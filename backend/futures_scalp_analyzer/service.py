"""Core analysis service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from .price_feed import PriceFeed
from .recommendations import compute_final_recommendation
from .risk import get_account_risk_template
from .symbols import SUPPORTED_SYMBOLS, SymbolSpec


def _risk_points(request: FuturesScalpIdeaRequest) -> float:
    return abs(request.entry_price - request.stop_price)


def _reward_points(request: FuturesScalpIdeaRequest) -> float:
    return abs(request.target_price - request.entry_price)


def _distance_entry_to_live(request: FuturesScalpIdeaRequest, live_price: float | None) -> float | None:
    if live_price is None:
        return None
    return request.entry_price - live_price


def _pricing_percentage_difference(request: FuturesScalpIdeaRequest, live_price: float | None) -> float:
    if live_price is None or live_price == 0:
        return 0.0
    return abs((request.entry_price - live_price) / live_price) * 100.0


def _entry_verdict(request: FuturesScalpIdeaRequest, live_price: float | None) -> str:
    if live_price is None:
        return "unavailable"
    pricing_diff = _pricing_percentage_difference(request, live_price)
    is_attractive = (
        request.side == "long" and request.entry_price <= live_price
    ) or (
        request.side == "short" and request.entry_price >= live_price
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


def _risk_reward_asymmetric(request: FuturesScalpIdeaRequest, spec: SymbolSpec, live_price: float | None) -> bool:
    if live_price is None:
        return False
    if request.side == "long":
        risk_remaining_points = max(live_price - request.stop_price, 0.0)
        reward_remaining_points = max(request.target_price - live_price, 0.0)
    else:
        risk_remaining_points = max(request.stop_price - live_price, 0.0)
        reward_remaining_points = max(live_price - request.target_price, 0.0)

    risk_remaining = risk_remaining_points * spec.point_value
    reward_remaining = reward_remaining_points * spec.point_value
    return reward_remaining <= risk_remaining


def _is_far_from_key_levels(request: FuturesScalpIdeaRequest, spec: SymbolSpec, live_price: float | None) -> bool:
    if live_price is None:
        return False
    return abs(live_price - request.entry_price) >= 0.2 * spec.atr_reference


async def analyze_request(
    request: FuturesScalpIdeaRequest,
    price_feed: PriceFeed,
) -> FuturesScalpAnalysisResponse:
    spec = SUPPORTED_SYMBOLS[request.symbol]
    risk_template = get_account_risk_template(request.account_size)

    live_price = await price_feed.get_live_price(request.symbol)
    risk_points = _risk_points(request)
    reward_points = _reward_points(request)
    risk_per_contract = risk_points * spec.point_value
    reward_per_contract = reward_points * spec.point_value
    rr_ratio = reward_per_contract / risk_per_contract if risk_per_contract else 0.0
    atr_multiple_risk = risk_points / spec.atr_reference if spec.atr_reference else 0.0

    violations = {
        "per_trade_risk_exceeds_limit": risk_per_contract * request.contracts > risk_template["per_trade_risk"],
        "max_loss_trades_reached": request.realized_loss_count_today >= 3,
        "daily_profit_target_reached": request.realized_pnl_today >= risk_template["daily_profit_target"],
    }

    ctx: dict[str, Any] = {
        "mode": request.mode,
        "live_price": live_price,
        "entry_verdict": _entry_verdict(request, live_price),
        "trade_verdict": _trade_verdict(rr_ratio, violations) if live_price is not None else "unavailable",
        "liquidity_score": spec.liquidity_score,
        "rr_ratio": rr_ratio,
        "pricing_percentage_difference": _pricing_percentage_difference(request, live_price),
        "risk_rule_violations": violations,
        "risk_reward_asymmetric": _risk_reward_asymmetric(request, spec, live_price),
        "is_far_from_key_levels": _is_far_from_key_levels(request, spec, live_price),
        "final_recommendation": None,
        "final_recommendation_comment": "",
    }
    compute_final_recommendation(ctx)

    return FuturesScalpAnalysisResponse(
        symbol=request.symbol,
        side=request.side,
        entry_price=request.entry_price,
        stop_price=request.stop_price,
        target_price=request.target_price,
        contracts=request.contracts,
        tick_value=spec.tick_value,
        point_value=spec.point_value,
        risk_per_contract=round(risk_per_contract, 2),
        reward_per_contract=round(reward_per_contract, 2),
        rr_ratio=round(rr_ratio, 2),
        atr_multiple_risk=round(atr_multiple_risk, 4),
        live_price=live_price,
        distance_entry_to_live=_distance_entry_to_live(request, live_price),
        entry_verdict=ctx["entry_verdict"],
        trade_verdict=ctx["trade_verdict"],
        liquidity_score=ctx["liquidity_score"],
        risk_rule_violations=violations,
        realized_pnl_today=request.realized_pnl_today,
        realized_loss_count_today=request.realized_loss_count_today,
        daily_profit_target=risk_template["daily_profit_target"],
        per_trade_risk_limit=risk_template["per_trade_risk"],
        per_trade_profit_target=risk_template["per_trade_target"],
        final_recommendation=ctx["final_recommendation"],
        final_recommendation_comment=ctx["final_recommendation_comment"],
        as_of=datetime.now(timezone.utc),
    )
