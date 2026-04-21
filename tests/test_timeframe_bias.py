from __future__ import annotations

import asyncio
from typing import Any

from futures_scalp_analyzer.models import FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import PriceFeed
from futures_scalp_analyzer.service import analyze_request


def _make_bars(start: float, step: float, count: int = 30) -> list[dict[str, float | int]]:
    bars: list[dict[str, float | int]] = []
    for i in range(count):
        close = start + (step * i)
        bars.append(
            {
                "open": close - 0.5,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 100 + i,
                "datetime": 1_700_000_000 + i,
            }
        )
    return bars


class _BiasTestFeed(PriceFeed):
    def __init__(self, bars_by_key: dict[tuple[str, int], list[dict[str, Any]]], live_price: float = 20_000.0) -> None:
        self._bars_by_key = bars_by_key
        self._live_price = live_price

    async def get_live_price(self, symbol: str) -> float | None:
        del symbol
        return self._live_price

    async def get_bars(
        self,
        symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        del symbol, period_type, period
        bars = self._bars_by_key.get((frequency_type, frequency))
        return bars or []


class _BiasWith3mFailureFeed(_BiasTestFeed):
    async def get_bars(
        self,
        symbol: str,
        frequency_type: str,
        frequency: int,
        period_type: str,
        period: int,
    ) -> list[dict[str, float | int | str]]:
        if frequency_type == "minute" and frequency == 3:
            raise RuntimeError("3m unavailable")
        return await super().get_bars(symbol, frequency_type, frequency, period_type, period)


def _request() -> FuturesScalpIdeaRequest:
    return FuturesScalpIdeaRequest(
        symbol="NQ",
        side="long",
        entry_price=20000.0,
        stop_price=19995.0,
        target_price=20010.0,
        contracts=1,
        account_size=50000,
        mode="idea_eval",
        session="RTH",
        realized_pnl_today=0.0,
        realized_loss_count_today=0,
        open_positions=[],
    )


def test_timeframe_bias_includes_3m_and_aligned_long():
    bars = _make_bars(start=100.0, step=1.0)
    daily_bars = [{"high": 101.0, "low": 99.0}, {"high": 102.0, "low": 98.0}]
    feed = _BiasTestFeed(
        {
            ("minute", 1): bars,
            ("minute", 3): bars,
            ("minute", 5): bars,
            ("minute", 15): bars,
            ("daily", 1): daily_bars,
        }
    )

    response = asyncio.run(analyze_request(_request(), feed))
    assert response.bias_1m == "long"
    assert response.bias_3m == "long"
    assert response.bias_5m == "long"
    assert response.bias_15m == "long"
    assert response.timeframe_alignment == "aligned_long"


def test_timeframe_bias_defaults_3m_to_neutral_when_fetch_fails():
    uptrend_bars = _make_bars(start=100.0, step=1.0)
    flat_bars = _make_bars(start=100.0, step=0.0)
    daily_bars = [{"high": 101.0, "low": 99.0}, {"high": 102.0, "low": 98.0}]
    feed = _BiasWith3mFailureFeed(
        {
            ("minute", 1): uptrend_bars,
            ("minute", 5): flat_bars,
            ("minute", 15): flat_bars,
            ("daily", 1): daily_bars,
        }
    )

    response = asyncio.run(analyze_request(_request(), feed))
    assert response.bias_1m == "long"
    assert response.bias_3m == "neutral"
    assert response.bias_5m == "neutral"
    assert response.bias_15m == "neutral"
    assert response.timeframe_alignment == "neutral"
