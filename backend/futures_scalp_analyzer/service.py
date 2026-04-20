"""Core analysis service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from .price_feed import PriceFeed
from .recommendations import compute_final_recommendation
from .risk import evaluate_session_status, get_account_risk_template
from .symbols import SUPPORTED_SYMBOLS, SymbolSpec


def _resolve_trade_levels(
    request: FuturesScalpIdeaRequest,
    spec: SymbolSpec,
    risk_template: dict[str, float | int],
    live_price: float | None,
) -> tuple[float, float, float]:
    entry_price = request.entry_price if request.entry_price is not None else (live_price or 0.0)
    per_contract_risk_dollars = float(risk_template["per_trade_risk"]) / max(request.contracts, 1)
    per_contract_target_dollars = float(risk_template["per_trade_target"]) / max(request.contracts, 1)
    stop_distance_points = per_contract_risk_dollars / spec.point_value
    target_distance_points = per_contract_target_dollars / spec.point_value

    if request.side == "long":
        stop_price = request.stop_price if request.stop_price is not None else entry_price - stop_distance_points
        target_price = request.target_price if request.target_price is not None else entry_price + target_distance_points
    else:
        stop_price = request.stop_price if request.stop_price is not None else entry_price + stop_distance_points
        target_price = request.target_price if request.target_price is not None else entry_price - target_distance_points

    return entry_price, stop_price, target_price


def _risk_points(entry_price: float, stop_price: float) -> float:
    return abs(entry_price - stop_price)


def _reward_points(entry_price: float, target_price: float) -> float:
    return abs(target_price - entry_price)


def _distance_entry_to_live(entry_price: float, live_price: float | None) -> float | None:
    if live_price is None:
        return None
    return entry_price - live_price


def _pricing_percentage_difference(entry_price: float, live_price: float | None) -> float:
    if live_price is None or live_price == 0:
        return 0.0
    return abs((entry_price - live_price) / live_price) * 100.0


def _entry_verdict(side: str, entry_price: float, live_price: float | None) -> str:
    if live_price is None:
        return "unavailable"
    pricing_diff = _pricing_percentage_difference(entry_price, live_price)
    is_attractive = (
        side == "long" and entry_price <= live_price
    ) or (
        side == "short" and entry_price >= live_price
    )
    if is_attractive and pricing_diff <= 0.1:
        return "attractive"
    if pricing_diff <= 0.5:
        return "fair"
    return "rich"


def _trade_verdict(rr_ratio: float, violations: dict[str, bool]) -> str:
    if rr_ratio <= 0:
        return "unavailable"
    if any(violations.values()):
        return "avoid"
    if rr_ratio >= 2.0:
        return "favorable"
    if rr_ratio >= 1.5:
        return "neutral"
    return "speculative"


def _risk_reward_asymmetric(side: str, stop_price: float, target_price: float, spec: SymbolSpec, live_price: float | None) -> bool:
    if live_price is None:
        return False
    if side == "long":
        risk_remaining_points = max(live_price - stop_price, 0.0)
        reward_remaining_points = max(target_price - live_price, 0.0)
    else:
        risk_remaining_points = max(stop_price - live_price, 0.0)
        reward_remaining_points = max(live_price - target_price, 0.0)

    risk_remaining = risk_remaining_points * spec.point_value
    reward_remaining = reward_remaining_points * spec.point_value
    return reward_remaining <= risk_remaining


def _is_far_from_key_levels(entry_price: float, spec: SymbolSpec, live_price: float | None) -> bool:
    if live_price is None:
        return False
    return abs(live_price - entry_price) >= 0.2 * spec.atr_reference


def _format_dollars(amount: float) -> str:
    return f"${amount:,.2f}"


def _format_price_level(price: float) -> str:
    return f"{price:,.2f}"


def _resolve_gpt_verdict(final_recommendation: str, session_status: str) -> str:
    if session_status != "ACTIVE":
        return "STOP TRADING"
    if final_recommendation == "take":
        return "GO"
    if final_recommendation in {"take only on pullback", "scalp only", "unavailable"}:
        return "WAIT"
    return "NO GO"


def _build_gpt_fields(
    account_size: int,
    losses_today: int,
    pnl_today: float,
    symbol: str,
    side: str,
    live_price: float | None,
    entry_price: float,
    stop_price: float,
    target_price: float,
    risk_per_contract: float,
    reward_per_contract: float,
    rr_ratio: float,
    entry_verdict: str,
    trade_verdict: str,
    session_state: dict[str, float | int | bool | str],
    final_recommendation: str,
) -> dict[str, str]:
    direction = side.upper()
    session_status = str(session_state["session_status"])
    verdict = _resolve_gpt_verdict(final_recommendation, session_status)

    if session_status != "ACTIVE":
        why = str(session_state["reason"])
        return {
            "direction": direction,
            "verdict": verdict,
            "entry_zone": "N/A",
            "stop_loss": "N/A",
            "target": "N/A",
            "rr_ratio_display": "N/A",
            "why": why,
            "watch_out_for": "Prop firm hard stops are in effect; preserve capital and reset for the next session.",
            "account_summary": f"Account: ${account_size:,} | Losses today: {losses_today}/3 | P&L today: {_format_dollars(pnl_today)}",
        }

    price_context = "above" if live_price is not None and live_price > entry_price else "below"
    why = (
        f"{symbol} is trading {price_context} the planned entry, which makes the current setup read as {entry_verdict} with a {trade_verdict} risk profile. "
        f"The structure targets {_format_dollars(reward_per_contract)} for {_format_dollars(risk_per_contract)} of risk, keeping the scalp disciplined for prop rules."
    )
    watch_out_for = "Do not widen the stop if momentum stalls near the entry zone."
    if verdict == "WAIT":
        watch_out_for = "Price is not in the cleanest entry zone yet, so waiting for location is the main edge."
    elif verdict == "NO GO":
        watch_out_for = "The reward-to-risk or prop-rule alignment is not strong enough for a disciplined scalp."

    return {
        "direction": direction,
        "verdict": verdict,
        "entry_zone": "at market" if live_price is not None and abs(entry_price - live_price) <= 0.1 else _format_price_level(entry_price),
        "stop_loss": f"{_format_dollars(risk_per_contract)} ({_format_price_level(stop_price)})",
        "target": f"{_format_dollars(reward_per_contract)} ({_format_price_level(target_price)})",
        "rr_ratio_display": f"1:{rr_ratio:.2f}",
        "why": why,
        "watch_out_for": watch_out_for,
        "account_summary": f"Account: ${account_size:,} | Losses today: {losses_today}/3 | P&L today: {_format_dollars(pnl_today)}",
    }


async def analyze_request(
    request: FuturesScalpIdeaRequest,
    price_feed: PriceFeed,
) -> FuturesScalpAnalysisResponse:
    spec = SUPPORTED_SYMBOLS[request.symbol]
    risk_template = get_account_risk_template(request.account_size)
    session_state = evaluate_session_status(
        request.account_size,
        request.realized_loss_count_today,
        request.realized_pnl_today,
    )
    active_contract_getter = getattr(price_feed, "get_active_contract", None)
    active_contract = active_contract_getter(request.symbol) if callable(active_contract_getter) else None

    if not bool(session_state["can_trade"]):
        entry_price, stop_price, target_price = _resolve_trade_levels(request, spec, risk_template, None)
        gpt_fields = _build_gpt_fields(
            account_size=request.account_size,
            losses_today=request.realized_loss_count_today,
            pnl_today=request.realized_pnl_today,
            symbol=request.symbol,
            side=request.side,
            live_price=None,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            risk_per_contract=0.0,
            reward_per_contract=0.0,
            rr_ratio=0.0,
            entry_verdict="unavailable",
            trade_verdict="avoid",
            session_state=session_state,
            final_recommendation="pass",
        )
        return FuturesScalpAnalysisResponse(
            symbol=request.symbol,
            side=request.side,
            direction=gpt_fields["direction"],
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            contracts=request.contracts,
            tick_value=spec.tick_value,
            point_value=spec.point_value,
            risk_per_contract=0.0,
            reward_per_contract=0.0,
            rr_ratio=0.0,
            atr_multiple_risk=0.0,
            live_price=None,
            distance_entry_to_live=None,
            entry_verdict="unavailable",
            trade_verdict="avoid",
            liquidity_score=spec.liquidity_score,
            risk_rule_violations={
                "per_trade_risk_exceeds_limit": False,
                "max_loss_trades_reached": request.realized_loss_count_today >= 3,
                "daily_profit_target_reached": request.realized_pnl_today >= risk_template["daily_profit_target"],
            },
            realized_pnl_today=request.realized_pnl_today,
            realized_loss_count_today=request.realized_loss_count_today,
            daily_profit_target=risk_template["daily_profit_target"],
            daily_loss_limit=risk_template["daily_loss_limit"],
            per_trade_risk_limit=risk_template["per_trade_risk"],
            per_trade_profit_target=risk_template["per_trade_target"],
            active_contract=active_contract,
            verdict=gpt_fields["verdict"],
            entry_zone=gpt_fields["entry_zone"],
            stop_loss=gpt_fields["stop_loss"],
            target=gpt_fields["target"],
            rr_ratio_display=gpt_fields["rr_ratio_display"],
            why=gpt_fields["why"],
            watch_out_for=gpt_fields["watch_out_for"],
            account_summary=gpt_fields["account_summary"],
            session_status=str(session_state["session_status"]),
            final_recommendation="pass",
            final_recommendation_comment=str(session_state["reason"]),
            as_of=datetime.now(timezone.utc),
        )

    live_price = await price_feed.get_live_price(request.symbol)
    entry_price, stop_price, target_price = _resolve_trade_levels(request, spec, risk_template, live_price)
    risk_points = _risk_points(entry_price, stop_price)
    reward_points = _reward_points(entry_price, target_price)
    risk_per_contract = risk_points * spec.point_value
    reward_per_contract = reward_points * spec.point_value
    rr_ratio = reward_per_contract / risk_per_contract if risk_per_contract else 0.0
    atr_multiple_risk = risk_points / spec.atr_reference if spec.atr_reference else 0.0

    violations = {
        "per_trade_risk_exceeds_limit": risk_per_contract * request.contracts > risk_template["per_trade_risk"],
        "max_loss_trades_reached": request.realized_loss_count_today >= 3,
        "daily_profit_target_reached": request.realized_pnl_today >= risk_template["daily_profit_target"],
    }

    entry_verdict = _entry_verdict(request.side, entry_price, live_price)
    trade_verdict = _trade_verdict(rr_ratio, violations) if live_price is not None else "unavailable"

    ctx: dict[str, Any] = {
        "mode": request.mode,
        "live_price": live_price,
        "entry_verdict": entry_verdict,
        "trade_verdict": trade_verdict,
        "liquidity_score": spec.liquidity_score,
        "rr_ratio": rr_ratio,
        "pricing_percentage_difference": _pricing_percentage_difference(entry_price, live_price),
        "risk_rule_violations": violations,
        "risk_reward_asymmetric": _risk_reward_asymmetric(request.side, stop_price, target_price, spec, live_price),
        "is_far_from_key_levels": _is_far_from_key_levels(entry_price, spec, live_price),
        "final_recommendation": None,
        "final_recommendation_comment": "",
    }
    compute_final_recommendation(ctx)
    gpt_fields = _build_gpt_fields(
        account_size=request.account_size,
        losses_today=request.realized_loss_count_today,
        pnl_today=request.realized_pnl_today,
        symbol=request.symbol,
        side=request.side,
        live_price=live_price,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        risk_per_contract=risk_per_contract,
        reward_per_contract=reward_per_contract,
        rr_ratio=rr_ratio,
        entry_verdict=entry_verdict,
        trade_verdict=trade_verdict,
        session_state=session_state,
        final_recommendation=ctx["final_recommendation"],
    )

    return FuturesScalpAnalysisResponse(
        symbol=request.symbol,
        side=request.side,
        direction=gpt_fields["direction"],
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        contracts=request.contracts,
        tick_value=spec.tick_value,
        point_value=spec.point_value,
        risk_per_contract=round(risk_per_contract, 2),
        reward_per_contract=round(reward_per_contract, 2),
        rr_ratio=round(rr_ratio, 2),
        atr_multiple_risk=round(atr_multiple_risk, 4),
        live_price=live_price,
        distance_entry_to_live=_distance_entry_to_live(entry_price, live_price),
        entry_verdict=entry_verdict,
        trade_verdict=trade_verdict,
        liquidity_score=ctx["liquidity_score"],
        risk_rule_violations=violations,
        realized_pnl_today=request.realized_pnl_today,
        realized_loss_count_today=request.realized_loss_count_today,
        daily_profit_target=risk_template["daily_profit_target"],
        daily_loss_limit=risk_template["daily_loss_limit"],
        per_trade_risk_limit=risk_template["per_trade_risk"],
        per_trade_profit_target=risk_template["per_trade_target"],
        active_contract=active_contract,
        verdict=gpt_fields["verdict"],
        entry_zone=gpt_fields["entry_zone"],
        stop_loss=gpt_fields["stop_loss"],
        target=gpt_fields["target"],
        rr_ratio_display=gpt_fields["rr_ratio_display"],
        why=gpt_fields["why"],
        watch_out_for=gpt_fields["watch_out_for"],
        account_summary=gpt_fields["account_summary"],
        session_status=str(session_state["session_status"]),
        final_recommendation=ctx["final_recommendation"],
        final_recommendation_comment=ctx["final_recommendation_comment"],
        as_of=datetime.now(timezone.utc),
    )
