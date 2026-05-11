"""Apex Scalp Engine market data payload and decision pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .price_feed import SchwabQuotePriceFeed
from .symbols import get_instrument_metadata


MANUAL_EXECUTION_NOTE = "Manual execution only. No broker order has been placed."
DISPLAY_CONTEXT_RULE = "Display only. Not used in trade decisions."
STALE_MARKET_DATA_SECONDS = 120
DATA_GATE_OPEN = "open"
DATA_GATE_CLOSED = "closed"
REQUIRED_MARKET_DATA_FIELDS = ("price", "vwap", "ema9", "ema20", "rsi", "trend")
MULTI_TIMEFRAMES = ("30m", "15m", "5m", "3m", "1m")
MTF_REQUIRED_BARS = 50
MTF_LOOKBACK_DAYS = {
    "30m": 10,
    "15m": 5,
    "5m": 3,
    "3m": 3,
    "1m": 2,
}
EASTERN_TZ = ZoneInfo("America/New_York")

DEFAULT_RISK_SETTINGS: dict[str, float | int] = {
    "max_daily_loss": 2000.00,
    "max_risk_per_trade": 500.00,
    "preferred_risk_per_trade": 300.00,
    "minimum_rr_ratio": 2.00,
    "preferred_rr_ratio": 3.00,
    "max_trades_per_day": 5,
    "max_consecutive_losses": 3,
}


class MarketDataProvider(ABC):
    """Synchronous Apex market data interface."""

    data_source: str

    @abstractmethod
    def get_quote(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict[str, Any]]:
        raise NotImplementedError


class SchwabMarketDataProvider(MarketDataProvider):
    """Apex wrapper around the existing read-only Schwab price feed."""

    data_source = "schwab"

    def __init__(self, feed: SchwabQuotePriceFeed | None = None) -> None:
        self.feed = feed or SchwabQuotePriceFeed()

    def get_quote(self, symbol: str) -> dict[str, Any]:
        details = self.feed.get_quote_details(symbol)
        if not details:
            return {"symbol": symbol.upper(), "price": None, "data_source": "unavailable"}
        price = details.get("last")
        if price is None:
            price = details.get("mark")
        return {
            "symbol": symbol.upper(),
            "price": float(price) if price is not None else None,
            "bid": details.get("bid"),
            "ask": details.get("ask"),
            "active_contract": details.get("active_contract"),
            "timestamp": details.get("timestamp"),
            "data_source": self.data_source,
        }

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict[str, Any]]:
        frequency_type, frequency = _parse_timeframe(timeframe)
        return list(self.feed.get_price_history(symbol, frequency_type, frequency, "day", lookback))


class MockMarketDataProvider(MarketDataProvider):
    """Deterministic local provider for tests and Schwab fallback."""

    data_source = "mock"

    def __init__(
        self,
        quote: dict[str, Any] | None = None,
        bars: list[dict[str, Any]] | None = None,
    ) -> None:
        self._quote = quote or {"symbol": "NQ", "price": 101.0}
        self._bars = bars

    def get_quote(self, symbol: str) -> dict[str, Any]:
        quote = dict(self._quote)
        quote["symbol"] = symbol.upper()
        quote["data_source"] = self.data_source
        quote.setdefault("timestamp", _utc_now())
        return quote

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict[str, Any]]:
        del symbol, lookback
        if self._bars is not None:
            return [dict(bar) for bar in self._bars]
        return make_mock_bars(timeframe=timeframe)


def make_mock_bars(
    count: int = 80,
    start: float = 100.0,
    step: float = 0.25,
    timeframe: str = "1m",
) -> list[dict[str, Any]]:
    bars: list[dict[str, Any]] = []
    base_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    interval_ms = _timeframe_minutes(timeframe) * 60_000
    pullbacks = (0.0, 0.35, -0.15, 0.25, -0.30, 0.10)
    for idx in range(count):
        close = start + (idx * step * 0.35) + pullbacks[idx % len(pullbacks)]
        bars.append(
            {
                "open": close - 0.1,
                "high": close + 0.25,
                "low": close - 0.25,
                "close": close,
                "volume": 1000 + idx,
                "datetime": base_time - ((count - idx - 1) * interval_ms),
            }
        )
    return bars


def calculate_ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    seed = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1)
    ema_value = seed
    for value in values[period:]:
        ema_value = (value - ema_value) * multiplier + ema_value
    return ema_value


def calculate_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(1, len(closes)):
        delta = closes[idx] - closes[idx - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for idx in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[idx]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[idx]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_vwap(bars: list[dict[str, Any]]) -> float | None:
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for bar in bars:
        high = _to_float(bar.get("high"))
        low = _to_float(bar.get("low"))
        close = _to_float(bar.get("close"))
        volume = _to_float(bar.get("volume"))
        if high is None or low is None or close is None or volume is None:
            continue
        typical_price = (high + low + close) / 3.0
        cumulative_pv += typical_price * volume
        cumulative_volume += volume
    if cumulative_volume == 0:
        return None
    return cumulative_pv / cumulative_volume


def classify_trend(price: float | None, vwap: float | None, ema9: float | None, ema20: float | None) -> str:
    if price is None or vwap is None or ema9 is None or ema20 is None:
        return "neutral"
    if price > vwap and ema9 > ema20:
        return "uptrend"
    if price < vwap and ema9 < ema20:
        return "downtrend"
    return "neutral"


def build_payload(
    symbol: str,
    provider: MarketDataProvider | None = None,
    fallback_provider: MarketDataProvider | None = None,
    context: dict[str, Any] | None = None,
    risk_settings: dict[str, float | int] | None = None,
    allow_mock_fallback: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the Apex market data, context, and risk payload."""

    selected_provider = provider or SchwabMarketDataProvider()
    fallback = fallback_provider or MockMarketDataProvider()
    active_provider = selected_provider

    quote = selected_provider.get_quote(symbol)
    bars = selected_provider.get_bars(symbol, "1m", 1)
    bars = _normalize_bars(bars)
    data_source = selected_provider.data_source
    provider_status = _provider_status_for_market_data(quote, bars)

    if not _has_quote(quote) and allow_mock_fallback:
        quote = fallback.get_quote(symbol)
        bars = fallback.get_bars(symbol, "1m", 1)
        bars = _normalize_bars(bars)
        if _has_valid_market_data(quote, bars):
            active_provider = fallback
            data_source = fallback.data_source
            provider_status = "fallback"
        else:
            data_source = "unavailable"
            provider_status = "unavailable"
    elif not _has_quote(quote):
        data_source = "unavailable"
        provider_status = "unavailable"

    market_session = build_market_session(now)
    instrument = build_instrument_payload(symbol)
    market_data = _build_market_data(symbol, quote, bars, data_source, provider_status)
    if market_session["status"] in {"closed", "maintenance"}:
        market_data["data_gate_status"] = DATA_GATE_CLOSED
        market_data["data_gate_reason"] = market_session["data_gate_reason"]
    multi_timeframe_trend = build_multi_timeframe_trend(symbol, active_provider, data_source, provider_status)
    data_diagnostics = build_data_diagnostics(
        symbol=symbol,
        quote=quote,
        bars=bars,
        market_data=market_data,
        multi_timeframe_trend=multi_timeframe_trend,
        data_source=data_source,
        provider_status=provider_status,
        market_session=market_session,
    )
    return {
        "instrument": instrument,
        "market_data": market_data,
        "multi_timeframe_trend": multi_timeframe_trend,
        "market_session": market_session,
        "data_diagnostics": data_diagnostics,
        "context": _build_display_context(context),
        "risk_settings": _format_risk_settings(risk_settings or DEFAULT_RISK_SETTINGS),
        "risk_state": {
            "daily_loss": 0.00,
            "estimated_risk": 0.00,
            "trades_today": 0,
            "consecutive_losses": 0,
            "locked_out": False,
        },
        "timestamp": _utc_now(),
    }


