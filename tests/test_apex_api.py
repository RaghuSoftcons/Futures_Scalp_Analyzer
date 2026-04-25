from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from futures_scalp_analyzer.apex_pipeline import MANUAL_EXECUTION_NOTE, MarketDataProvider, MockMarketDataProvider
from futures_scalp_analyzer.price_feed import StaticPriceFeed


def _client() -> TestClient:
    app = create_app(StaticPriceFeed({"NQ": 101.0}))
    app.state.apex_provider = MockMarketDataProvider()
    return TestClient(app)


class StaleProvider(MarketDataProvider):
    data_source = "schwab"

    def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 110.0, "timestamp": "2026-04-24T13:00:00Z"}

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict]:
        return [
            {
                "open": 100.0 + idx,
                "high": 100.5 + idx,
                "low": 99.5 + idx,
                "close": 100.0 + idx,
                "volume": 1000.0,
                "datetime": "2026-04-24T13:00:00Z",
            }
            for idx in range(30)
        ]


def _client_with_provider(provider: MarketDataProvider) -> TestClient:
    app = create_app(StaticPriceFeed({"NQ": 101.0}))
    app.state.apex_provider = provider
    return TestClient(app)


def test_apex_payload_endpoint_returns_valid_json():
    response = _client().get("/apex/payload/NQ")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"market_data", "context", "risk_settings", "risk_state", "timestamp"}
    assert body["market_data"]["symbol"] == "NQ"
    assert body["market_data"]["data_source"] == "mock"
    assert body["market_data"]["data_mode"] == "mock"
    assert body["market_data"]["provider_status"] == "connected"
    assert "last_update_time" in body["market_data"]
    assert body["market_data"]["is_stale"] is False


def test_apex_payload_endpoint_includes_required_sections():
    body = _client().get("/apex/payload/NQ").json()

    assert "market_data" in body
    assert "context" in body
    assert "risk_settings" in body
    assert "data_mode" in body["market_data"]
    assert "provider_status" in body["market_data"]
    assert "last_update_time" in body["market_data"]
    assert body["context"]["context_rule"] == "Display only. Not used in trade decisions."


def test_apex_decision_endpoint_returns_payload_and_decision():
    response = _client().get("/apex/decision/NQ")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"payload", "decision", "technical_readout", "timestamp"}
    assert "market_data" in body["payload"]
    assert "context" in body["payload"]
    assert "risk_settings" in body["payload"]
    assert body["decision"]["recommendation"] in {"LONG", "SHORT", "NO TRADE"}
    assert body["decision"]["manual_execution_note"] == MANUAL_EXECUTION_NOTE
    assert "summary" in body["technical_readout"]
    assert "price_relationships" in body["technical_readout"]


def test_apex_decision_endpoint_risk_blocked_returns_no_trade():
    body = _client().get("/apex/decision/NQ?estimated_risk=501").json()

    assert body["decision"]["recommendation"] == "NO TRADE"
    assert body["decision"]["risk_status"] == "blocked"
    assert body["decision"]["no_trade_reason"] == "risk rule violated"


def test_apex_decision_endpoint_news_social_do_not_affect_decision():
    client = _client()
    baseline = client.get("/apex/decision/NQ").json()["decision"]
    with_context = client.get(
        "/apex/decision/NQ?news_title=Breaking%20display%20headline&social_title=Display%20only%20post"
    ).json()["decision"]

    assert with_context["display_context"]["news"][0]["title"] == "Breaking display headline"
    assert with_context["display_context"]["social"][0]["title"] == "Display only post"
    assert baseline["recommendation"] == with_context["recommendation"]
    assert baseline["confidence"] == with_context["confidence"]
    assert baseline["risk_status"] == with_context["risk_status"]
    assert baseline["no_trade_reason"] == with_context["no_trade_reason"]


def test_apex_decision_endpoint_stale_data_returns_no_trade():
    body = _client_with_provider(StaleProvider()).get("/apex/decision/NQ").json()

    assert body["payload"]["market_data"]["is_stale"] is True
    assert body["payload"]["market_data"]["stale_reason"] == "market data stale"
    assert body["decision"]["recommendation"] == "NO TRADE"
    assert body["decision"]["no_trade_reason"] == "market data stale"
