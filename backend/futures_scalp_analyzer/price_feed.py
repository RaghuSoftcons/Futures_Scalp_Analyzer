"""Read-only live price abstraction for Schwab quote access."""
from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
import logging
import os
from typing import Any, Mapping

import httpx

from .symbols import SUPPORTED_SYMBOLS

LOGGER = logging.getLogger(__name__)


class PriceFeed(ABC):
    """Read-only interface for fetching a live futures price."""

    @abstractmethod
    async def get_live_price(self, symbol: str) -> float | None:
        raise NotImplementedError


class StaticPriceFeed(PriceFeed):
    """Simple in-memory feed useful for tests or local development."""

    def __init__(self, prices: Mapping[str, float] | None = None) -> None:
        self._prices = dict(prices or {})

    async def get_live_price(self, symbol: str) -> float | None:
        return self._prices.get(symbol.upper())


class SchwabQuotePriceFeed(PriceFeed):
    """Read-only Schwab quote client with in-memory token refresh."""

    def __init__(self) -> None:
        self._access_token = os.getenv("SCHWAB_ACCESS_TOKEN")
        self._refresh_token = os.getenv("SCHWAB_REFRESH_TOKEN")
        self._client_id = os.getenv("SCHWAB_CLIENT_ID")
        self._client_secret = os.getenv("SCHWAB_CLIENT_SECRET")
        self._api_base_url = os.getenv("SCHWAB_API_BASE_URL", "https://api.schwabapi.com").rstrip("/")
        self._token_url = os.getenv("SCHWAB_TOKEN_URL", "https://api.schwabapi.com/v1/oauth/token")

    async def get_live_price(self, symbol: str) -> float | None:
        return await asyncio.to_thread(self.get_price, symbol)

    def get_price(self, symbol: str) -> float | None:
        try:
            spec = SUPPORTED_SYMBOLS[symbol.upper()]
        except KeyError:
            LOGGER.warning("Unsupported symbol requested from Schwab feed: %s", symbol)
            return None
        if not self._access_token:
            LOGGER.warning("SCHWAB_ACCESS_TOKEN is not set; live price unavailable for %s", symbol)
            return None
        quote = self._fetch_quote(spec.schwab_symbol, self._access_token)
        if quote is None:
            return None
        if quote.status_code == 401:
            if not self._refresh_access_token():
                LOGGER.warning("Schwab token refresh failed; live price unavailable for %s", symbol)
                return None
            quote = self._fetch_quote(spec.schwab_symbol, self._access_token)
            if quote is None or quote.status_code == 401:
                LOGGER.warning("Schwab quote retry failed after refresh for %s", symbol)
                return None
        if quote.status_code >= 400:
            LOGGER.warning("Schwab quote request failed for %s with status %s", symbol, quote.status_code)
            return None
        try:
            payload = quote.json()
            quote_data = self._extract_quote_payload(payload, spec.schwab_symbol)
            if quote_data is None:
                return None
            last_price = quote_data.get("lastPrice")
            if last_price is not None:
                return float(last_price)
            mark = quote_data.get("mark")
            if mark is not None:
                return float(mark)
        except Exception:
            LOGGER.exception("Failed to parse Schwab quote payload for %s", symbol)
            return None
        return None

    def _fetch_quote(self, schwab_symbol: str, access_token: str | None) -> httpx.Response | None:
        try:
            import urllib.parse
            encoded_symbol = urllib.parse.quote(schwab_symbol, safe="")
            return httpx.get(
                f"{self._api_base_url}/marketdata/v1/quotes?symbols={encoded_symbol}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0,
            )
        except httpx.HTTPError:
            LOGGER.exception("Network error while fetching Schwab quote for %s", schwab_symbol)
            return None
        except Exception:
            LOGGER.exception("Unexpected error while fetching Schwab quote for %s", schwab_symbol)
            return None

    def _refresh_access_token(self) -> bool:
        if not all([self._refresh_token, self._client_id, self._client_secret]):
            LOGGER.warning("Schwab refresh credentials are incomplete")
            return False
        try:
            credentials = base64.b64encode(
                f"{self._client_id}:{self._client_secret}".encode()
            ).decode()
            response = httpx.post(
                self._token_url,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=10.0,
            )
            LOGGER.info(
                "Schwab token refresh status=%s body=%s",
                response.status_code,
                response.text,
            )
            if response.status_code >= 400:
                LOGGER.warning("Schwab token refresh returned status %s", response.status_code)
                return False
            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                LOGGER.warning("Schwab token refresh response did not include access_token")
                return False
            self._access_token = str(access_token)
            return True
        except httpx.HTTPError:
            LOGGER.exception("Network error while refreshing Schwab access token")
            return False
        except Exception:
            LOGGER.exception("Unexpected error while refreshing Schwab access token")
            return False

    @staticmethod
    def _extract_quote_payload(payload: Mapping[str, Any], schwab_symbol: str) -> Mapping[str, Any] | None:
        direct_payload = payload.get(schwab_symbol)
        if isinstance(direct_payload, Mapping):
            nested_quote = direct_payload.get("quote")
            if isinstance(nested_quote, Mapping):
                return nested_quote
            return direct_payload
        return None
