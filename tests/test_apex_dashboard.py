from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from futures_scalp_analyzer.apex_dashboard import (
    DISPLAY_LABELS,
    DISPLAY_CONTEXT_RULE,
    MANUAL_EXECUTION_NOTE,
    data_gate_display_state,
    decision_display_state,
    format_count,
    format_money,
    risk_display_state,
    validate_dashboard_response,
)
from futures_scalp_analyzer.apex_pipeline import MockMarketDataProvider
from futures_scalp_analyzer.price_feed import StaticPriceFeed


def test_format_money_uses_two_decimals():
    assert format_money(300) == "$300.00"
    assert format_money("2000") == "$2,000.00"


def test_format_count_uses_whole_numbers():
    assert format_count(5.0) == "5"
    assert format_count("3") == "3"


def test_dashboard_has_user_friendly_labels():
    assert DISPLAY_LABELS["session_high"] == "Session High"
    assert DISPLAY_LABELS["max_daily_loss"] == "Max Daily Loss"
    assert DISPLAY_LABELS["minimum_rr_ratio"] == "Minimum R:R"
    assert DISPLAY_LABELS["manual_execution_note"] == "Manual Execution Note"
    assert "timestamp" not in DISPLAY_LABELS


def test_decision_display_mapping():
    assert decision_display_state("LONG") == {"label": "LONG", "class_name": "state-long"}
    assert decision_display_state("SHORT") == {"label": "SHORT", "class_name": "state-short"}
    assert decision_display_state("NO TRADE") == {"label": "NO TRADE", "class_name": "state-none"}


def test_risk_blocked_display_mapping():
    assert risk_display_state("blocked") == {
        "label": "RISK GATE CLOSED",
        "class_name": "risk-blocked",
    }
    assert risk_display_state("allowed") == {"label": "RISK GATE OPEN", "class_name": "risk-allowed"}


def test_data_gate_display_mapping():
    assert data_gate_display_state("open") == {"label": "DATA GATE OPEN", "class_name": "data-allowed"}
    assert data_gate_display_state("closed") == {"label": "DATA GATE CLOSED", "class_name": "data-blocked"}


def test_validate_dashboard_response_flags_missing_fields():
    errors = validate_dashboard_response({"market_data": {}, "risk_settings": {}}, {"decision": {}})
    assert errors == ["missing context"]


def test_dashboard_route_contains_required_static_contract():
    app = create_app(StaticPriceFeed({"NQ": 101.0}))
    app.state.apex_provider = MockMarketDataProvider()
    client = TestClient(app)

    response = client.get("/apex/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Apex Scalp Engine" in body
    assert "Technical Readout" in body
    assert "Multi-Timeframe Trend" in body
    assert "multi-timeframe-trend" in body
    assert "renderMultiTimeframeTrend" in body
    assert "MTF: " in body
    assert "Quick Status" in body
    assert "quick-status" in body
    assert "renderQuickStatus" in body
    assert "font-size: 16px;" in body
    assert "font-size: 20px;" in body
    assert "font-size: 25px;" in body
    assert 'timeZone: "America/New_York"' in body
    assert 'timeZone: "UTC"' not in body
    assert "Data Stale &mdash; Verify Before Trading" in body
    assert "stale-warning" in body
    assert "data-mode" in body
    assert "provider-status" in body
    assert "DATA GATE OPEN" in body
    assert "DATA GATE CLOSED" in body
    assert "data-gate-badge" in body
    assert "mini-bullish" in body
    assert "Last Update:" in body
    assert "Price vs VWAP" in body
    assert "Decision Comment" in body
    assert "technical_readout" in body
    assert MANUAL_EXECUTION_NOTE in body
    assert DISPLAY_CONTEXT_RULE in body
    assert "Mock Data &mdash; Not Live Market Data" in body
    assert "No display-only news or social context available." in body
    assert "Session High" in body
    assert "Manual Execution Note" in body
    assert "Max Trades Per Day" in body
    assert 'const marketKeys = ["symbol", "price", "trend", "vwap", "ema9", "ema20", "rsi", "session_high", "session_low", "data_source"];' in body
    assert '<h2>Status</h2>' not in body
    assert "Updated successfully." not in body
    assert "/apex/payload/" in body
    assert "/apex/decision/" in body
    assert "RISK GATE OPEN" in body
    assert "RISK GATE CLOSED" in body
    assert "DATA GATE OPEN" in body
    assert "DATA GATE CLOSED" in body
    assert '"data_gate_status") return String(value).toLowerCase() === "open" ? "DATA GATE OPEN" : "DATA GATE CLOSED"' in body
    assert '"risk_status") return String(value).toLowerCase() === "blocked" ? "RISK GATE CLOSED" : "RISK GATE OPEN"' in body
    assert "Auto 8s" in body
