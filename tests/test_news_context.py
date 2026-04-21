import asyncio

from futures_scalp_analyzer.news_context import fetch_news_context

def test_news_context_without_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    context = asyncio.run(fetch_news_context("NQ"))
    assert context["news_bias"] in {"bullish", "bearish", "neutral"}
    assert "top_headlines" in context
    assert "trump_posts_recent" in context
