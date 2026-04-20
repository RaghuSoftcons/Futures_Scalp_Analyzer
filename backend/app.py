"""FastAPI application for the standalone futures scalp analyzer."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, FastAPI

from futures_scalp_analyzer.models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import (
    FALLBACK_ACTIVE_CONTRACTS,
    PriceFeed,
    ROOT_DISPLAY_NAMES,
    SchwabQuotePriceFeed,
    normalize_root_symbol,
)
from futures_scalp_analyzer.service import analyze_request


def create_app(price_feed: PriceFeed | None = None) -> FastAPI:
    app = FastAPI(title="Futures Scalp Analyzer", version="0.1.0")
    app.state.price_feed = price_feed or SchwabQuotePriceFeed()

    def get_price_feed() -> PriceFeed:
        return app.state.price_feed

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/futures/active-contracts")
    async def active_contracts(
        feed: PriceFeed = Depends(get_price_feed),
    ) -> list[dict[str, str | None]]:
        if isinstance(feed, SchwabQuotePriceFeed):
            return await asyncio.to_thread(feed.list_active_contracts)

        return [
            {
                "root": root,
                "active_contract": contract,
                "expiration": None,
                "display_name": ROOT_DISPLAY_NAMES.get(root, root),
            }
            for root, contract in FALLBACK_ACTIVE_CONTRACTS.items()
        ]

    @app.get("/price/{symbol}")
    async def get_price(
        symbol: str,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> dict[str, Any]:
        normalized_symbol = symbol.upper().lstrip("/")
        root_symbol = normalize_root_symbol(symbol)
        if root_symbol is None:
            return {
                "symbol": normalized_symbol,
                "error": "unsupported_symbol",
                "detail": f"Unsupported symbol: {normalized_symbol}",
            }

        if isinstance(feed, SchwabQuotePriceFeed):
            quote_details = await asyncio.to_thread(feed.get_quote_details, symbol)
            if quote_details is None:
                return {
                    "symbol": normalized_symbol,
                    "error": "quote_unavailable",
                    "detail": f"Unable to fetch Schwab quote for {root_symbol}",
                }

            price = quote_details.get("last")
            if price is None:
                price = quote_details.get("mark")

            return {
                "symbol": normalized_symbol,
                "root": root_symbol,
                "active_contract": quote_details.get("active_contract"),
                "price": price,
                "source": quote_details.get("source", "schwab_live"),
                "last": quote_details.get("last"),
                "bid": quote_details.get("bid"),
                "ask": quote_details.get("ask"),
                "mark": quote_details.get("mark"),
                "timestamp": quote_details.get("timestamp"),
                "token_refreshed": quote_details.get("token_refreshed", False),
            }

        live_price = await feed.get_live_price(normalized_symbol)
        return {
            "symbol": normalized_symbol,
            "root": root_symbol,
            "active_contract": FALLBACK_ACTIVE_CONTRACTS.get(root_symbol),
            "price": live_price,
            "source": "price_feed",
        }

    @app.post("/futures/analyze")
    async def analyze(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> dict[str, Any]:
        response = await analyze_request(request, feed)
        payload = response.model_dump(mode="json")

        active_contract = None
        if isinstance(feed, SchwabQuotePriceFeed):
            active_contract = await asyncio.to_thread(feed.get_active_contract, request.symbol)
        else:
            root_symbol = normalize_root_symbol(request.symbol)
            if root_symbol is not None:
                active_contract = FALLBACK_ACTIVE_CONTRACTS.get(root_symbol)

        payload["active_contract"] = active_contract
        return payload

    @app.post("/futures/position", response_model=FuturesScalpAnalysisResponse)
    async def position(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        position_request = request.model_copy(update={"mode": "position_mgmt"})
        return await analyze_request(position_request, feed)

    return app


app = create_app()