def generate_trade_decision(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate a risk-first, technical-only Apex Phase 1 decision."""

    risk_status, risk_reason = _evaluate_risk(payload)
    display_context = {
        "news": list(payload.get("context", {}).get("news", [])),
        "social": list(payload.get("context", {}).get("social", [])),
        "context_rule": DISPLAY_CONTEXT_RULE,
    }
    market_data = payload.get("market_data", {})
    market_session = payload.get("market_session", {})
    instrument = payload.get("instrument", {})
    data_gate_status, data_gate_reason = _evaluate_data_gate(market_data)

    if instrument and not bool(instrument.get("decisions_enabled", True)):
        data_gate_status = DATA_GATE_CLOSED
        data_gate_reason = "asset class not enabled for Apex decisions"

    if market_session.get("status") in {"closed", "maintenance"}:
        data_gate_status = DATA_GATE_CLOSED
        data_gate_reason = str(market_session.get("data_gate_reason") or "market closed")

    if risk_status == "blocked":
        return {
            "recommendation": "NO TRADE",
            "reason": "technical only",
            "confidence": 0,
            "risk_status": "blocked",
            "data_gate_status": data_gate_status,
            "data_gate_reason": data_gate_reason,
            "no_trade_reason": risk_reason,
            "manual_execution_note": MANUAL_EXECUTION_NOTE,
            "display_context": display_context,
        }

    if data_gate_status == DATA_GATE_CLOSED:
        return {
            "recommendation": "NO TRADE",
            "reason": "technical only",
            "confidence": 0,
            "risk_status": "allowed",
            "data_gate_status": DATA_GATE_CLOSED,
            "data_gate_reason": data_gate_reason,
            "no_trade_reason": data_gate_reason,
            "manual_execution_note": MANUAL_EXECUTION_NOTE,
            "display_context": display_context,
        }

    price = _to_float(market_data.get("price"))
    vwap = _to_float(market_data.get("vwap"))
    ema9 = _to_float(market_data.get("ema9"))
    ema20 = _to_float(market_data.get("ema20"))
    rsi = _to_float(market_data.get("rsi"))
    trend = market_data.get("trend")

    recommendation = "NO TRADE"
    confidence = 0
    no_trade_reason = "technical criteria not met"

    if (
        trend == "uptrend"
        and price is not None
        and vwap is not None
        and ema9 is not None
        and ema20 is not None
        and rsi is not None
        and price > vwap
        and ema9 > ema20
        and 50.0 <= rsi <= 70.0
    ):
        recommendation = "LONG"
        confidence = 70
        no_trade_reason = ""
    elif (
        trend == "downtrend"
        and price is not None
        and vwap is not None
        and ema9 is not None
        and ema20 is not None
        and rsi is not None
        and price < vwap
        and ema9 < ema20
        and 30.0 <= rsi <= 50.0
    ):
        recommendation = "SHORT"
        confidence = 70
        no_trade_reason = ""

    return {
        "recommendation": recommendation,
        "reason": "technical only",
        "confidence": confidence,
        "risk_status": "allowed",
        "data_gate_status": DATA_GATE_OPEN,
        "data_gate_reason": "",
        "no_trade_reason": no_trade_reason,
        "manual_execution_note": MANUAL_EXECUTION_NOTE,
        "display_context": display_context,
    }


def build_technical_readout(payload: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Describe market relationships using only technical payload and decision data."""

    market_data = payload.get("market_data", {})
    price = _to_float(market_data.get("price"))
    vwap = _to_float(market_data.get("vwap"))
    ema9 = _to_float(market_data.get("ema9"))
    ema20 = _to_float(market_data.get("ema20"))
    rsi = _to_float(market_data.get("rsi"))

    price_vs_vwap = _price_relationship("VWAP", price, vwap)
    price_vs_ema9 = _price_relationship("EMA 9", price, ema9)
    price_vs_ema20 = _price_relationship("EMA 20", price, ema20)
    ma_alignment = _moving_average_alignment(ema9, ema20)
    rsi_comment = _rsi_comment(rsi)
    trend_comment = _trend_comment(price, vwap, ema9, ema20)
    decision_comment = _decision_comment(decision)

    summary = (
        f"{price_vs_vwap} {price_vs_ema9} {price_vs_ema20} "
        f"{ma_alignment} {rsi_comment} {trend_comment} {decision_comment}"
    )
    data_gate_status = str(decision.get("data_gate_status") or market_data.get("data_gate_status") or "").lower()
    if data_gate_status == DATA_GATE_CLOSED:
        safety_reason = str(decision.get("data_gate_reason") or market_data.get("data_gate_reason") or "")
        market_session = payload.get("market_session", {})
        session_message = str(market_session.get("message") or "")
        if market_session.get("status") in {"closed", "maintenance"} and session_message:
            safety_note = f"{session_message}"
        elif "stale" in safety_reason.lower():
            safety_note = (
                "Market data is stale. Technical readout is shown for context only. "
                "Trade recommendations are blocked until data freshness is restored."
            )
        else:
            safety_note = (
                "Market data is not usable. Technical readout is shown for context only. "
                "Trade recommendations are blocked until data quality is restored."
            )
        summary = f"{safety_note} {summary}"
    summary = f"{summary} {_multi_timeframe_summary_sentence(payload.get('multi_timeframe_trend', {}))}"

    return {
        "summary": summary,
        "price_relationships": [price_vs_vwap, price_vs_ema9, price_vs_ema20],
        "moving_average_alignment": ma_alignment,
        "rsi_comment": rsi_comment,
        "trend_comment": trend_comment,
        "decision_comment": decision_comment,
    }


def build_multi_timeframe_trend(
    symbol: str,
    provider: MarketDataProvider,
    data_source: str,
    provider_status: str,
) -> dict[str, Any]:
    timeframes: dict[str, dict[str, Any]] = {}
    for timeframe in MULTI_TIMEFRAMES:
        bars = _get_multi_timeframe_bars(provider, symbol, timeframe)
        timeframes[timeframe] = build_timeframe_trend(
            timeframe=timeframe,
            bars=bars,
            data_source=data_source,
            provider_status=provider_status,
        )

    trend_values = [row["trend"] for row in timeframes.values() if not row["is_stale"]]
    bullish_count = sum(1 for trend in trend_values if trend in {"strong_bullish", "bullish"})
    bearish_count = sum(1 for trend in trend_values if trend in {"strong_bearish", "bearish"})
    all_timeframes_aligned = len(trend_values) == len(MULTI_TIMEFRAMES) and (
        bullish_count == len(MULTI_TIMEFRAMES) or bearish_count == len(MULTI_TIMEFRAMES)
    )
    if bullish_count >= 3:
        dominant_trend = "bullish"
    elif bearish_count >= 3:
        dominant_trend = "bearish"
    else:
        dominant_trend = "mixed"

    any_stale = any(row["is_stale"] for row in timeframes.values())
    if any_stale:
        data_gate_status = DATA_GATE_CLOSED
    elif data_source in {"schwab"} and provider_status == "connected":
        data_gate_status = DATA_GATE_OPEN
    else:
        data_gate_status = DATA_GATE_CLOSED

    return {
        "symbol": symbol.upper(),
        "source": data_source,
        "timeframes": timeframes,
        "alignment_summary": _alignment_summary(dominant_trend, bullish_count, bearish_count, any_stale),
        "dominant_trend": dominant_trend,
        "all_timeframes_aligned": all_timeframes_aligned,
        "data_gate_status": data_gate_status,
    }


def _get_multi_timeframe_bars(provider: MarketDataProvider, symbol: str, timeframe: str) -> list[dict[str, Any]]:
    lookback = MTF_LOOKBACK_DAYS.get(timeframe, 2)
    try:
        bars = _normalize_bars(provider.get_bars(symbol, timeframe, lookback))
    except Exception:
        bars = []

    if timeframe != "3m" or len(bars) >= MTF_REQUIRED_BARS:
        return bars

    try:
        one_minute_bars = _normalize_bars(provider.get_bars(symbol, "1m", max(lookback, MTF_LOOKBACK_DAYS["1m"])))
    except Exception:
        one_minute_bars = []
    aggregated_bars = _aggregate_minute_bars(one_minute_bars, 3)
    if len(aggregated_bars) > len(bars):
        return aggregated_bars
    return bars


def _aggregate_minute_bars(bars: list[dict[str, Any]], interval_minutes: int) -> list[dict[str, Any]]:
    valid_bars = []
    for bar in bars:
        parsed = _parse_timestamp(bar.get("datetime"))
        open_price = _to_float(bar.get("open"))
        high_price = _to_float(bar.get("high"))
        low_price = _to_float(bar.get("low"))
        close_price = _to_float(bar.get("close"))
        if parsed is None or None in {open_price, high_price, low_price, close_price}:
            continue
        valid_bars.append((parsed, bar))

    interval_seconds = interval_minutes * 60
    grouped: dict[int, list[tuple[datetime, dict[str, Any]]]] = {}
    for parsed, bar in sorted(valid_bars, key=lambda item: item[0]):
        bucket_start = int(parsed.timestamp() // interval_seconds) * interval_seconds
        grouped.setdefault(bucket_start, []).append((parsed, bar))

    aggregated: list[dict[str, Any]] = []
    for bucket_start, group in sorted(grouped.items()):
        group_bars = [bar for _, bar in group]
        volumes = [_to_float(bar.get("volume")) for bar in group_bars]
        aggregated.append(
            {
                "timestamp": datetime.fromtimestamp(bucket_start, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "datetime": datetime.fromtimestamp(bucket_start, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "open": _to_float(group_bars[0].get("open")),
                "high": max(_to_float(bar.get("high")) for bar in group_bars if _to_float(bar.get("high")) is not None),
                "low": min(_to_float(bar.get("low")) for bar in group_bars if _to_float(bar.get("low")) is not None),
                "close": _to_float(group_bars[-1].get("close")),
                "volume": sum(volume for volume in volumes if volume is not None) if all(volume is not None for volume in volumes) else None,
            }
        )
    return aggregated


def build_timeframe_trend(
    timeframe: str,
    bars: list[dict[str, Any]],
    data_source: str,
    provider_status: str,
) -> dict[str, Any]:
    closes = [_to_float(bar.get("close")) for bar in bars]
    valid_closes = [close for close in closes if close is not None]
    last_bar_time = _format_utc(_latest_bar_timestamp(bars)) if _latest_bar_timestamp(bars) else ""
    is_stale, stale_reason = _evaluate_timeframe_staleness(timeframe, bars, data_source, provider_status, last_bar_time)
    price = valid_closes[-1] if valid_closes else None
    ema9 = calculate_ema(valid_closes, 9)
    ema21 = calculate_ema(valid_closes, 21)
    ema50 = calculate_ema(valid_closes, 50)
    stack_status = classify_ema_stack(ema9, ema21, ema50)
    trend = classify_timeframe_trend(price, ema9, ema21, ema50)

    return {
        "timeframe": timeframe,
        "price": _round_or_none(price),
        "ema9": _round_or_none(ema9),
        "ema21": _round_or_none(ema21),
        "ema50": _round_or_none(ema50),
        "ema_stack_status": stack_status,
        "trend": trend,
        "price_vs_ema9": _level_relationship(price, ema9),
        "price_vs_ema21": _level_relationship(price, ema21),
        "price_vs_ema50": _level_relationship(price, ema50),
        "last_bar_time": last_bar_time,
        "is_stale": is_stale,
        "stale_reason": stale_reason,
    }


def classify_ema_stack(ema9: float | None, ema21: float | None, ema50: float | None) -> str:
    if ema9 is None or ema21 is None or ema50 is None:
        return "mixed_stack"
    if ema9 > ema21 > ema50:
        return "bullish_stack"
    if ema9 < ema21 < ema50:
        return "bearish_stack"
    return "mixed_stack"


def classify_timeframe_trend(
    price: float | None,
    ema9: float | None,
    ema21: float | None,
    ema50: float | None,
) -> str:
    stack_status = classify_ema_stack(ema9, ema21, ema50)
    if price is None or ema9 is None:
        return "mixed"
    if stack_status == "bullish_stack":
        return "strong_bullish" if price > ema9 else "bullish"
    if stack_status == "bearish_stack":
        return "strong_bearish" if price < ema9 else "bearish"
    return "mixed"


def _build_market_data(
    symbol: str,
    quote: dict[str, Any],
    bars: list[dict[str, Any]],
    data_source: str,
    provider_status: str,
) -> dict[str, Any]:
    closes = [float(bar["close"]) for bar in bars if _to_float(bar.get("close")) is not None]
    price = _to_float(quote.get("price"))
    if price is None and closes:
        price = closes[-1]

    ema9 = calculate_ema(closes, 9)
    ema20 = calculate_ema(closes, 20)
    rsi = calculate_rsi(closes, 14)
    vwap = calculate_vwap(bars) if bars else None
    trend = classify_trend(price, vwap, ema9, ema20)
    last_update_time = _resolve_last_update_time(quote, bars)
    data_mode = _data_mode_for_source(data_source)
    is_stale, stale_reason = _evaluate_freshness(data_source, price, bars, last_update_time)
    rounded_market_data = {
        "symbol": symbol.upper(),
        "price": _round_or_none(price),
        "session_high": _round_or_none(max(_to_float(bar.get("high")) for bar in bars if _to_float(bar.get("high")) is not None) if any(_to_float(bar.get("high")) is not None for bar in bars) else None),
        "session_low": _round_or_none(min(_to_float(bar.get("low")) for bar in bars if _to_float(bar.get("low")) is not None) if any(_to_float(bar.get("low")) is not None for bar in bars) else None),
        "vwap": _round_or_none(vwap),
        "ema9": _round_or_none(ema9),
        "ema20": _round_or_none(ema20),
        "rsi": _round_or_none(rsi),
        "trend": trend,
        "data_source": data_source,
        "data_mode": data_mode,
        "provider_status": provider_status,
        "timestamp": last_update_time,
        "last_update_time": last_update_time,
        "is_stale": is_stale,
        "stale_reason": stale_reason,
    }
    data_gate_status, data_gate_reason = _evaluate_data_gate(rounded_market_data)
    rounded_market_data["data_gate_status"] = data_gate_status
    rounded_market_data["data_gate_reason"] = data_gate_reason

    return rounded_market_data


def _data_mode_for_source(data_source: str) -> str:
    if data_source == "schwab":
        return "near_real_time"
    if data_source == "mock":
        return "mock"
    return "unavailable"


def build_instrument_payload(symbol: str) -> dict[str, Any]:
    metadata = get_instrument_metadata(symbol)
    if metadata is None:
        return {
            "symbol": symbol.strip().upper().removeprefix("/"),
            "display_symbol": symbol.strip().upper(),
            "provider_symbol": symbol.strip().upper(),
            "asset_class": "unknown",
            "exchange": "unknown",
            "session_type": "unknown",
            "tick_size": None,
            "tick_value": None,
            "point_value": None,
            "position_unit": "unknown",
            "decisions_enabled": False,
        }
    return {
        "symbol": metadata.symbol,
        "display_symbol": metadata.display_symbol,
        "provider_symbol": metadata.provider_symbol,
        "asset_class": metadata.asset_class,
        "exchange": metadata.exchange,
        "session_type": metadata.session_type,
        "tick_size": metadata.tick_size,
        "tick_value": metadata.tick_value,
        "point_value": metadata.point_value,
        "position_unit": metadata.position_unit,
        "decisions_enabled": metadata.decisions_enabled,
    }


def build_data_diagnostics(
    symbol: str,
    quote: dict[str, Any],
    bars: list[dict[str, Any]],
    market_data: dict[str, Any],
    multi_timeframe_trend: dict[str, Any],
    data_source: str,
    provider_status: str,
    market_session: dict[str, Any],
) -> dict[str, Any]:
    latest_bar_time = _latest_bar_timestamp(bars)
    return {
        "quote": {
            "status": "available" if _has_quote(quote) else "unavailable",
            "source": quote.get("data_source") or data_source,
            "requested_symbol": symbol.upper(),
            "resolved_symbol": quote.get("active_contract") or quote.get("symbol") or symbol.upper(),
            "timestamp": quote.get("timestamp") or "",
        },
        "bars": {
            "status": _bar_status(bars, market_data),
            "source": data_source,
            "requested_symbol": symbol.upper(),
            "requested_timeframe": "1m",
            "bars_returned": len(bars),
            "latest_bar_time": _format_utc(latest_bar_time) if latest_bar_time else "",
            "missing_fields": _missing_bar_fields(bars),
            "reason": _bar_diagnostic_reason(bars, market_data, market_session),
        },
        "multi_timeframe": {
            timeframe: {
                "bars_status": "stale" if row.get("is_stale") else "available",
                "latest_bar_time": row.get("last_bar_time") or "",
                "reason": row.get("stale_reason") or "",
            }
            for timeframe, row in (multi_timeframe_trend.get("timeframes") or {}).items()
        },
        "provider_status": provider_status,
        "data_gate_status": market_data.get("data_gate_status", DATA_GATE_CLOSED),
        "data_gate_reason": market_data.get("data_gate_reason", ""),
        "market_session_status": market_session.get("status", "unknown"),
    }


def _normalize_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_bars: list[dict[str, Any]] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        timestamp = bar.get("timestamp", bar.get("datetime", bar.get("time")))
        normalized_bars.append(
            {
                "timestamp": timestamp,
                "datetime": timestamp,
                "open": _to_float(bar.get("open")),
                "high": _to_float(bar.get("high")),
                "low": _to_float(bar.get("low")),
                "close": _to_float(bar.get("close")),
                "volume": _to_float(bar.get("volume")),
            }
        )
    return normalized_bars


def _bar_status(bars: list[dict[str, Any]], market_data: dict[str, Any]) -> str:
    if not bars:
        return "unavailable"
    if bool(market_data.get("is_stale", False)):
        return "stale"
    if _missing_bar_fields(bars):
        return "degraded"
    return "connected"


def _missing_bar_fields(bars: list[dict[str, Any]]) -> list[str]:
    if not bars:
        return []
    required_fields = ("timestamp", "open", "high", "low", "close", "volume")
    missing: set[str] = set()
    for bar in bars:
        for field in required_fields:
            if bar.get(field) in (None, "", "unavailable"):
                missing.add(field)
    return sorted(missing)


def _bar_diagnostic_reason(
    bars: list[dict[str, Any]],
    market_data: dict[str, Any],
    market_session: dict[str, Any],
) -> str:
    if market_session.get("status") in {"closed", "maintenance"}:
        return str(market_session.get("data_gate_reason") or "market closed")
    if not bars:
        return "provider returned empty candles"
    missing = _missing_bar_fields(bars)
    if "volume" in missing:
        return "bars missing volume"
    if len(bars) < 20:
        return "not enough bars for EMA20"
    if bool(market_data.get("is_stale", False)):
        return str(market_data.get("stale_reason") or "market data stale")
    if missing:
        return f"bars missing fields: {', '.join(missing)}"
    return ""


def build_market_session(now: datetime | None = None) -> dict[str, Any]:
    current_et = _to_eastern(now or datetime.now(timezone.utc))
    weekday = current_et.weekday()
    minutes = (current_et.hour * 60) + current_et.minute

    status = "open"
    reason = "regular_session"
    next_open = None
    message = "Market Open — Futures session appears open."
    data_gate_reason = ""

    if weekday == 5:
        status = "closed"
        reason = "weekend"
        next_open = _next_sunday_open(current_et)
        message = "Market Closed — Futures reopen Sunday 6:00 PM ET. Showing last available quote only. Bar-based indicators and trade recommendations are disabled."
        data_gate_reason = "market closed"
    elif weekday == 6 and minutes < (18 * 60):
        status = "closed"
        reason = "weekend"
        next_open = current_et.replace(hour=18, minute=0, second=0, microsecond=0)
        message = "Market Closed — Futures reopen today at 6:00 PM ET. Showing last available quote only. Bar-based indicators and trade recommendations are disabled."
        data_gate_reason = "market closed"
    elif weekday == 4 and minutes >= (17 * 60):
        status = "closed"
        reason = "weekend"
        next_open = _next_sunday_open(current_et)
        message = "Market Closed — Futures reopen Sunday 6:00 PM ET. Showing last available quote only. Bar-based indicators and trade recommendations are disabled."
        data_gate_reason = "market closed"
    elif weekday in {0, 1, 2, 3} and (17 * 60) <= minutes < (18 * 60):
        status = "maintenance"
        reason = "daily_maintenance"
        next_open = current_et.replace(hour=18, minute=0, second=0, microsecond=0)
        message = "Market Paused — Futures typically resume at 6:00 PM ET. Showing last available quote only. Bar-based indicators and trade recommendations are disabled."
        data_gate_reason = "market maintenance"

    return {
        "status": status,
        "reason": reason,
        "current_time_et": _format_et(current_et),
        "current_time_iso": current_et.isoformat(),
        "next_open_time_et": _format_et(next_open) if next_open else "",
        "message": message,
        "data_gate_reason": data_gate_reason,
        "holiday_note": "Holiday schedules can differ. If data does not update during normal hours, the market may be closed. Wait until the next market open.",
    }


def _to_eastern(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(EASTERN_TZ)


def _next_sunday_open(current_et: datetime) -> datetime:
    days_until_sunday = (6 - current_et.weekday()) % 7
    if days_until_sunday == 0 and (current_et.hour, current_et.minute) >= (18, 0):
        days_until_sunday = 7
    return current_et.replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)


def _format_et(value: datetime) -> str:
    eastern = value.astimezone(EASTERN_TZ)
    hour = eastern.hour % 12 or 12
    return f"{eastern.strftime('%b')} {eastern.day}, {eastern.year}, {hour}:{eastern.minute:02d} {eastern.strftime('%p %Z')}"


def _resolve_last_update_time(quote: dict[str, Any], bars: list[dict[str, Any]]) -> str:
    quote_timestamp = _parse_timestamp(quote.get("timestamp"))
    if quote_timestamp is not None:
        return _format_utc(quote_timestamp)
    bar_timestamp = _latest_bar_timestamp(bars)
    if bar_timestamp is not None:
        return _format_utc(bar_timestamp)
    return _utc_now()


def _latest_bar_timestamp(bars: list[dict[str, Any]]) -> datetime | None:
    timestamps = [_parse_timestamp(bar.get("datetime")) for bar in bars]
    valid = [timestamp for timestamp in timestamps if timestamp is not None]
    if not valid:
        return None
    return max(valid)


def _evaluate_freshness(
    data_source: str,
    price: float | None,
    bars: list[dict[str, Any]],
    last_update_time: str,
) -> tuple[bool, str]:
    if data_source == "unavailable" or price is None:
        return True, "market data unavailable"
    if len(bars) < 20:
        return True, "market data bars unavailable"
    if data_source == "mock":
        return False, ""
    parsed = _parse_timestamp(last_update_time)
    if parsed is None:
        return True, "market data timestamp unavailable"
    age_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    if age_seconds > STALE_MARKET_DATA_SECONDS:
        return True, "market data stale"
    return False, ""


def _evaluate_data_gate(market_data: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(market_data, dict) or not market_data:
        return DATA_GATE_CLOSED, "market data unavailable"

    provider_status = str(market_data.get("provider_status") or "").lower()
    data_source = str(market_data.get("data_source") or "").lower()
    data_mode = str(market_data.get("data_mode") or "").lower()

    if provider_status == "unavailable":
        return DATA_GATE_CLOSED, "market data unavailable"
    if data_source in {"", "unavailable"}:
        return DATA_GATE_CLOSED, "market data unavailable"
    if data_mode not in {"live", "near_real_time"}:
        return DATA_GATE_CLOSED, "market data unavailable"
    if bool(market_data.get("is_stale", False)):
        return DATA_GATE_CLOSED, str(market_data.get("stale_reason") or "market data stale")

    missing = [field for field in REQUIRED_MARKET_DATA_FIELDS if market_data.get(field) in (None, "", "unavailable")]
    if missing:
        return DATA_GATE_CLOSED, "required market data missing"

    return DATA_GATE_OPEN, ""


def _evaluate_timeframe_staleness(
    timeframe: str,
    bars: list[dict[str, Any]],
    data_source: str,
    provider_status: str,
    last_bar_time: str,
) -> tuple[bool, str]:
    if provider_status == "unavailable" or data_source == "unavailable":
        return True, "timeframe data unavailable"
    if len(bars) < MTF_REQUIRED_BARS:
        return True, "not enough bars for EMA 50"
    if not last_bar_time:
        return True, "last bar time unavailable"
    if data_source == "mock":
        return False, ""
    parsed = _parse_timestamp(last_bar_time)
    if parsed is None:
        return True, "last bar time unavailable"
    threshold_seconds = (_timeframe_minutes(timeframe) * 60 * 2) + STALE_MARKET_DATA_SECONDS
    if (datetime.now(timezone.utc) - parsed).total_seconds() > threshold_seconds:
        return True, "timeframe data stale"
    return False, ""


def _level_relationship(price: float | None, level: float | None) -> str:
    if price is None or level is None:
        return "unavailable"
    if price > level:
        return "above"
    if price < level:
        return "below"
    return "equal"


def _alignment_summary(dominant_trend: str, bullish_count: int, bearish_count: int, any_stale: bool) -> str:
    if any_stale:
        return "Multi-timeframe data is stale or incomplete; use the trend panel for context only."
    if dominant_trend == "bullish":
        return f"Multi-timeframe trend is bullish across {bullish_count} of 5 timeframes."
    if dominant_trend == "bearish":
        return f"Multi-timeframe trend is bearish across {bearish_count} of 5 timeframes."
    return "Multi-timeframe trend is mixed; higher and lower timeframes are not aligned."


def _multi_timeframe_summary_sentence(multi_timeframe_trend: dict[str, Any]) -> str:
    if not multi_timeframe_trend:
        return "Multi-timeframe trend is unavailable."
    if multi_timeframe_trend.get("data_gate_status") == DATA_GATE_CLOSED:
        return "Multi-timeframe data is stale; use trend panel for context only."
    return str(multi_timeframe_trend.get("alignment_summary") or "Multi-timeframe trend is unavailable.")


def _price_relationship(level_name: str, price: float | None, level: float | None) -> str:
    if price is None or level is None:
        return f"Price relationship to {level_name} is unavailable."
    if price > level:
        return f"Price is above {level_name}."
    if price < level:
        return f"Price is below {level_name}."
    return f"Price is at {level_name}."


def _moving_average_alignment(ema9: float | None, ema20: float | None) -> str:
    if ema9 is None or ema20 is None:
        return "EMA 9 and EMA 20 alignment is unavailable."
    if abs(ema9 - ema20) <= 0.01:
        return "EMA 9 and EMA 20 are nearly flat/neutral."
    if ema9 > ema20:
        return "EMA 9 is above EMA 20, short-term momentum is above the slower average."
    return "EMA 9 is below EMA 20, short-term momentum is below the slower average."


def _rsi_comment(rsi: float | None) -> str:
    if rsi is None:
        return "RSI is unavailable."
    if rsi >= 70.0:
        return "RSI is overbought."
    if rsi >= 55.0:
        return "RSI is bullish/positive."
    if rsi > 45.0:
        return "RSI is neutral."
    if rsi > 30.0:
        return "RSI is bearish/weak."
    return "RSI is oversold."


def _trend_comment(
    price: float | None,
    vwap: float | None,
    ema9: float | None,
    ema20: float | None,
) -> str:
    if price is None or vwap is None or ema9 is None or ema20 is None:
        return "Alignment is neutral because market data is incomplete."
    if price > vwap and price > ema9 and price > ema20 and ema9 > ema20:
        return "Alignment is bullish because price is above VWAP, EMA 9, and EMA 20 while EMA 9 is above EMA 20."
    if price < vwap and price < ema9 and price < ema20 and ema9 < ema20:
        return "Alignment is bearish because price is below VWAP, EMA 9, and EMA 20 while EMA 9 is below EMA 20."
    return "Alignment is mixed because price and moving averages are not fully aligned."


def _decision_comment(decision: dict[str, Any]) -> str:
    risk_status = str(decision.get("risk_status", "")).lower()
    recommendation = str(decision.get("recommendation", "NO TRADE")).upper()
    if risk_status == "blocked":
        return "Risk rules are blocking new recommendations."
    if recommendation == "LONG":
        return "Technical criteria are aligned bullish and risk is allowed."
    if recommendation == "SHORT":
        return "Technical criteria are aligned bearish and risk is allowed."
    return "Decision remains NO TRADE because technical criteria are not fully aligned."


def _build_display_context(context: dict[str, Any] | None) -> dict[str, Any]:
    raw = context or {}
    news = _normalize_context_items(raw.get("news") or raw.get("top_headlines") or [], default_source="news")
    social = _normalize_context_items(
        raw.get("social") or raw.get("trump_posts_recent") or [],
        default_source="Truth Social",
    )
    combined_room = max(0, 5 - len(news[:5]))
    return {
        "news": news[:5],
        "social": social[:combined_room],
        "context_rule": DISPLAY_CONTEXT_RULE,
    }


def _normalize_context_items(items: list[Any], default_source: str) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("text") or "")
            source = str(item.get("source") or default_source)
            url = str(item.get("url") or "")
        else:
            raw = str(item)
            title, _, url_part = raw.partition(" -- ")
            source = default_source
            url = url_part.strip()
        if not title:
            continue
        normalized.append({"title": title, "source": source, "url": url})
    return normalized


def _evaluate_risk(payload: dict[str, Any]) -> tuple[str, str]:
    settings = {**DEFAULT_RISK_SETTINGS, **payload.get("risk_settings", {})}
    state = payload.get("risk_state", {})
    if bool(state.get("locked_out", False)):
        return "blocked", "risk rule violated"
    if float(state.get("daily_loss", 0.0)) >= float(settings["max_daily_loss"]):
        return "blocked", "risk rule violated"
    if float(state.get("estimated_risk", 0.0)) > float(settings["max_risk_per_trade"]):
        return "blocked", "risk rule violated"
    if int(state.get("trades_today", 0)) >= int(settings["max_trades_per_day"]):
        return "blocked", "risk rule violated"
    if int(state.get("consecutive_losses", 0)) >= int(settings["max_consecutive_losses"]):
        return "blocked", "risk rule violated"
    return "allowed", ""


def _format_risk_settings(settings: dict[str, float | int]) -> dict[str, float | int]:
    formatted: dict[str, float | int] = {}
    int_keys = {"max_trades_per_day", "max_consecutive_losses"}
    for key, value in settings.items():
        if key in int_keys:
            formatted[key] = int(value)
        else:
            formatted[key] = round(float(value), 2)
    return formatted


def _has_valid_market_data(quote: dict[str, Any], bars: list[dict[str, Any]]) -> bool:
    return _has_quote(quote) and len(bars) >= 20


def _has_quote(quote: dict[str, Any]) -> bool:
    return _to_float(quote.get("price")) is not None


def _provider_status_for_market_data(quote: dict[str, Any], bars: list[dict[str, Any]]) -> str:
    if _has_valid_market_data(quote, bars):
        return "connected"
    if _has_quote(quote):
        return "degraded"
    return "unavailable"


def _parse_timeframe(timeframe: str) -> tuple[str, int]:
    normalized = timeframe.strip().lower()
    if normalized.endswith("m"):
        return "minute", int(normalized[:-1])
    if normalized in {"daily", "1d", "d"}:
        return "daily", 1
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _timeframe_minutes(timeframe: str) -> int:
    frequency_type, frequency = _parse_timeframe(timeframe)
    if frequency_type != "minute":
        return 1440
    return frequency


def _to_float(value: Any) -> float | None:
    if value in (None, "", "unavailable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        timestamp_value = float(value)
        if timestamp_value > 1_000_000_000_000:
            timestamp_value /= 1000.0
        parsed = datetime.fromtimestamp(timestamp_value, tz=timezone.utc)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.isdigit():
            return _parse_timestamp(float(normalized))
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
