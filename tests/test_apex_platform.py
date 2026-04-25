from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from futures_scalp_analyzer.apex import build_accountability_status
from futures_scalp_analyzer.models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest


def test_apex_status_declares_manual_execution_only():
    client = TestClient(create_app())

    response = client.get("/apex/status")

    assert response.status_code == 200
    body = response.json()
    assert body["platform"] == "Apex Scalp Engine"
    assert body["execution_mode"] == "manual_only"
    assert body["order_routing_enabled"] is False
    assert body["news_decision_policy"] == "display_only"
    assert "No live orders" in body["manual_execution_notice"]


def test_accountability_status_identifies_tagged_requests():
    assert build_accountability_status("trader-1", None) == "identified"
    assert build_accountability_status(None, "plan-1") == "identified"
    assert build_accountability_status(None, None) == "anonymous"


def test_analysis_response_defaults_to_apex_guardrails():
    response = FuturesScalpAnalysisResponse(
        symbol="NQ",
        side="long",
        direction="LONG",
        entry_verdict="attractive",
        trade_verdict="favorable",
        liquidity_score="good",
        verdict="GO",
        entry_zone="at market",
        stop_loss="$20.00 (99.00)",
        target="$40.00 (102.00)",
        rr_ratio_display="1:2.00",
        why="test",
        watch_out_for="test",
        account_summary="test",
        session_status="ACTIVE",
        final_recommendation="take",
        final_recommendation_comment="test",
    )

    assert response.platform == "Apex Scalp Engine"
    assert response.execution_mode == "manual_only"
    assert response.order_routing_enabled is False
    assert response.news_decision_policy == "display_only"


def test_request_accepts_optional_accountability_context():
    request = FuturesScalpIdeaRequest(
        trader_id="trader-42",
        trade_plan_id="plan-open-drive",
        symbol="NQ",
        direction="long",
        account_size=100000,
    )

    assert request.trader_id == "trader-42"
    assert request.trade_plan_id == "plan-open-drive"
