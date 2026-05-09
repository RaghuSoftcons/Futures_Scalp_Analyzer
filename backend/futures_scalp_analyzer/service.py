"""Core analysis service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .apex import (
    EXECUTION_MODE,
    NEWS_DECISION_POLICY,
    ORDER_ROUTING_ENABLED,
    PLATFORM_NAME,
    build_accountability_status,
    build_manual_execution_notice,
)
from .economic_calendar import fetch_economic_events
from .market_analysis import compute_market_context
from .models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from .news_context import fetch_news_context
from .price_feed import PriceFeed
from .recommendations import compute_final_recommendation
from .risk import evaluate_session_status, get_account_risk_template
from .session_guard import check_session_allowed
from .symbols import SUPPORTED_SYMBOLS, SymbolSpec



def _compute_analysis_long(
    side: str,
    trend: str | None,
    market_structure: str | None,
    rr_ratio: float,
    entry_verdict: str,
    timeframe_alignment: str,
    rsi: float | None,
    vwap_position: str | None,
) -> str:
    """Generate a plain-English analysis sentence for one direction."""
    if side == "long":
        momentum_desc = "bullish" if trend in ("uptrend",) else "bearish" if trend in ("downtrend",) else "mixed"
        structure_desc = "bullish" if market_structure == "bullish_structure" else "bearish" if market_structure == "bearish_structure" else "neutral"
        rsi_desc = f"RSI {rsi:.0f} (overbought)" if rsi is not None and rsi > 70 else f"RSI {rsi:.0f} (oversold — favorable for long)" if rsi is not None and rsi < 35 else f"RSI {rsi:.0f} (neutral)" if rsi is not None else "RSI unavailable"
        return (
            f"Momentum leaning {momentum_desc} short-term, "
            f"{structure_desc} market structure, "
            f"{rsi_desc}, "
            f"R:R ({rr_ratio:.1f}:1), "
            f"entry is {entry_verdict}, "
            f"timeframe alignment: {timeframe_alignment}."
        )
    else:
        momentum_desc = "bearish" if trend in ("downtrend",) else "bullish" if trend in ("uptrend",) else "mixed"
        structure_desc = "bearish" if market_structure == "bearish_structure" else "bullish" if market_structure == "bullish_structure" else "neutral"
        rsi_desc = f"RSI {rsi:.0f} (overbought — favorable for short)" if rsi is not None and rsi > 65 else f"RSI {rsi:.0f} (oversold)" if rsi is not None and rsi < 30 else f"RSI {rsi:.0f} (neutral)" if rsi is not None else "RSI unavailable"
        return (
            f"Momentum leaning {momentum_desc} short-term, "
            f"{structure_desc} market structure, "
            f"{rsi_desc}, "
            f"R:R ({rr_ratio:.1f}:1) — shorts align with structure if {vwap_position or 'N/A'} holds, "
            f"timeframe alignment: {timeframe_alignment}."
        )

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


def _compute_timeframe_alignment(bias_1m: str, bias_3m: str, bias_5m: str, bias_15m: str) -> str:
    biases = [bias_1m, bias_3m, bias_5m, bias_15m]
    neutral_count = sum(1 for bias in biases if bias == "neutral")
    if neutral_count >= 2:
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
    bias_3m: str,
    bias_5m: str,
    bias_15m: str,
    timeframe_alignment: str,
    news_bias: str,
    news_bias_note: str,
    trump_posts_recent: list[str],
    top_headlines: list[str],
    economic_event_warning: bool,
    next_economic_event: str,
    economic_events_today: list[str],
    economic_warning_message: str,
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
                f"3-min: {bias_3m}\n"
                f"5-min: {bias_5m}\n"
                f"15-min: {bias_15m}\n"
                f"Alignment: {timeframe_alignment}"
            ),
            "news_context": "## News & Geopolitical Context\nunavailable",
            "economic_calendar": "## Economic Calendar\nunavailable",
        }

    if not market_data_available:
        return {
            "direction": direction,
            "verdict": verdict,
            "entry_zone": "WAIT FOR REOPEN",
            "stop_loss": f"{_format_dollars(risk_per_contract)} ({_format_price_level(stop_price)})",
            "target": f"{_format_dollars(reward_per_contract)} ({_format_price_level(target_price)})",
            "rr_ratio_display": f"1:{rr_ratio:.2f}",
            "why": (
                f"{symbol} does not have fresh intraday market context available right now, so the scalp engine cannot confirm timing. "
                "Wait for the next active session and a live bar set before taking a directional trade."
            ),
            "watch_out_for": "Do not act on stale or closed-session quotes; wait for live session data and fresh market structure.",
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
                f"3-min: {bias_3m}\n"
                f"5-min: {bias_5m}\n"
                f"15-min: {bias_15m}\n"
                f"Alignment: {timeframe_alignment}"
            ),
            "news_context": (
                "## News & Geopolitical Context\n"
                f"News bias: {news_bias}\n"
                f"News note: {news_bias_note or 'none'}\n"
                f"Recent Truth Social posts: {', '.join(trump_posts_recent) if trump_posts_recent else 'none'}\n"
                f"Top headlines: {', '.join(top_headlines) if top_headlines else 'none'}"
            ),
            "economic_calendar": (
                "## Economic Calendar\n"
                f"Event warning active: {economic_event_warning}\n"
                f"Next economic event: {next_economic_event or 'none'}\n"
                f"Events today: {', '.join(economic_events_today) if economic_events_today else 'none'}\n"
                f"Warning message: {economic_warning_message or 'none'}"
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
            f"3-min: {bias_3m}\n"
            f"5-min: {bias_5m}\n"
            f"15-min: {bias_15m}\n"
            f"Alignment: {timeframe_alignment}\n\n"
            "If alignment is aligned_long or aligned_short, treat it as strong confirmation. "
            "If alignment is mixed, explicitly call out conflict in watch_out_for."
        ),
        "news_context": (
            "## News & Geopolitical Context\n"
            f"News bias: {news_bias}\n"
            f"News note: {news_bias_note or 'none'}\n"
            f"Recent Truth Social posts: {', '.join(trump_posts_recent) if trump_posts_recent else 'none'}\n"
            f"Top headlines: {', '.join(top_headlines) if top_headlines else 'none'}\n\n"
            "Display-only context. Do not use news/geopolitical context to make, upgrade, or downgrade trade decisions."
        ),
        "economic_calendar": (
            "## Economic Calendar\n"
            f"Event warning active: {economic_event_warning}\n"
            f"Next economic event: {next_economic_event or 'none'}\n"
            f"Events today: {', '.join(economic_events_today) if economic_events_today else 'none'}\n"
            f"Warning message: {economic_warning_message or 'none'}\n\n"
            "If warning is active, emphasize caution and reduced aggressiveness."
        ),
    }


def _recommendation_rank(value: str) -> int:
    return {
        "take": 4,
        "scalp only": 3,
        "take only on pullback": 2,
        "pass": 1,
        "flatten": 1,
        "unavailable": 0,
    }.get(value, -1)


def _select_preferred_response(
    long_response: FuturesScalpAnalysisResponse | dict[str, Any],
    short_response: FuturesScalpAnalysisResponse | dict[str, Any],
) -> FuturesScalpAnalysisResponse | dict[str, Any]:
    if isinstance(long_response, dict):
        return short_response
    if isinstance(short_response, dict):
        return long_response

    candidates = [long_response, short_response]
    return max(
        candidates,
        key=lambda response: (
            _recommendation_rank(response.final_recommendation),
            float(response.directional_score),
            float(response.rr_ratio) if isinstance(response.rr_ratio, (int, float)) else 0.0,
        ),
    )


def _apex_response_fields(request: FuturesScalpIdeaRequest) -> dict[str, Any]:
    return {
        "platform": PLATFORM_NAME,
        "execution_mode": EXECUTION_MODE,
        "order_routing_enabled": ORDER_ROUTING_ENABLED,
        "manual_execution_notice": build_manual_execution_notice(),
        "news_decision_policy": NEWS_DECISION_POLICY,
        "trader_id": request.trader_id,
        "trade_plan_id": request.trade_plan_id,
        "accountability_status": build_accountability_status(
            request.trader_id,
            request.trade_plan_id,
        ),
    }


async def _analyze_request_for_side(
    request: FuturesScalpIdeaRequest,
    price_feed: PriceFeed,
) -> FuturesScalpAnalysisResponse | dict[str, Any]:
    spec = SUPPORTED_SYMBOLS[request.symbol]
    risk_template = get_account_risk_template(request.account_size)
    session_guard = check_session_allowed(
        account_size=request.account_size,
        losses_today=request.realized_loss_count_today,
        pnl_today=request.realized_pnl_today,
    )
    if not session_guard["allowed"]:
        entry_price, stop_price, target_price = _resolve_trade_levels(request, spec, risk_template, None)
        return FuturesScalpAnalysisResponse(
            **_apex_response_fields(request),
            symbol=request.symbol,
            side=request.side,
            direction=request.side.upper(),
            requested_side=request.side,
            auto_selected=False,
            evaluated_sides=[request.side],
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
            active_contract="",
            verdict="STOP TRADING",
            entry_zone="N/A",
            stop_loss="N/A",
            target="N/A",
            rr_ratio_display="N/A",
            why=str(session_guard["reason"]),
            watch_out_for="Session is LOCKED by the daily loss guard.",
            account_summary=(
                f"Account: ${request.account_size:,} | Losses today: {request.realized_loss_count_today}/3 | "
                f"P&L today: {_format_dollars(request.realized_pnl_today)}"
            ),
            session_status="LOCKED",
            final_recommendation="pass",
            final_recommendation_comment=str(session_guard["reason"]),
            daily_loss_pct=float(session_guard["daily_loss_pct"]),
            daily_loss_limit_pct=float(session_guard["daily_loss_limit_pct"]),
            market_data_available=False,
            as_of=datetime.now(timezone.utc),
        )
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
            bias_3m="neutral",
            bias_5m="neutral",
            bias_15m="neutral",
            timeframe_alignment="neutral",
            news_bias="neutral",
            news_bias_note="",
            trump_posts_recent=[],
            top_headlines=[],
            economic_event_warning=False,
            next_economic_event="",
            economic_events_today=[],
            economic_warning_message="",
            session_state=session_state,
            final_recommendation="pass",
        )
        return FuturesScalpAnalysisResponse(
            **_apex_response_fields(request),
            symbol=request.symbol,
            side=request.side,
            direction=gpt_fields["direction"],
            requested_side=request.side,
            auto_selected=False,
            evaluated_sides=[request.side],
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
            active_contract=active_contract or "",
            verdict=gpt_fields["verdict"],
            entry_zone=gpt_fields["entry_zone"],
            stop_loss=gpt_fields["stop_loss"],
            target=gpt_fields["target"],
            rr_ratio_display=gpt_fields["rr_ratio_display"],
            why=gpt_fields["why"],
            watch_out_for=gpt_fields["watch_out_for"],
            account_summary=gpt_fields["account_summary"],
            final_recommendation="pass",
            final_recommendation_comment=str(session_state["reason"]),
            directional_score=0.0,
            momentum_bias="neutral",
            bias_1m="neutral",
            bias_3m="neutral",
            bias_5m="neutral",
            bias_15m="neutral",
            timeframe_alignment="neutral",
            daily_loss_pct=float(session_guard["daily_loss_pct"]),
            daily_loss_limit_pct=float(session_guard["daily_loss_limit_pct"]),
            session_status=str(session_state["session_status"]),
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
    bars_3m: list[dict] = []
    bars_5m: list[dict] = []
    bars_15m: list[dict] = []
    daily_bars: list[dict] = []
    bars_1m_result, bars_3m_result, bars_5m_result, bars_15m_result, daily_bars_result, news_context, economic_context = await asyncio.gather(
        price_feed.get_bars(request.symbol, "minute", 1, "day", 1),
        price_feed.get_bars(request.symbol, "minute", 3, "day", 2),
        price_feed.get_bars(request.symbol, "minute", 5, "day", 2),
        price_feed.get_bars(request.symbol, "minute", 15, "day", 5),
        price_feed.get_bars(request.symbol, "daily", 1, "day", 5),
        fetch_news_context(),
        fetch_economic_events(request.symbol),
        return_exceptions=True,
    )
    for idx, result in enumerate([bars_1m_result, bars_3m_result, bars_5m_result, bars_15m_result, daily_bars_result]):
        if isinstance(result, Exception):
            continue
        if idx == 0:
            bars_1m = result
        elif idx == 1:
            bars_3m = result
        elif idx == 2:
            bars_5m = result
        elif idx == 3:
            bars_15m = result
        else:
            daily_bars = result
    if isinstance(news_context, Exception):
        news_context = {}
    if isinstance(economic_context, Exception):
        economic_context = {}

    bias_1m = _compute_timeframe_bias(bars_1m)
    bias_3m = _compute_timeframe_bias(bars_3m)
    bias_5m = _compute_timeframe_bias(bars_5m)
    bias_15m = _compute_timeframe_bias(bars_15m)
    timeframe_alignment = _compute_timeframe_alignment(bias_1m, bias_3m, bias_5m, bias_15m)

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
    if bool(economic_context.get("event_block")):
        ctx["final_recommendation"] = "pass"
        ctx["final_recommendation_comment"] = str(economic_context.get("warning_message") or "Economic event block active.")
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
        bias_3m=bias_3m,
        bias_5m=bias_5m,
        bias_15m=bias_15m,
        timeframe_alignment=timeframe_alignment,
        news_bias=str(news_context.get("news_bias", "neutral")),
        news_bias_note=str(news_context.get("news_bias_note", "")),
        trump_posts_recent=list(news_context.get("trump_posts_recent", [])),
        top_headlines=list(news_context.get("top_headlines", [])),
        economic_event_warning=bool(economic_context.get("event_warning", False)),
        next_economic_event=str(economic_context.get("next_event", "")),
        economic_events_today=list(economic_context.get("events_today", [])),
        economic_warning_message=str(economic_context.get("warning_message", "")),
        session_state=session_state,
        final_recommendation=ctx["final_recommendation"],
    )
    watch_out_for = gpt_fields["watch_out_for"]
    if bool(economic_context.get("event_warning")):
        warning_message = str(economic_context.get("warning_message") or "Economic event approaching.")
        watch_out_for = f"{warning_message} {watch_out_for}".strip()
    if bool(economic_context.get("event_block")):
        warning_message = str(economic_context.get("warning_message") or "Economic event block active.")
        watch_out_for = f"{watch_out_for} {warning_message}".strip()

    return FuturesScalpAnalysisResponse(
        **_apex_response_fields(request),
        symbol=request.symbol,
        side=request.side,
        direction=gpt_fields["direction"],
        requested_side=request.side,
        auto_selected=False,
        evaluated_sides=[request.side],
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
        active_contract=active_contract or "",
        verdict=gpt_fields["verdict"],
        entry_zone=gpt_fields["entry_zone"],
        stop_loss=gpt_fields["stop_loss"],
        target=gpt_fields["target"],
        rr_ratio_display=gpt_fields["rr_ratio_display"],
        why=gpt_fields["why"],
        watch_out_for=watch_out_for,
        account_summary=gpt_fields["account_summary"],
        session_status=str(session_state["session_status"]),
        final_recommendation=ctx["final_recommendation"],
        final_recommendation_comment=ctx["final_recommendation_comment"],
        directional_score=round(directional_score, 1),
        momentum_bias=momentum_bias,
        bias_1m=bias_1m,
        bias_3m=bias_3m,
        bias_5m=bias_5m,
        bias_15m=bias_15m,
        timeframe_alignment=timeframe_alignment,
            news_bias=str(news_context.get("news_bias", "neutral")),
            news_bias_note=str(news_context.get("news_bias_note", "")),
            trump_posts_count=int(news_context.get("trump_posts_count", 0)),
            trump_posts_recent=list(news_context.get("trump_posts_recent", [])),
            trump_posts_recent_detailed=list(news_context.get("trump_posts_recent_detailed", [])),
            top_headlines=list(news_context.get("top_headlines", [])),
            top_headlines_detailed=list(news_context.get("top_headlines_detailed", [])),
            economic_event_warning=bool(economic_context.get("event_warning", False)),
        economic_event_block=bool(economic_context.get("event_block", False)),
        next_economic_event=str(economic_context.get("next_event", "")),
        economic_events_today=list(economic_context.get("events_today", [])),
        economic_warning_message=str(economic_context.get("warning_message", "")),
        daily_loss_pct=float(session_guard["daily_loss_pct"]),
        daily_loss_limit_pct=float(session_guard["daily_loss_limit_pct"]),
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
        analysis_long=_compute_analysis_long(
            side="long", trend=gpt_fields["trend"], market_structure=gpt_fields["market_structure"],
            rr_ratio=rr_ratio, entry_verdict=entry_verdict, timeframe_alignment=timeframe_alignment,
            rsi=market_context.get("rsi"), vwap_position=market_context.get("vwap_position"),
        ),
        analysis_short=_compute_analysis_long(
            side="short", trend=gpt_fields["trend"], market_structure=gpt_fields["market_structure"],
            rr_ratio=rr_ratio, entry_verdict=entry_verdict, timeframe_alignment=timeframe_alignment,
            rsi=market_context.get("rsi"), vwap_position=market_context.get("vwap_position"),
        ),
    )


async def analyze_request(
    request: FuturesScalpIdeaRequest,
    price_feed: PriceFeed,
) -> FuturesScalpAnalysisResponse | dict[str, Any]:
    if request.side is not None:
        response = await _analyze_request_for_side(request, price_feed)
        if isinstance(response, FuturesScalpAnalysisResponse):
            response.requested_side = request.side
            response.auto_selected = False
            response.evaluated_sides = [request.side]
        return response

    if request.mode == "position_mgmt":
        return {
            "error": "direction_required",
            "detail": "Position management requests must include side as long or short.",
            "symbol": request.symbol,
            "mode": request.mode,
            "final_recommendation": "unavailable",
            "final_recommendation_comment": "Direction is required for position management.",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    long_request = request.model_copy(update={"side": "long"})
    short_request = request.model_copy(update={"side": "short"})
    long_response, short_response = await asyncio.gather(
        _analyze_request_for_side(long_request, price_feed),
        _analyze_request_for_side(short_request, price_feed),
    )
    selected_response = _select_preferred_response(long_response, short_response)
    if isinstance(selected_response, FuturesScalpAnalysisResponse):
        selected_response.requested_side = None
        selected_response.auto_selected = True
        selected_response.evaluated_sides = ["long", "short"]
    return selected_response
