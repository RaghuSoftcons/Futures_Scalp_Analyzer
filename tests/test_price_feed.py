from __future__ import annotations

import httpx

from futures_scalp_analyzer.price_feed import SchwabQuotePriceFeed
from futures_scalp_analyzer.symbols import SUPPORTED_SYMBOLS


class MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_get_price_returns_float_on_success(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "token")

    def fake_get(url, params, headers, timeout):
        assert params["symbols"] == "/NQ"
        assert headers["Authorization"] == "Bearer token"
        return MockResponse(200, {"/NQ": {"quote": {"lastPrice": 18345.25}}})

    monkeypatch.setattr(httpx, "get", fake_get)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("NQ") == 18345.25


def test_get_price_returns_none_on_network_error(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "token")

    def fake_get(url, params, headers, timeout):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("NQ") is None


def test_get_price_refreshes_after_401(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "expired")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")

    call_count = {"quote": 0}

    def fake_get(url, params, headers, timeout):
        call_count["quote"] += 1
        if call_count["quote"] == 1:
            assert headers["Authorization"] == "Bearer expired"
            return MockResponse(401, {})
        assert headers["Authorization"] == "Bearer fresh-token"
        return MockResponse(200, {"/MNQ": {"quote": {"lastPrice": 20123.75}}})

    def fake_post(url, data, timeout):
        assert data["refresh_token"] == "refresh"
        return MockResponse(200, {"access_token": "fresh-token"})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("MNQ") == 20123.75


def test_get_price_returns_none_when_refresh_fails(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "expired")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")

    def fake_get(url, params, headers, timeout):
        return MockResponse(401, {})

    def fake_post(url, data, timeout):
        return MockResponse(500, {})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "post", fake_post)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("SIL") is None


def test_symbol_mapping_for_schwab_symbols():
    assert SUPPORTED_SYMBOLS["NQ"].schwab_symbol == "/NQ"
    assert SUPPORTED_SYMBOLS["MNQ"].schwab_symbol == "/MNQ"
    assert SUPPORTED_SYMBOLS["SIL"].schwab_symbol == "/SIL"
