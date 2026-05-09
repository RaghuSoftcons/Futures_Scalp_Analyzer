"""Pure recommendation logic."""

from __future__ import annotations


def _to_float(value: object) -> float | None:
    if value in (None, "", "unavailable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


FINAL_RECOMMENDATION_COMMENTS: dict[str, str] = {
    "take": "Setup is within prop rules with supportive pricing, liquidity, and reward-to-risk.",
    "take only on pullback": "Setup quality is acceptable, but current pricing looks chasey and a pullback is preferred.",
    "scalp only": "Edge is thin enough that only a short-duration scalp is justified.",
    "flatten": "Current position profile is no longer favorable for intraday prop rules and should be exited.",
    "pass": "Hard risk rules or poor trade quality block this setup.",
    "unavailable": "Required live pricing or evaluation inputs are unavailable or inconsistent.",
}

ORDERED_RECOMMENDATIONS = ["pass", "scalp only", "take only on pullback", "take"]


def _downgrade(recommendation: str, levels: int = 1) -> str:
    if recommendation not in ORDERED_RECOMMENDATIONS:
        return recommendation
    idx = ORDERED_RECOMMENDATIONS.index(recommendation)
    return ORDERED_RECOMMENDATIONS[max(0, idx - levels)]


def _pullback_bounds(ctx: dict) -> tuple[float, float]:
    live_atr = max(_to_float(ctx.get("live_atr")) or 0.0, 1.0)
    minimum = max(1.0, live_atr * 0.05)
    maximum = max(minimum * 2.0, live_atr * 0.2)
    return minimum, maximum


def detect_pullback(ctx: dict) -> bool:
    side = ctx.get("side")
    live_price = _to_float(ctx.get("live_price"))
    session_low = _to_float(ctx.get("session_low"))
    session_high = _to_float(ctx.get("session_high"))
    if live_price is None:
        return False

    minimum, maximum = _pullback_bounds(ctx)
    if side == "short" and session_low is not None:
        bounce_points = live_price - session_low
        return minimum <= bounce_points <= maximum
    if side == "long" and session_high is not None:
        bounce_points = session_high - live_price
        return minimum <= bounce_points <= maximum
    return False


def detect_extension(ctx: dict) -> bool:
    side = ctx.get("side")
    live_price = _to_float(ctx.get("live_price"))
    session_low = _to_float(ctx.get("session_low"))
    session_high = _to_float(ctx.get("session_high"))
    if live_price is None:
        return False

    threshold = max(1.0, _pullback_bounds(ctx)[0] * 0.8)
    if side == "short" and session_low is not None:
        return live_price - session_low <= threshold
    if side == "long" and session_high is not None:
        return session_high - live_price <= threshold
    return False


def _rejection_or_stall(ctx: dict) -> bool:
    live_price = _to_float(ctx.get("live_price"))
    ema9 = _to_float(ctx.get("ema9"))
    rsi = _to_float(ctx.get("rsi"))
    volume_condition = ctx.get("volume_condition")
    if live_price is None:
        return False
    if ema9 is not None and live_price <= ema9:
        return True
    if volume_condition in {"normal_volume", "low_volume"}:
        return True
    return rsi is not None and rsi <= 55.0


def _strong_upward_impulse(ctx: dict) -> bool:
    live_price = _to_float(ctx.get("live_price"))
    ema9 = _to_float(ctx.get("ema9"))
    session_low = _to_float(ctx.get("session_low"))
    volume_condition = ctx.get("volume_condition")
    if live_price is None:
        return False

    minimum_pullback, _ = _pullback_bounds(ctx)
    bounce_from_low = (live_price - session_low) if session_low is not None else 0.0
    if volume_condition == "high_volume" and bounce_from_low >= minimum_pullback:
        return True
    return ema9 is not None and live_price >= ema9 and bounce_from_low >= minimum_pullback


def _upward_continuation(ctx: dict) -> bool:
    live_price = _to_float(ctx.get("live_price"))
    ema9 = _to_float(ctx.get("ema9"))
    rsi = _to_float(ctx.get("rsi"))
    volume_condition = ctx.get("volume_condition")
    if live_price is None:
        return False
    if ema9 is not None and live_price >= ema9:
        return True
    if volume_condition == "high_volume":
        return True
    return rsi is not None and rsi >= 50.0


def _near_session_low(ctx: dict) -> bool:
    live_price = _to_float(ctx.get("live_price"))
    session_low = _to_float(ctx.get("session_low"))
    if live_price is None or session_low is None:
        return False
    _, maximum_pullback = _pullback_bounds(ctx)
    return (live_price - session_low) <= maximum_pullback


def compute_scalper_decision(ctx: dict) -> dict[str, str]:
    side = ctx.get("side")
    live_price = _to_float(ctx.get("live_price"))
    vwap = _to_float(ctx.get("vwap"))
    rsi = _to_float(ctx.get("rsi"))
    trend = ctx.get("trend")
    market_data_available = bool(ctx.get("market_data_available", False))
    pullback_detected = detect_pullback(ctx)
    extension_detected = detect_extension(ctx) and not pullback_detected

    default_decision = {
        "final_recommendation": "NO TRADE",
        "reason": "Market context is incomplete for scalper execution timing.",
        "entry_quality": "POOR",
        "setup_type": "EXTENSION" if extension_detected else "PULLBACK",
    }
    if not market_data_available or live_price is None:
        return default_decision

    if side == "short":
        if extension_detected:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Price is pressing lows in extension with no pullback; avoid shorting the straight-line move.",
                "entry_quality": "POOR",
                "setup_type": "EXTENSION",
            }
        if vwap is None or live_price >= vwap:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Short scalp needs price below VWAP before execution timing is acceptable.",
                "entry_quality": "AVERAGE",
                "setup_type": "PULLBACK",
            }
        if trend != "downtrend":
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Short scalp requires an active downtrend; current trend is not aligned.",
                "entry_quality": "AVERAGE",
                "setup_type": "PULLBACK",
            }
        if rsi is not None and rsi < 30.0 and not pullback_detected:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "RSI is already washed out and there has been no bounce, so the move is too extended to short.",
                "entry_quality": "POOR",
                "setup_type": "EXTENSION",
            }
        if not pullback_detected:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Downtrend is intact, but there is no  pullback to lean against yet.",
                "entry_quality": "POOR",
                "setup_type": "EXTENSION",
            }
        if not _rejection_or_stall(ctx):
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Bounce occurred, but rejection or stall after the pullback is still missing.",
                "entry_quality": "AVERAGE",
                "setup_type": "PULLBACK",
            }
        return {
            "final_recommendation": "SHORT",
            "reason": "Price is below VWAP in a downtrend, and the bounce has stalled after a tradable pullback.",
            "entry_quality": "GOOD",
            "setup_type": "PULLBACK",
        }

    if side == "long":
        if extension_detected:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Price is extending without a pullback, so this is too late for a disciplined long scalp entry.",
                "entry_quality": "POOR",
                "setup_type": "EXTENSION",
            }

        if vwap is not None and live_price > vwap and trend == "uptrend":
            if not pullback_detected:
                return {
                    "final_recommendation": "NO TRADE",
                    "reason": "Trend-following long is valid only after a pullback; chasing the move at extension is low quality.",
                    "entry_quality": "POOR",
                    "setup_type": "EXTENSION",
                }
            if not _upward_continuation(ctx):
                return {
                    "final_recommendation": "NO TRADE",
                    "reason": "Pullback happened, but continuation back up has not resumed yet.",
                    "entry_quality": "AVERAGE",
                    "setup_type": "PULLBACK",
                }
            return {
                "final_recommendation": "LONG",
                "reason": "Price is above VWAP in an uptrend, and the pullback is resolving with continuation for a trend long scalp.",
                "entry_quality": "GOOD",
                "setup_type": "PULLBACK",
            }

        strong_impulse = _strong_upward_impulse(ctx)
        if rsi is None or rsi > 30.0:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Counter-trend long scalp needs an oversold RSI condition before considering reversal timing.",
                "entry_quality": "POOR",
                "setup_type": "REVERSAL",
            }
        if not _near_session_low(ctx):
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Long scalp requires price to be working near the session low for a clean reversal location.",
                "entry_quality": "AVERAGE",
                "setup_type": "REVERSAL",
            }
        if not strong_impulse:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Bounce is weak and lacks the upward impulse needed for a reversal scalp.",
                "entry_quality": "POOR",
                "setup_type": "REVERSAL",
            }
        if ctx.get("vwap_position") == "below_vwap" and not strong_impulse:
            return {
                "final_recommendation": "NO TRADE",
                "reason": "Long scalp is still below VWAP without a reversal impulse.",
                "entry_quality": "POOR",
                "setup_type": "REVERSAL",
            }
        return {
            "final_recommendation": "LONG",
            "reason": "RSI is oversold near the session low and a strong upward impulse is in place for a reversal scalp.",
            "entry_quality": "AVERAGE" if ctx.get("vwap_position") == "below_vwap" else "GOOD",
            "setup_type": "REVERSAL",
        }

    return default_decision


