"""Core analysis service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .market_analysis import compute_market_context
from .models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from .price_feed import PriceFeed
from .recommendations import compute_final_recommendation
from .risk import evaluate_session_status, get_account_risk_template
from .symbols import SUPPORTED_SYMBOLS, SymbolSpec


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


def _timeframe_vwap(bars: list[dict]) -> float | None:
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for bar in bars:
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        volume = float(bar.get("volume", 0.0))
        typical_price = (high + low + close) / 3.0
        cumulative_pv += typical_price * volume
        cumulative_volume += volume
    if cumulative_volume == 0:
        return None
    return cumulative_pv / cumulative_volume


def _compute_timeframe_bias(bars: list[dict]) -> str:
    if len(bars) < 20:
        return "neutral"
    closes = [float(bar["close"]) for bar in bars]
    ema9 = _ema(closes, 9)
    ema20 = _ema(closes, 20)
    rsi = _wilder_rsi(closes, 14)
    vwap = _timeframe_vwap(bars)
    latest_close = closes[-1]
    if ema9 is None or ema20 is None or rsi is None or vwap is None:
        return "neutral"
    if ema9 > ema20 and latest_close > vwap and rsi > 50:
        return "long"
    if ema9 < ema20 and latest_close < vwap and rsi < 50:
        return "short"
    return "neutral"


def _compute_timeframe_alignment(bias_1m: str, bias_5m: str, bias_15m: str) -> str:
    biases = [bias_1m, bias_5m, bias_15m]
    neutral_count = sum(1 for bias in biases if bias == "neutral")
    if neutral_count >= 2 or neutral_count == 3:
        return "neutral"
    if all(bias == "long" for bias in biases):
        return "aligned_long"
    if all(bias == "short" for bias in biases):
        return "aligned_short"
    return "mixed"


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


def _compute_directional_score(
    side: str,
    live_price: float | None,
    spec: SymbolSpec,
    entry_verdict: str,
    rr_ratio: float,
    trade_verdict: str,
) -> float:
    del side, live_price, spec
    score = 50.0

    entry_score_map = {
        "attractive": 15.0,
        "fair": 5.0,
        "rich": -15.0,
    }
    trade_score_map = {
        "favorable": 20.0,
        "neutral": 5.0,
        "speculative": -10.0,
        "avoid": -30.0,
    }

    score += entry_score_map.get(entry_verdict, 0.0)
    score += trade_score_map.get(trade_verdict, 0.0)
    score += min((rr_ratio - 1.0) * 5.0, 15.0)

    return max(0.0, min(100.0, score))


def _momentum_bias(directional_score: float) -> str:
    if directional_score >= 65:
        return "bullish"
    if directional_score <= 35:
        return "bearish"
    return "neutral"


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
    directional_score: float,
    momentum_bias: str,
    ema9: float | None,
    ema20: float | None,
    vwap: float | None,
    rsi: float | None,
    trend: str | None,
    market_structure: str | None,
    volume_condition: str | None,
    rsi_condition: str | None,
    session_high: float | None,
    session_low: float | None,
    prior_day_high: float | None,
    prior_day_low: float | None,
    live_atr: float | None,
    market_data_available: bool,
    bias_1m: str,
    bias_5m: str,
    bias_15m: str,
    timeframe_alignment: str,
    session_state: dict[str, float | int | bool | str],
    final_recommendation: str,
) -> dict[str, str]:
    def _fmt_number(value: float | None) -> str:
        if not market_data_available or value is None:
            return "unavailable"
        return f"{value:,.2f}"

    def _fmt_text(value: str | None) -> str:
        if not market_data_available or value is None:
            return "unavailable"
        return value

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
            "ema9": "unavailable",
            "ema20": "unavailable",
            "vwap": "unavailable",
            "rsi": "unavailable",
            "trend": "unavailable",
            "market_structure": "unavailable",
            "volume_condition": "unavailable",
            "rsi_condition": "unavailable",
            "session_high": "unavailable",
            "session_low": "unavailable",
            "prior_day_high": "unavailable",
            "prior_day_low": "unavailable",
            "live_atr": "unavailable",
            "market_data_available": "false",
            "timeframe_bias": (
                "## Timeframe Bias\n"
                f"1-min: {bias_1m}\n"
                f"5-min: {bias_5m}\n"
                f"15-min: {bias_15m}\n"
                f"Alignment: {timeframe_alignment}"
            ),
        }

    price_context = "above" if live_price is not None and live_price > entry_price else "below"
    why = (
        f"{symbol} is trading {price_context} the planned entry, which makes the current setup read as {entry_verdict} with a {trade_verdict} risk profile. "
        f"The structure targets {_format_dollars(reward_per_contract)} for {_format_dollars(risk_per_contract)} of risk, keeping the scalp disciplined for prop rules."
        f" Directional momentum bias: {momentum_bias} (score: {directional_score:.0f}/100)."
    )
    watch_out_for = "Do not widen the stop if momentum stalls near the entry zone."
    if verdict == "WAIT":
        watch_out_for = "Price is not in the cleanest entry zone yet, so waiting for location is the main edge."
    elif verdict == "NO GO":
        watch_out_for = "The reward-to-risk or prop-rule alignment is not strong enough for a disciplined scalp."
    if timeframe_alignment in {"aligned_long", "aligned_short"}:
        watch_out_for = f"{watch_out_for} Multi-timeframe alignment is strong confirmation ({timeframe_alignment})."
    elif timeframe_alignment == "mixed":
        watch_out_for = f"{watch_out_for} Timeframe conflict detected; wait for alignment before committing size."

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
        "ema9": _fmt_number(ema9),
        "ema20": _fmt_number(ema20),
        "vwap": _fmt_number(vwap),
        "rsi": _fmt_number(rsi),
        "trend": _fmt_text(trend),
        "market_structure": _fmt_text(market_structure),
        "volume_condition": _fmt_text(volume_condition),
        "rsi_condition": _fmt_text(rsi_condition),
        "session_high": _fmt_number(session_high),
        "session_low": _fmt_number(session_low),
        "prior_day_high": _fmt_number(prior_day_high),
        "prior_day_low": _fmt_number(prior_day_low),
        "live_atr": _fmt_number(live_atr),
        "market_data_available": str(market_data_available).lower(),
        "timeframe_bias": (
            "## Timeframe Bias\n"
            f"1-min: {bias_1m}\n"
            f"5-min: {bias_5m}\n"
            f"15-min: {bias_15m}\n"
            f"Alignment: {timeframe_alignment}\n\n"
            "If alignment is aligned_long or aligned_short, treat it as strong confirmation. "
            "If alignment is mixed, explicitly call out conflict in watch_out_for."
        ),
    }


async def analyze_request(
    request: FuturesScalpIdeaRequest,
    price_feed: PriceFeed,
) -> FuturesScalpAnalysisResponse | dict[str, Any]:
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
            directional_score=0.0,
            momentum_bias="neutral",
            ema9=None,
            ema20=None,
            vwap=None,
            rsi=None,
            trend=None,
            market_structure=None,
            volume_condition=None,
            rsi_condition=None,
            session_high=None,
            session_low=None,
            prior_day_high=None,
            prior_day_low=None,
            live_atr=None,
            market_data_available=False,
            bias_1m="neutral",
            bias_5m="neutral",
            bias_15m="neutral",
            timeframe_alignment="neutral",
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
            directional_score=0.0,
            momentum_bias="neutral",
            bias_1m="neutral",
            bias_5m="neutral",
            bias_15m="neutral",
            timeframe_alignment="neutral",
            market_data_available=False,
            as_of=datetime.now(timezone.utc),
        )

    try:
        live_price = await asyncio.wait_for(price_feed.get_live_price(request.symbol), timeout=10.0)
    except asyncio.TimeoutError:
        entry_price, stop_price, target_price = _resolve_trade_levels(request, spec, risk_template, None)
        return {
            "error": "price_feed_timeout",
            "detail": f"Timed out fetching live price for {request.symbol} after 10 seconds.",
            "symbol": request.symbol,
            "side": request.side,
            "mode": request.mode,
            "active_contract": active_contract,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "contracts": request.contracts,
            "session_status": str(session_state["session_status"]),
            "final_recommendation": "unavailable",
            "final_recommendation_comment": "Live Schwab quote timed out. Retry shortly.",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
    bars_1m: list[dict] = []
    bars_5m: list[dict] = []
    bars_15m: list[dict] = []
    daily_bars: list[dict] = []
    bars_results = await asyncio.gather(
        price_feed.get_bars(request.symbol, "minute", 1, "day", 1),
        price_feed.get_bars(request.symbol, "minute", 5, "day", 2),
        price_feed.get_bars(request.symbol, "minute", 15, "day", 5),
        price_feed.get_bars(request.symbol, "daily", 1, "day", 5),
        return_exceptions=True,
    )
    for idx, result in enumerate(bars_results):
        if isinstance(result, Exception):
            continue
        if idx == 0:
            bars_1m = result
        elif idx == 1:
            bars_5m = result
        elif idx == 2:
            bars_15m = result
        else:
            daily_bars = result

    bias_1m = _compute_timeframe_bias(bars_1m)
    bias_5m = _compute_timeframe_bias(bars_5m)
    bias_15m = _compute_timeframe_bias(bars_15m)
    timeframe_alignment = _compute_timeframe_alignment(bias_1m, bias_5m, bias_15m)

    prior_day_high = float(daily_bars[-2]["high"]) if len(daily_bars) >= 2 else None
    prior_day_low = float(daily_bars[-2]["low"]) if len(daily_bars) >= 2 else None
    market_context = compute_market_context(
        bars_1m,
        bars_5m,
        bars_15m,
        request.symbol,
        prior_day_high=prior_day_high,
        prior_day_low=prior_day_low,
    )

    entry_price, stop_price, target_price = _resolve_trade_levels(request, spec, risk_template, live_price)
    risk_points = _risk_points(entry_price, stop_price)
    reward_points = _reward_points(entry_price, target_price)
    risk_per_contract = risk_points * spec.point_value
    reward_per_contract = reward_points * spec.point_value
    rr_ratio = reward_per_contract / risk_per_contract if risk_per_contract else 0.0
    atr_reference = float(market_context.get("live_atr") or spec.atr_reference)
    atr_multiple_risk = risk_points / atr_reference if atr_reference else 0.0

    violations = {
        "per_trade_risk_exceeds_limit": risk_per_contract * request.contracts > risk_template["per_trade_risk"],
        "max_loss_trades_reached": request.realized_loss_count_today >= 3,
        "daily_profit_target_reached": request.realized_pnl_today >= risk_template["daily_profit_target"],
    }

    entry_verdict = _entry_verdict(request.side, entry_price, live_price)
    trade_verdict = _trade_verdict(rr_ratio, violations) if live_price is not None else "unavailable"

    ctx: dict[str, Any] = {
        "mode": request.mode,
        "side": request.side,
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
        **market_context,
    }
    compute_final_recommendation(ctx)
    directional_score = _compute_directional_score(
        side=request.side,
        live_price=live_price,
        spec=spec,
        entry_verdict=entry_verdict,
        rr_ratio=rr_ratio,
        trade_verdict=trade_verdict,
    )
    momentum_bias = _momentum_bias(directional_score)
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
        directional_score=directional_score,
        momentum_bias=momentum_bias,
        ema9=market_context.get("ema9"),
        ema20=market_context.get("ema20"),
        vwap=market_context.get("vwap"),
        rsi=market_context.get("rsi"),
        trend=market_context.get("trend"),
        market_structure=market_context.get("market_structure"),
        volume_condition=market_context.get("volume_condition"),
        rsi_condition=market_context.get("rsi_condition"),
        session_high=market_context.get("session_high"),
        session_low=market_context.get("session_low"),
        prior_day_high=market_context.get("prior_day_high"),
        prior_day_low=market_context.get("prior_day_low"),
        live_atr=market_context.get("live_atr"),
        market_data_available=bool(market_context.get("market_data_available", False)),
        bias_1m=bias_1m,
        bias_5m=bias_5m,
        bias_15m=bias_15m,
        timeframe_alignment=timeframe_alignment,
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
        directional_score=round(directional_score, 1),
        momentum_bias=momentum_bias,
        bias_1m=bias_1m,
        bias_5m=bias_5m,
        bias_15m=bias_15m,
        timeframe_alignment=timeframe_alignment,
        ema9=gpt_fields["ema9"],
        ema20=gpt_fields["ema20"],
        vwap=gpt_fields["vwap"],
        rsi=gpt_fields["rsi"],
        live_atr=gpt_fields["live_atr"],
        volume_ratio=market_context.get("volume_ratio"),
        trend=gpt_fields["trend"],
        market_structure=gpt_fields["market_structure"],
        vwap_position=market_context.get("vwap_position"),
        rsi_condition=gpt_fields["rsi_condition"],
        volume_condition=gpt_fields["volume_condition"],
        session_high=gpt_fields["session_high"],
        session_low=gpt_fields["session_low"],
        prior_day_high=gpt_fields["prior_day_high"],
        prior_day_low=gpt_fields["prior_day_low"],
        market_data_available=bool(market_context.get("market_data_available", False)),
        as_of=datetime.now(timezone.utc),
    )
