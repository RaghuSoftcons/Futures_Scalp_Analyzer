import asyncio
from datetime import datetime, timezone

from futures_scalp_analyzer.models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import StaticPriceFeed
from futures_scalp_analyzer.service import analyze_request
import futures_scalp_analyzer.service as service_module


def _response(side: str, final_recommendation: str, directional_score: float) -> FuturesScalpAnalysisResponse:
    return FuturesScalpAnalysisResponse(
        symbol="NQ",
        side=side,
        direction=side.upper(),
        entry_price=100.0,
        stop_price=99.0 if side == "long" else 101.0,
        target_price=102.0 if side == "long" else 98.0,
        contracts=1,
        tick_value=5.0,
        point_value=20.0,
        risk_per_contract=20.0,
        reward_per_contract=40.0,
        rr_ratio=2.0,
        atr_multiple_risk=0.2,
        live_price=100.0,
        distance_entry_to_live=0.0,
        entry_verdict="attractive",
        trade_verdict="favorable",
        liquidity_score="good",
        risk_rule_violations={},
        realized_pnl_today=0.0,
        realized_loss_count_today=0,
        daily_profit_target=1200.0,
        daily_loss_limit=600.0,
        per_trade_risk_limit=200.0,
        per_trade_profit_target=400.0,
        active_contract="/NQM26",
        verdict="GO",
        entry_zone="at market",
        stop_loss="$20.00 (99.00)",
        target="$40.00 (102.00)",
        rr_ratio_display="1:2.00",
        why="test",
        watch_out_for="test",
        account_summary="test",
        session_status="ACTIVE",
        final_recommendation=final_recommendation,
        final_recommendation_comment="test",
        directional_score=directional_score,
        as_of=datetime.now(timezone.utc),
    )


def test_analyze_request_auto_selects_best_direction(monkeypatch):
    async def fake_analyze(request, _price_feed):
        if request.side == "long":
            return _response("long", "pass", 35.0)
        return _response("short", "take", 82.0)

    monkeypatch.setattr(service_module, "_analyze_request_for_side", fake_analyze)

    request = FuturesScalpIdeaRequest(symbol="NQ", account_size=100000, direction=None)
    result = asyncio.run(analyze_request(request, StaticPriceFeed({"NQ": 100.0})))

    assert isinstance(result, FuturesScalpAnalysisResponse)
    assert result.side == "short"
    assert result.direction == "SHORT"
    assert result.requested_side is None
    assert result.auto_selected is True
    assert result.evaluated_sides == ["long", "short"]
    assert result.final_recommendation == "take"


def test_analyze_request_preserves_explicit_direction(monkeypatch):
    async def fake_analyze(request, _price_feed):
        return _response(request.side or "long", "take", 70.0)

    monkeypatch.setattr(service_module, "_analyze_request_for_side", fake_analyze)

    request = FuturesScalpIdeaRequest(symbol="NQ", account_size=100000, direction="long")
    result = asyncio.run(analyze_request(request, StaticPriceFeed({"NQ": 100.0})))

    assert isinstance(result, FuturesScalpAnalysisResponse)
    assert result.side == "long"
    assert result.direction == "LONG"
    assert result.requested_side == "long"
    assert result.auto_selected is False
    assert result.evaluated_sides == ["long"]
