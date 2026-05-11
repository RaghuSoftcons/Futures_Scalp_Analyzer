from __future__ import annotations

import base64
from fastapi.testclient import TestClient

from app import create_app
from futures_scalp_analyzer import price_feed as price_feed_module
from futures_scalp_analyzer.price_feed import SchwabQuotePriceFeed


class MockResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self) -> dict:
        return self._payload


def _make_test_client(monkeypatch, fake_get, fake_post=None) -> TestClient:
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(price_feed_module.httpx, "get", fake_get)
    if fake_post is not None:
        monkeypatch.setattr(price_feed_module.httpx, "post", fake_post)
    app = create_app(SchwabQuotePriceFeed())
    return TestClient(app)


def test_price_endpoint_returns_quote(monkeypatch):
    def fake_get(url, headers, timeout):
        if "%2FES,%2FNQ" in url:
            return MockResponse(200, {root: {"quote": {"futureActiveSymbol": f"/{root.strip('/')}M26"}} for root in price_feed_module.ROOT_SYMBOLS})
        assert url.endswith("/marketdata/v1/quotes?symbols=%2FESM26")
        return MockResponse(200, {"/ESM26": {"quote": {"lastPrice": 7143.25, "bidPrice": 7143.0, "askPrice": 7143.5, "mark": 7143.25, "quoteTime": 1776693600000}}})

    client = _make_test_client(monkeypatch, fake_get)
    response = client.get("/price/ES")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "symbol": "ES",
        "root": "/ES",
        "active_contract": "/ESM26",
        "price": 7143.25,
        "source": "schwab_live",
        "last": 7143.25,
        "bid": 7143.0,
        "ask": 7143.5,
        "mark": 7143.25,
        "timestamp": "2026-04-20T14:00:00Z",
        "token_refreshed": False,
        "market_status": body["market_status"],
        "is_market_open": body["is_market_open"],
        "is_live": False,
        "quote_age_seconds": body["quote_age_seconds"],
    }
    assert body["market_status"] in {"stale", "market_closed"}
    assert isinstance(body["quote_age_seconds"], int)


def test_price_endpoint_refreshes_on_401(monkeypatch):
    quote_calls = {"count": 0}

    def fake_get(url, headers, timeout):
        if "%2FES,%2FNQ" in url:
            return MockResponse(200, {root: {"quote": {"futureActiveSymbol": f"/{root.strip('/')}M26"}} for root in price_feed_module.ROOT_SYMBOLS})
        quote_calls["count"] += 1
        if quote_calls["count"] == 1:
            return MockResponse(401, {})
        assert headers["Authorization"] == "Bearer refreshed-token"
        return MockResponse(200, {"/NQM26": {"quote": {"lastPrice": 20345.25, "bidPrice": 20345.0, "askPrice": 20345.5, "mark": 20345.25, "timestamp": "2026-04-20T14:00:00Z"}}})

    def fake_post(url, headers, data, timeout):
        expected_credentials = base64.b64encode(b"client-id:client-secret").decode()
        assert headers["Authorization"] == f"Basic {expected_credentials}"
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "refresh-token"
        return MockResponse(200, {"access_token": "refreshed-token"})

    client = _make_test_client(monkeypatch, fake_get, fake_post)
    response = client.get("/price/NQ")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NQ"
    assert body["active_contract"] == "/NQM26"
    assert body["price"] == 20345.25
    assert body["token_refreshed"] is True
    assert body["market_status"] in {"live", "stale", "market_closed"}


def test_price_endpoint_reports_closed_market_for_weekend_quote(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")

    monkeypatch.setattr(price_feed_module.httpx, "get", lambda url, headers, timeout: MockResponse(200, {}))
    feed = SchwabQuotePriceFeed()
    monkeypatch.setattr(
        feed,
        "get_quote_details",
        lambda symbol: {
            "root": "/NQ",
            "active_contract": "/NQM26",
            "last": 29333.75,
            "bid": 29331.5,
            "ask": 29343.25,
            "mark": 29333.75,
            "timestamp": "2026-05-08T21:00:00.068000Z",
            "token_refreshed": False,
            "source": "schwab_broker",
        },
    )

    app = create_app(feed)
    client = TestClient(app)

    response = client.get("/price/NQ")

    assert response.status_code == 200
    body = response.json()
    assert body["active_contract"] == "/NQM26"
    assert body["market_status"] in {"stale", "market_closed"}
    assert body["is_live"] is False
    assert isinstance(body["quote_age_seconds"], int)


def test_price_endpoint_returns_error_payload_on_network_error(monkeypatch):
    def fake_get(url, headers, timeout):
        raise price_feed_module.httpx.ConnectError("network down")

    client = _make_test_client(monkeypatch, fake_get)
    response = client.get("/price/MNQ")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "MNQ"
    assert body["error"] == "quote_unavailable"