def _base_recommendation(ctx: dict) -> str:
    live_price = ctx.get("live_price")
    entry_verdict = ctx.get("entry_verdict")
    trade_verdict = ctx.get("trade_verdict")
    violations = ctx.get("risk_rule_violations", {})
    pricing_diff = abs(float(ctx.get("pricing_percentage_difference", 0.0)))
    liquidity_score = ctx.get("liquidity_score")
    rr_ratio = float(ctx.get("rr_ratio", 0.0))
    mode = ctx.get("mode")

    if live_price is None or entry_verdict == "unavailable" or trade_verdict == "unavailable":
        return "unavailable"
    if (
        violations.get("per_trade_risk_exceeds_limit")
        or violations.get("max_loss_trades_reached")
        or violations.get("daily_profit_target_reached")
        or trade_verdict == "avoid"
        or (pricing_diff >= 25 and entry_verdict == "rich")
    ):
        return "pass"
    if mode == "position_mgmt" and (
        ctx.get("risk_reward_asymmetric")
        or violations.get("max_loss_trades_reached")
        or violations.get("daily_profit_target_reached")
    ):
        return "flatten"
    if (
        trade_verdict == "speculative"
        or (ctx.get("is_far_from_key_levels") and liquidity_score == "weak")
        or rr_ratio < 1.5
    ):
        return "scalp only"
    if (
        trade_verdict == "favorable"
        and entry_verdict == "rich"
        and 5 <= pricing_diff < 25
        and liquidity_score in {"good", "acceptable"}
    ):
        return "take only on pullback"
    if (
        trade_verdict == "favorable"
        and entry_verdict in {"attractive", "fair"}
        and liquidity_score in {"good", "acceptable"}
        and rr_ratio >= 1.5
        and not any(violations.values())
    ):
        return "take"
    if trade_verdict in {"favorable", "neutral", "speculative"}:
        return "scalp only"
    return "pass"


