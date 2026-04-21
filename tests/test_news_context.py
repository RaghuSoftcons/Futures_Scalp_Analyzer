from __future__ import annotations

import asyncio

import httpx

from futures_scalp_analyzer.news_context import _score_news_bias, fetch_news_context


class FailingAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    async def get(self, *args, **kwargs):
        del args, kwargs
        raise httpx.TimeoutException("network down")


def test_fetch_news_context_handles_external_failures(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", FailingAsyncClient)
    result = asyncio.run(fetch_news_context("NQ"))

    assert set(result.keys()) == {
        "news_available",
        "overall_bias",
        "symbol_relevant",
        "trump_posts",
        "headlines",
        "key_themes",
        "bias_note",
    }
    assert result["news_available"] is False
    assert result["trump_posts"] == []
    assert result["headlines"] == []
    assert result["overall_bias"] == "neutral"


def test_score_news_bias_bullish():
    trump_posts = [{"text": "Great trade deal and jobs boom coming"}]
    headlines = [{"headline": "Market rally surge on growth optimism", "summary": "strong economy narrative"}]

    result = _score_news_bias(trump_posts, headlines, "ES")
    assert result["overall_bias"] == "bullish"


def test_score_news_bias_bearish():
    trump_posts = [{"text": "Tariff war escalation creates crisis"}]
    headlines = [{"headline": "Inflation and rate hike fears spark crash", "summary": "market conflict concerns"}]

    result = _score_news_bias(trump_posts, headlines, "NQ")
    assert result["overall_bias"] == "bearish"

