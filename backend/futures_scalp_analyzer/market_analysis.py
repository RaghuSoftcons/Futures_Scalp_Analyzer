"""Market context computations from bar data."""

from __future__ import annotations

from datetime import UTC, datetime


UNAVAILABLE_CONTEXT: dict[str, float | str | bool | None] = {
    "ema9": None,
    "ema20": None,
    "vwap": None,
    "rsi": None,
    "live_atr": None,
    "volume_ratio": None,
    "trend": "unavailable",
    "market_structure": "unavailable",
    "vwap_position": "unavailable",
    "rsi_condition": "unavailable",
    "volume_condition": "unavailable",
    "session_high": None,
    "session_low": None,
    "prior_day_high": None,
    "prior_day_low": None,
    "market_data_available": False,
}


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    seed = sum(values[:period]) / period
    multiplier = 2.0 / (period + 1)
    ema_value = seed
    for value in values[period:]:
        ema_value = (value - ema_value) * multiplier + ema_value
    return ema_value


def _wilder_rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) <= period:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _wilder_atr(bars_5m: list[dict], period: int = 14) -> float | None:
    if len(bars_5m) <= period:
        return None

    true_ranges: list[float] = []
    prev_close = float(bars_5m[0]["close"])
    for bar in bars_5m[1:]:
        high = float(bar["high"])
        low = float(bar["low"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
        prev_close = float(bar["close"])

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = ((atr * (period - 1)) + tr) / period
    return atr


def _market_structure(bars_15m: list[dict]) -> str:
    if len(bars_15m) < 3:
        return "neutral_structure"
    recent = bars_15m[-3:]
    highs = [float(bar["high"]) for bar in recent]
    lows = [float(bar["low"]) for bar in recent]
    if highs[2] > highs[1] > highs[0] and lows[2] > lows[1] > lows[0]:
        return "bullish_structure"
    if highs[2] < highs[1] < highs[0] and lows[2] < lows[1] < lows[0]:
        return "bearish_structure"
    return "neutral_structure"


def _session_filter_today(bars_1m: list[dict]) -> list[dict]:
    today = datetime.now(UTC).date()
    filtered: list[dict] = []
    for bar in bars_1m:
        raw_dt = bar.get("datetime")
        try:
            if isinstance(raw_dt, (int, float)):
                dt = datetime.fromtimestamp(float(raw_dt) / (1000.0 if float(raw_dt) > 1_000_000_000_000 else 1.0), tz=UTC)
            else:
                dt = datetime.fromisoformat(str(raw_dt).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                else:
                    dt = dt.astimezone(UTC)
        except Exception:
            continue
        if dt.date() == today:
            filtered.append(bar)
    return filtered or bars_1m


def compute_market_context(
    bars_1m: list,
    bars_5m: list,
    bars_15m: list,
    symbol: str,
    prior_day_high: float | None = None,
    prior_day_low: float | None = None,
) -> dict:
    del symbol
    if len(bars_1m) < 20 or len(bars_5m) < 20 or len(bars_15m) < 3:
        return dict(UNAVAILABLE_CONTEXT)

    closes_5m = [float(bar["close"]) for bar in bars_5m]
    ema9 = _ema(closes_5m, 9)
    ema20 = _ema(closes_5m, 20)
    rsi = _wilder_rsi(closes_5m, 14)
    live_atr = _wilder_atr(bars_5m, 14)

    today_bars_1m = _session_filter_today(bars_1m)
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for bar in today_bars_1m:
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        volume = float(bar.get("volume", 0.0))
        typical_price = (high + low + close) / 3.0
        cumulative_pv += typical_price * volume
        cumulative_volume += volume
    vwap = (cumulative_pv / cumulative_volume) if cumulative_volume else None

    latest_close = float(closes_5m[-1])
    latest_volume = float(bars_5m[-1].get("volume", 0.0))
    avg20_volume = sum(float(bar.get("volume", 0.0)) for bar in bars_5m[-20:]) / 20.0
    volume_ratio = (latest_volume / avg20_volume) if avg20_volume else None

    if ema9 is None or ema20 is None:
        trend = "unavailable"
    elif latest_close > ema9 > ema20:
        trend = "uptrend"
    elif latest_close < ema9 < ema20:
        trend = "downtrend"
    else:
        trend = "sideways"

    if vwap is None:
        vwap_position = "unavailable"
    elif abs(latest_close - vwap) / vwap <= 0.0005:
        vwap_position = "at_vwap"
    elif latest_close > vwap:
        vwap_position = "above_vwap"
    else:
        vwap_position = "below_vwap"

    if rsi is None:
        rsi_condition = "unavailable"
    elif rsi > 70:
        rsi_condition = "overbought"
    elif rsi < 30:
        rsi_condition = "oversold"
    else:
        rsi_condition = "neutral"

    if volume_ratio is None:
        volume_condition = "unavailable"
    elif volume_ratio > 1.5:
        volume_condition = "high_volume"
    elif volume_ratio < 0.7:
        volume_condition = "low_volume"
    else:
        volume_condition = "normal_volume"

    session_high = max(float(bar["high"]) for bar in today_bars_1m)
    session_low = min(float(bar["low"]) for bar in today_bars_1m)

    return {
        "ema9": ema9,
        "ema20": ema20,
        "vwap": vwap,
        "rsi": rsi,
        "live_atr": live_atr,
        "volume_ratio": volume_ratio,
        "trend": trend,
        "market_structure": _market_structure(bars_15m),
        "vwap_position": vwap_position,
        "rsi_condition": rsi_condition,
        "volume_condition": volume_condition,
        "session_high": session_high,
        "session_low": session_low,
        "prior_day_high": prior_day_high,
        "prior_day_low": prior_day_low,
        "market_data_available": True,
    }