def compute_final_recommendation(ctx: dict) -> str:
    """Return a final recommendation and comment informed by market context."""
    existing = ctx.get("final_recommendation")
    if existing:
        if not ctx.get("final_recommendation_comment"):
            ctx["final_recommendation_comment"] = FINAL_RECOMMENDATION_COMMENTS.get(existing, "")
        return existing

    if ctx.get("market_data_available") is False:
        recommendation = "unavailable"
        ctx["final_recommendation"] = recommendation
        ctx["final_recommendation_comment"] = (
            "Live market context is unavailable or stale, so the setup should be treated as wait-only until fresh session data is available."
        )
        return recommendation

    recommendation = _base_recommendation(ctx)
    reasons: list[str] = []

    if recommendation in {"pass", "flatten", "unavailable"}:
        base_comment = FINAL_RECOMMENDATION_COMMENTS.get(recommendation, "")
        ctx["final_recommendation"] = recommendation
        ctx["final_recommendation_comment"] = base_comment
        return recommendation

    if bool(ctx.get("market_data_available", False)):
        scalper_decision = compute_scalper_decision(ctx)
        ctx["scalper_decision"] = scalper_decision
        reasons.append(scalper_decision["reason"])

        if scalper_decision["final_recommendation"] == "NO TRADE":
            recommendation = "pass"
        elif scalper_decision["final_recommendation"] == "SHORT":
            recommendation = "take" if scalper_decision["entry_quality"] == "GOOD" else "scalp only"
        elif scalper_decision["final_recommendation"] == "LONG":
            recommendation = "scalp only" if ctx.get("vwap_position") == "below_vwap" else "take"

        if ctx.get("volume_condition") == "low_volume" and recommendation == "take":
            recommendation = "scalp only"
            reasons.append("Low volume keeps this in scalp-only mode.")

    base_comment = FINAL_RECOMMENDATION_COMMENTS.get(recommendation, "")
    ctx["final_recommendation"] = recommendation
    ctx["final_recommendation_comment"] = (
        f"{base_comment} Market analysis: {' '.join(reasons)}" if reasons else base_comment
    )
    return recommendation
