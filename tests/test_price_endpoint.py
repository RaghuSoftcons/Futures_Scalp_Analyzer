from __future__ import annotations

import base64
import importlib

import httpx
from fastapi.testclient import TestClient

import app as app_module


class MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _reload_app_module(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "access-token")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh-token")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")
    return importlib.reload(app_module)


def test_price_endpoint_returns_quote(monkeypatch):
    module = _reload_app_module(monkeypatch)

    def fake_get(url, headers, timeout):
        assert url.endswith("/marketdata/v1/quotes?symbols=%2FESM26")
        assert headers["Authorization"] == "Bearer access-token"
        return MockResponse(
            200,
            {
                "/ESM26": {
                    "quote": {
                        "lastPrice": 7143.25,
                        "bidPrice": 7143.0,
                        "askPrice": 7143.5,
                        "mark": 7143.25,
                        "quoteTime": 1776693600000,
                    }
                }
            },
        )

    monkeypatch.setattr(module.httpx, "get", fake_get)

    client = TestClient(module.app)
    response = client.get("/price/ES")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "ES",
        "schwab_symbol": "/ESM26",
        "last": 7143.25,
        "bid": 7143.0,
        "ask": 7143.5,
        "mark": 7143.25,
        "timestamp": "2026-04-20T14:00:00Z",
        "token_refreshed": False,
    }


def test_price_endpoint_refreshes_on_401(monkeypatch):
    module = _reload_app_module(monkeypatch)
    quote_calls = {"count": 0}

    def fake_get(url, headers, timeout):
        quote_calls["count"] += 1
        if quote_calls["count"] == 1:
            assert url.endswith("/marketdata/v1/quotes?symbols=%2FNQM26")
            assert headers["Authorization"] == "Bearer access-token"
            return MockResponse(401, {})
        assert url.endswith("/marketdata/v1/quotes?symbols=%2FNQM26")
        assert headers["Authorization"] == "Bearer refreshed-token"
        return MockResponse(
            200,
            {
                "/NQM26": {
                    "quote": {
                        "lastPrice": 20345.25,
                        "bidPrice": 20345.0,
                        "askPrice": 20345.5,
                        "mark": 20345.25,
                        "timestamp": "2026-04-20T14:00:00Z",
                    }
                }
            },
        )

    def fake_post(url, headers, data, timeout):
        expected_credentials = base64.b64encode(b"client-id:client-secret").decode()
        assert headers["Authorization"] == f"Basic {expected_credentials}"
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "refresh-token"
        return MockResponse(200, {"access_token": "refreshed-token"})

    monkeypatch.setattr(module.httpx, "get", fake_get)
    monkeypatch.setattr(module.httpx, "post", fake_post)

    client = TestClient(module.app)
    response = client.get("/price/NQ")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NQ"
    assert body["schwab_symbol"] == "/NQM26"
    assert body["last"] == 20345.25
    assert body["token_refreshed"] is True


def test_price_endpoint_returns_error_payload_on_network_error(monkeypatch):
    module = _reload_app_module(monkeypatch)

    def fake_get(url, headers, timeout):
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(module.httpx, "get", fake_get)

    client = TestClient(module.app)
    response = client.get("/price/MNQ")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "MNQ"
    assert body["error"] == "quote_fetch_error"
    assert "network down" in body["detail"]
