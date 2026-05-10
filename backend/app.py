"""FastAPI application for the standalone futures scalp analyzer."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from futures_scalp_analyzer.apex import build_platform_status
from futures_scalp_analyzer.apex_cache import ApexMarketDataCache
from futures_scalp_analyzer.apex_dashboard import render_apex_dashboard
from futures_scalp_analyzer.apex_pipeline import (
    MarketDataProvider,
    MockMarketDataProvider,
    SchwabMarketDataProvider,
    build_technical_readout,
    build_payload,
    generate_trade_decision,
)
from futures_scalp_analyzer.models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import (
    FALLBACK_ACTIVE_CONTRACTS,
    PriceFeed,
    ROOT_DISPLAY_NAMES,
    SchwabQuotePriceFeed,
    normalize_root_symbol,
)
from futures_scalp_analyzer.risk import evaluate_session_status
from futures_scalp_analyzer.service import analyze_request

EASTERN_TZ = ZoneInfo("America/New_York")


def create_app(price_feed: PriceFeed | None = None) -> FastAPI:
    app = FastAPI(title="Futures Scalp Analyzer", version="0.1.0")
    app.state.price_feed = price_feed or SchwabQuotePriceFeed()
    app.state.apex_provider = None
    app.state.apex_cache = ApexMarketDataCache()

    def get_price_feed() -> PriceFeed:
        return app.state.price_feed

    def parse_quote_timestamp(timestamp: str | None) -> datetime | None:
        if not timestamp:
            return None
        try:
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None

    def is_futures_market_open(now_utc: datetime | None = None) -> bool:
        now = (now_utc or datetime.now(timezone.utc)).astimezone(EASTERN_TZ)
        weekday = now.weekday()
        hour_minute = (now.hour, now.minute)

        if weekday == 5:
            return False
        if weekday == 6:
            return hour_minute >= (18, 0)
        if weekday == 4:
            return hour_minute < (17, 0)
        return not ((17, 0) <= hour_minute < (18, 0))

    def build_market_status(timestamp: str | None) -> dict[str, Any]:
        quote_dt = parse_quote_timestamp(timestamp)
        now_utc = datetime.now(timezone.utc)
        market_open = is_futures_market_open(now_utc)
        age_seconds = None
        if quote_dt is not None:
            age_seconds = max(int((now_utc - quote_dt.astimezone(timezone.utc)).total_seconds()), 0)
        is_live = market_open and age_seconds is not None and age_seconds <= 120
        status = "live" if is_live else "market_closed" if not market_open else "stale"
        return {
            "market_status": status,
            "is_market_open": market_open,
            "is_live": is_live,
            "quote_age_seconds": age_seconds,
        }

    def get_apex_provider(feed: PriceFeed) -> MarketDataProvider:
        configured_provider = getattr(app.state, "apex_provider", None)
        if configured_provider is not None:
            return configured_provider
        if isinstance(feed, SchwabQuotePriceFeed):
            return SchwabMarketDataProvider(feed)
        return MockMarketDataProvider()

    def should_use_apex_cache(
        market_time: datetime | None,
        news_title: str | None,
        social_title: str | None,
    ) -> bool:
        return market_time is None and news_title is None and social_title is None

    async def build_apex_payload_for_request(
        symbol: str,
        feed: PriceFeed,
        context: dict[str, Any],
        market_time: datetime | None,
        news_title: str | None,
        social_title: str | None,
    ) -> dict[str, Any]:
        provider = get_apex_provider(feed)
        if should_use_apex_cache(market_time, news_title, social_title):
            return await app.state.apex_cache.get_payload(symbol, provider)
        return await asyncio.to_thread(
            build_payload,
            symbol,
            provider,
            None,
            context,
            None,
            True,
            market_time,
        )

    def apply_apex_risk_state(
        payload: dict[str, Any],
        daily_loss: float,
        estimated_risk: float,
        trades_today: int,
        consecutive_losses: int,
        locked_out: bool,
    ) -> dict[str, Any]:
        payload["risk_state"] = {
            "daily_loss": round(float(daily_loss), 2),
            "estimated_risk": round(float(estimated_risk), 2),
            "trades_today": int(trades_today),
            "consecutive_losses": int(consecutive_losses),
            "locked_out": bool(locked_out),
        }
        return payload

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    async def start_apex_cache() -> None:
        app.state.apex_cache.start(lambda: get_apex_provider(app.state.price_feed))

    @app.on_event("shutdown")
    async def stop_apex_cache() -> None:
        await app.state.apex_cache.stop()

    @app.get("/apex/status")
    async def apex_status() -> dict[str, Any]:
        return build_platform_status()

    @app.get("/apex/cache/status")
    async def apex_cache_status() -> dict[str, Any]:
        return await app.state.apex_cache.snapshot()

    @app.get("/apex/dashboard", response_class=HTMLResponse)
    async def apex_dashboard() -> HTMLResponse:
        return HTMLResponse(render_apex_dashboard())

    @app.get("/apex/payload/{symbol}")
    async def apex_payload(
        symbol: str,
        daily_loss: float = 0.0,
        estimated_risk: float = 0.0,
        trades_today: int = 0,
        consecutive_losses: int = 0,
        locked_out: bool = False,
        news_title: str | None = None,
        social_title: str | None = None,
        market_time: datetime | None = None,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> dict[str, Any]:
        context = {
            "news": [{"title": news_title, "source": "API", "url": ""}] if news_title else [],
            "social": [{"title": social_title, "source": "Truth Social", "url": ""}] if social_title else [],
        }
        payload = await build_apex_payload_for_request(
            symbol,
            feed,
            context,
            market_time,
            news_title,
            social_title,
        )
        return apply_apex_risk_state(
            payload,
            daily_loss=daily_loss,
            estimated_risk=estimated_risk,
            trades_today=trades_today,
            consecutive_losses=consecutive_losses,
            locked_out=locked_out,
        )

    @app.get("/apex/decision/{symbol}")
    async def apex_decision(
        symbol: str,
        daily_loss: float = 0.0,
        estimated_risk: float = 0.0,
        trades_today: int = 0,
        consecutive_losses: int = 0,
        locked_out: bool = False,
        news_title: str | None = None,
        social_title: str | None = None,
        market_time: datetime | None = None,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> dict[str, Any]:
        context = {
            "news": [{"title": news_title, "source": "API", "url": ""}] if news_title else [],
            "social": [{"title": social_title, "source": "Truth Social", "url": ""}] if social_title else [],
        }
        payload = await build_apex_payload_for_request(
            symbol,
            feed,
            context,
            market_time,
            news_title,
            social_title,
        )
        payload = apply_apex_risk_state(
            payload,
            daily_loss=daily_loss,
            estimated_risk=estimated_risk,
            trades_today=trades_today,
            consecutive_losses=consecutive_losses,
            locked_out=locked_out,
        )
        decision = generate_trade_decision(payload)
        technical_readout = build_technical_readout(payload, decision)
        return {
            "payload": payload,
            "decision": decision,
            "technical_readout": technical_readout,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

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
            } | build_market_status(quote_details.get("timestamp"))
        live_price = await feed.get_live_price(normalized_symbol)
        return {
            "symbol": normalized_symbol,
            "root": root_symbol,
            "active_contract": FALLBACK_ACTIVE_CONTRACTS.get(root_symbol),
            "price": live_price,
            "source": "price_feed",
        }

    @app.get("/futures/session")
    async def session_status(
        account_size: int,
        losses_today: int,
        pnl_today: float,
    ) -> dict[str, Any]:
        session = evaluate_session_status(account_size, losses_today, pnl_today)
        return {
            "can_trade": session["can_trade"],
            "reason": session["reason"],
            "trades_remaining": session["trades_remaining"],
            "dollars_to_target": session["dollars_to_target"],
            "dollars_to_limit": session["dollars_to_limit"],
            "session_status": session["session_status"],
        }

    @app.post("/futures/analyze")
    async def analyze(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        try:
            return await analyze_request(request, feed)
        except Exception as e:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "analysis_failed",
                    "detail": str(e),
                    "symbol": request.symbol,
                    "side": request.side,
                },
            )

    @app.post("/futures/position")
    async def position(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        try:
            position_request = request.model_copy(update={"mode": "position_mgmt"})
            return await analyze_request(position_request, feed)
        except Exception as e:
            return JSONResponse(
                status_code=200,
                content={
                    "error": "analysis_failed",
                    "detail": str(e),
                    "symbol": request.symbol,
                    "side": request.side,
                },
            )

    @app.get("/privacy")
    async def privacy_policy():
        return {
            "service": "Apex Scalp Engine",
            "description": "This API provides live futures price data and scalp trade analysis for manual trader decision support only. It does not place or route orders.",
            "data_collected": "Optional trader_id and trade_plan_id may be submitted for accountability context; no persistence is added in this phase.",
            "contact": "For questions, contact the account owner via ChatGPT.",
            "usage": "This service is for personal trading analysis only and does not provide financial advice."
        }

    return app


app = create_app()
