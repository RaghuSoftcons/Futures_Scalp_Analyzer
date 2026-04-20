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


def compute_final_recommendation(ctx: dict) -> str:
    """Return a final recommendation without overriding an upstream choice."""
    existing = ctx.get("final_recommendation")
    if existing:
        if not ctx.get("final_recommendation_comment"):
            ctx["final_recommendation_comment"] = FINAL_RECOMMENDATION_COMMENTS.get(existing, "")
        return existing

    live_price = ctx.get("live_price")
    entry_verdict = ctx.get("entry_verdict")
    trade_verdict = ctx.get("trade_verdict")
    violations = ctx.get("risk_rule_violations", {})
    pricing_diff = abs(float(ctx.get("pricing_percentage_difference", 0.0)))
    liquidity_score = ctx.get("liquidity_score")
    rr_ratio = float(ctx.get("rr_ratio", 0.0))
    mode = ctx.get("mode")

    if live_price is None or entry_verdict == "unavailable" or trade_verdict == "unavailable":
        recommendation = "unavailable"
    elif (
        violations.get("per_trade_risk_exceeds_limit")
        or violations.get("max_loss_trades_reached")
        or violations.get("daily_profit_target_reached")
        or trade_verdict == "avoid"
        or (pricing_diff >= 25 and entry_verdict == "rich")
    ):
        recommendation = "pass"
    elif mode == "position_mgmt" and (
        ctx.get("risk_reward_asymmetric")
        or violations.get("max_loss_trades_reached")
        or violations.get("daily_profit_target_reached")
    ):
        recommendation = "flatten"
    elif (
        trade_verdict == "speculative"
        or (ctx.get("is_far_from_key_levels") and liquidity_score == "weak")
        or rr_ratio < 1.5
    ):
        recommendation = "scalp only"
    elif (
        trade_verdict == "favorable"
        and entry_verdict == "rich"
        and 5 <= pricing_diff < 25
        and liquidity_score in {"good", "acceptable"}
    ):
        recommendation = "take only on pullback"
    elif (
        trade_verdict == "favorable"
        and entry_verdict in {"attractive", "fair"}
        and liquidity_score in {"good", "acceptable"}
        and rr_ratio >= 1.5
        and not any(violations.values())
    ):
        recommendation = "take"
    elif trade_verdict in {"favorable", "neutral", "speculative"}:
        recommendation = "scalp only"
    else:
        recommendation = "pass"

    ctx["final_recommendation"] = recommendation
    ctx["final_recommendation_comment"] = FINAL_RECOMMENDATION_COMMENTS[recommendation]
    return recommendation

