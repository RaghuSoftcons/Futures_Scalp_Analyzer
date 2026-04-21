"""Pure recommendation logic."""

from __future__ import annotations


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

    recommendation = _base_recommendation(ctx)
    reasons: list[str] = []
    side = ctx.get("side")
    market_data_available = bool(ctx.get("market_data_available", False))

    if not market_data_available:
        reasons.append("Market data unavailable; using baseline risk/reward logic.")
    else:
        trend = ctx.get("trend")
        if trend == "downtrend" and side == "long" and recommendation in ORDERED_RECOMMENDATIONS:
            recommendation = _downgrade(recommendation)
            reasons.append("Long setup opposes a detected downtrend.")
        if trend == "uptrend" and side == "short" and recommendation in ORDERED_RECOMMENDATIONS:
            recommendation = _downgrade(recommendation)
            reasons.append("Short setup opposes a detected uptrend.")

        rsi_condition = ctx.get("rsi_condition")
        if rsi_condition == "overbought" and side == "long" and recommendation in ORDERED_RECOMMENDATIONS:
            recommendation = _downgrade(recommendation, levels=2)
            if recommendation == "take":
                recommendation = "take only on pullback"
            reasons.append("RSI is overbought for a long entry; pullback preferred.")
        if rsi_condition == "oversold" and side == "short" and recommendation in ORDERED_RECOMMENDATIONS:
            recommendation = _downgrade(recommendation, levels=2)
            if recommendation == "take":
                recommendation = "take only on pullback"
            reasons.append("RSI is oversold for a short entry; pullback preferred.")

        if ctx.get("volume_condition") == "low_volume" and recommendation in ORDERED_RECOMMENDATIONS:
            if recommendation == "take":
                recommendation = "scalp only"
            if recommendation == "take only on pullback":
                recommendation = "scalp only"
            reasons.append("Low-volume environment reduces follow-through odds.")

        if ctx.get("vwap_position") == "below_vwap" and side == "long" and recommendation in ORDERED_RECOMMENDATIONS:
            if recommendation == "take":
                recommendation = "scalp only"
            reasons.append("Long setup below VWAP adds directional risk.")

        if ctx.get("market_structure") == "bearish_structure" and side == "long" and recommendation in ORDERED_RECOMMENDATIONS:
            recommendation = _downgrade(recommendation)
            reasons.append("15m market structure is bearish against the long idea.")

    base_comment = FINAL_RECOMMENDATION_COMMENTS.get(recommendation, "")
    ctx["final_recommendation"] = recommendation
    ctx["final_recommendation_comment"] = (
        f"{base_comment} Market analysis: {' '.join(reasons)}" if reasons else base_comment
    )
    return recommendation
