"""FastAPI application for the standalone futures scalp analyzer."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
import logging
import os
from typing import Any, Mapping
import urllib.parse

import httpx
from fastapi import Depends, FastAPI

from futures_scalp_analyzer.models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import PriceFeed, SchwabQuotePriceFeed
from futures_scalp_analyzer.service import analyze_request

LOGGER = logging.getLogger(__name__)

SCHWAB_API_BASE_URL = "https://api.schwabapi.com"
SCHWAB_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
SHORT_TO_FRONT_MONTH_SYMBOL: dict[str, str] = {
    "NQ": "/NQM26",
    "MNQ": "/MNQM26",
    "ES": "/ESM26",
    "MES": "/MESM26",
    "GC": "/GCM26",
    "MGC": "/MGCM26",
    "CL": "/CLK26",
    "MCL": "/MCLK26",
    "SI": "/SIN26",
    "SIL": "/SILN26",
    "ZB": "/ZBM26",
    "UB": "/UBM26",
}

_QUOTE_ACCESS_TOKEN = os.getenv("SCHWAB_ACCESS_TOKEN")
_QUOTE_REFRESH_TOKEN = os.getenv("SCHWAB_REFRESH_TOKEN")
_QUOTE_CLIENT_ID = os.getenv("SCHWAB_CLIENT_ID")
_QUOTE_CLIENT_SECRET = os.getenv("SCHWAB_CLIENT_SECRET")


def _fetch_quote_response(schwab_symbol: str, access_token: str | None) -> httpx.Response:
    encoded_symbol = urllib.parse.quote(schwab_symbol, safe="")
    return httpx.get(
        f"{SCHWAB_API_BASE_URL}/marketdata/v1/quotes?symbols={encoded_symbol}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10.0,
    )


def _refresh_quote_access_token() -> bool:
    global _QUOTE_ACCESS_TOKEN

    if not all([_QUOTE_REFRESH_TOKEN, _QUOTE_CLIENT_ID, _QUOTE_CLIENT_SECRET]):
        return False

    credentials = base64.b64encode(
        f"{_QUOTE_CLIENT_ID}:{_QUOTE_CLIENT_SECRET}".encode()
    ).decode()

    response = httpx.post(
        SCHWAB_TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": _QUOTE_REFRESH_TOKEN,
        },
        timeout=10.0,
    )
    try:
        LOGGER.info(
            "Schwab token refresh status=%s body=%s",
            response.status_code,
            response.text,
        )
    except Exception:
        LOGGER.exception("Failed to log Schwab token refresh response")
    if response.status_code >= 400:
        return False

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        return False

    _QUOTE_ACCESS_TOKEN = str(access_token)
    return True


def _extract_quote_payload(payload: Mapping[str, Any], schwab_symbol: str) -> Mapping[str, Any] | None:
    direct_payload = payload.get(schwab_symbol)
    if isinstance(direct_payload, Mapping):
        quote_payload = direct_payload.get("quote")
        if isinstance(quote_payload, Mapping):
            return quote_payload
        return direct_payload

    quote_payload = payload.get("quote")
    if isinstance(quote_payload, Mapping):
        return quote_payload

    if "lastPrice" in payload or "mark" in payload:
        return payload

    return None


def _format_quote_timestamp(quote_payload: Mapping[str, Any]) -> str | None:
    raw_timestamp = (
        quote_payload.get("quoteTime")
        or quote_payload.get("tradeTime")
        or quote_payload.get("timestamp")
    )
    if raw_timestamp is None:
        return None

    if isinstance(raw_timestamp, (int, float)):
        timestamp_value = float(raw_timestamp)
        if timestamp_value > 1_000_000_000_000:
            timestamp_value /= 1000.0
        return datetime.fromtimestamp(timestamp_value, tz=UTC).isoformat().replace("+00:00", "Z")

    if isinstance(raw_timestamp, str):
        return raw_timestamp

    return None


def create_app(price_feed: PriceFeed | None = None) -> FastAPI:
    app = FastAPI(title="Futures Scalp Analyzer", version="0.1.0")
    app.state.price_feed = price_feed or SchwabQuotePriceFeed()

    def get_price_feed() -> PriceFeed:
        return app.state.price_feed

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/price/{symbol}")
    async def get_price(symbol: str) -> dict[str, Any]:
        normalized_symbol = symbol.upper()
        schwab_symbol = SHORT_TO_FRONT_MONTH_SYMBOL.get(normalized_symbol)
        if schwab_symbol is None:
            return {
                "symbol": normalized_symbol,
                "error": "unsupported_symbol",
                "detail": f"Unsupported symbol: {normalized_symbol}",
            }

        global _QUOTE_ACCESS_TOKEN
        token_refreshed = False

        if not _QUOTE_ACCESS_TOKEN:
            return {
                "symbol": normalized_symbol,
                "error": "missing_access_token",
                "detail": "SCHWAB_ACCESS_TOKEN is not set",
            }

        try:
            response = _fetch_quote_response(schwab_symbol, _QUOTE_ACCESS_TOKEN)
            if response.status_code == 401:
                token_refreshed = _refresh_quote_access_token()
                if not token_refreshed:
                    return {
                        "symbol": normalized_symbol,
                        "error": "token_refresh_failed",
                        "detail": "Unable to refresh Schwab access token after 401 response",
                    }
                response = _fetch_quote_response(schwab_symbol, _QUOTE_ACCESS_TOKEN)

            if response.status_code >= 400:
                return {
                    "symbol": normalized_symbol,
                    "error": "quote_request_failed",
                    "detail": f"Schwab quote request returned status {response.status_code}",
                }

            payload = response.json()
            quote_payload = _extract_quote_payload(payload, schwab_symbol)
            if quote_payload is None:
                return {
                    "symbol": normalized_symbol,
                    "error": "quote_parse_failed",
                    "detail": f"No quote payload found for {schwab_symbol}",
                }

            return {
                "symbol": normalized_symbol,
                "schwab_symbol": schwab_symbol,
                "last": quote_payload.get("lastPrice"),
                "bid": quote_payload.get("bidPrice"),
                "ask": quote_payload.get("askPrice"),
                "mark": quote_payload.get("mark"),
                "timestamp": _format_quote_timestamp(quote_payload),
                "token_refreshed": token_refreshed,
            }
        except Exception as exc:
            LOGGER.exception("Failed to fetch quote for %s", normalized_symbol)
            return {
                "symbol": normalized_symbol,
                "error": "quote_fetch_error",
                "detail": str(exc),
            }

    @app.post("/futures/analyze", response_model=FuturesScalpAnalysisResponse)
    async def analyze(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        return await analyze_request(request, feed)

    @app.post("/futures/position", response_model=FuturesScalpAnalysisResponse)
    async def position(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        position_request = request.model_copy(update={"mode": "position_mgmt"})
        return await analyze_request(position_request, feed)

    return app


app = create_app()
