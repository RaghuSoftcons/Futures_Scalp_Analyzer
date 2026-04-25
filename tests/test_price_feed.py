from __future__ import annotations

import base64

import httpx

from futures_scalp_analyzer import price_feed as price_feed_module
from futures_scalp_analyzer.price_feed import SchwabQuotePriceFeed
from futures_scalp_analyzer.symbols import SUPPORTED_SYMBOLS


class MockResponse:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self) -> dict:
        return self._payload


def test_get_price_returns_float_on_success(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "token")

    def fake_get(url, headers, timeout):
        if "%2FES,%2FNQ" in url:
            return MockResponse(200, {root: {"quote": {"futureActiveSymbol": f"/{root.strip('/')}M26"}} for root in price_feed_module.ROOT_SYMBOLS})
        assert url.endswith("symbols=%2FNQM26")
        assert headers["Authorization"] == "Bearer token"
        return MockResponse(200, {"/NQM26": {"quote": {"lastPrice": 18345.25}}})

    monkeypatch.setattr(price_feed_module.httpx, "get", fake_get)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("NQ") == 18345.25


def test_get_price_returns_none_on_network_error(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "token")

    def fake_get(url, headers, timeout):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(price_feed_module.httpx, "get", fake_get)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("NQ") is None


def test_get_price_refreshes_after_401(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "expired")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")

    call_count = {"quote": 0}

    def fake_get(url, headers, timeout):
        if "%2FES,%2FNQ" in url:
            return MockResponse(200, {root: {"quote": {"futureActiveSymbol": f"/{root.strip('/')}M26"}} for root in price_feed_module.ROOT_SYMBOLS})
        call_count["quote"] += 1
        if call_count["quote"] == 1:
            assert headers["Authorization"] == "Bearer expired"
            return MockResponse(401, {})
        assert headers["Authorization"] == "Bearer fresh-token"
        return MockResponse(200, {"/MNQM26": {"quote": {"lastPrice": 20123.75}}})

    def fake_post(url, headers, data, timeout):
        expected_credentials = base64.b64encode(b"client-id:client-secret").decode()
        assert headers["Authorization"] == f"Basic {expected_credentials}"
        assert data["refresh_token"] == "refresh"
        return MockResponse(200, {"access_token": "fresh-token"})

    monkeypatch.setattr(price_feed_module.httpx, "get", fake_get)
    monkeypatch.setattr(price_feed_module.httpx, "post", fake_post)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("MNQ") == 20123.75


def test_get_price_returns_none_when_refresh_fails(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "expired")
    monkeypatch.setenv("SCHWAB_REFRESH_TOKEN", "refresh")
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "client-id")
    monkeypatch.setenv("SCHWAB_CLIENT_SECRET", "client-secret")

    def fake_get(url, headers, timeout):
        if "%2FES,%2FNQ" in url:
            return MockResponse(200, {root: {"quote": {"futureActiveSymbol": f"/{root.strip('/')}M26"}} for root in price_feed_module.ROOT_SYMBOLS})
        return MockResponse(401, {})

    def fake_post(url, headers, data, timeout):
        return MockResponse(500, {})

    monkeypatch.setattr(price_feed_module.httpx, "get", fake_get)
    monkeypatch.setattr(price_feed_module.httpx, "post", fake_post)

    feed = SchwabQuotePriceFeed()
    assert feed.get_price("SIL") is None


def test_symbol_mapping_for_schwab_symbols():
    assert SUPPORTED_SYMBOLS["NQ"].schwab_symbol == "/NQ"
    assert SUPPORTED_SYMBOLS["MNQ"].schwab_symbol == "/MNQ"
    assert SUPPORTED_SYMBOLS["SIL"].schwab_symbol == "/SIL"


def test_get_price_history_allows_thirty_minute_bars(monkeypatch):
    monkeypatch.setenv("SCHWAB_ACCESS_TOKEN", "token")

    def fake_get(url, headers, timeout):
        if "quotes?symbols=" in url:
            return MockResponse(200, {root: {"quote": {"futureActiveSymbol": f"/{root.strip('/')}M26"}} for root in price_feed_module.ROOT_SYMBOLS})
        assert "frequencyType=minute" in url
        assert "frequency=30" in url
        assert headers["Authorization"] == "Bearer token"
        return MockResponse(
            200,
            {
                "candles": [
                    {
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.0,
                        "close": 100.5,
                        "volume": 10,
                        "datetime": 1_800_000_000_000,
                    }
                ]
            },
        )

    monkeypatch.setattr(price_feed_module.httpx, "get", fake_get)

    feed = SchwabQuotePriceFeed()
    bars = feed.get_price_history("NQ", "minute", 30, "day", 1)

    assert bars == [
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 10.0,
            "datetime": 1_800_000_000_000,
        }
    ]
