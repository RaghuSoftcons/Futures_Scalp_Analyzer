from __future__ import annotations

import asyncio

from futures_scalp_analyzer.apex_cache import ApexMarketDataCache
from futures_scalp_analyzer.apex_pipeline import MarketDataProvider, build_market_session


class CountingProvider(MarketDataProvider):
    data_source = "schwab"

    def __init__(self) -> None:
        self.quote_calls = 0
        self.bar_calls = 0

    def get_quote(self, symbol: str) -> dict:
        self.quote_calls += 1
        return {
            "symbol": symbol,
            "price": 110.0,
            "timestamp": "2026-04-27T14:00:00Z",
            "data_source": self.data_source,
        }

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict]:
        self.bar_calls += 1
        return [
            {
                "open": 100.0 + idx,
                "high": 100.5 + idx,
                "low": 99.5 + idx,
                "close": 100.0 + idx,
                "volume": 1000.0,
                "datetime": "2026-04-27T14:00:00Z",
            }
            for idx in range(80)
        ]


def test_cache_reuses_recent_payload_without_refetching_provider():
    provider = CountingProvider()
    cache = ApexMarketDataCache(poll_interval_seconds=60)

    first = asyncio.run(cache.get_payload("NQ", provider))
    second = asyncio.run(cache.get_payload("NQ", provider))

    assert first["market_data"]["symbol"] == "NQ"
    assert second["market_data"]["symbol"] == "NQ"
    assert provider.quote_calls == 1


def test_cache_snapshot_reports_cached_symbol_and_status():
    provider = CountingProvider()
    cache = ApexMarketDataCache(poll_interval_seconds=60)

    asyncio.run(cache.get_payload("NQ", provider))
    snapshot = asyncio.run(cache.snapshot())

    assert snapshot["poll_interval_seconds"] == 60
    assert snapshot["active_symbols"] == ["NQ"]
    assert snapshot["cached_symbols"] == ["NQ"]
    assert snapshot["cache"]["NQ"]["data_source"] == "schwab"


def test_market_session_confirms_sunday_afternoon_is_closed():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    session = build_market_session(datetime(2026, 5, 10, 13, 20, tzinfo=ZoneInfo("America/New_York")))

    assert session["status"] == "closed"
    assert "Futures reopen today at 6:00 PM ET" in session["message"]
