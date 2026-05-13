import asyncio

from futures_scalp_analyzer.news_context import fetch_news_context


def test_news_context_without_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    context = asyncio.run(fetch_news_context())
    assert context["news_bias"] in {"bullish", "bearish", "neutral"}
    assert "top_headlines" in context
    assert "top_headlines_detailed" in context
    assert "trump_posts_recent" in context
    assert "trump_posts_recent_detailed" in context


def test_news_context_preserves_truth_social_urls(monkeypatch):
    async def fake_posts(*args, **kwargs):
        return [
            {
                "text": "Policy statement. Second sentence. Third sentence.",
                "url": "https://truthsocial.com/@realDonaldTrump/posts/1234567890",
                "published_at": "2026-05-12T18:00:00Z",
            }
        ]

    async def fake_headlines(*args, **kwargs):
        return [
            {
                "title": "Fed headline",
                "summary": "Officials said inflation cooled. Futures traders repriced cuts. Extra sentence.",
                "url": "https://example.com/fed-headline",
                "published_at": "2026-05-12T17:45:00Z",
            }
        ]

    monkeypatch.setattr("futures_scalp_analyzer.news_context._fetch_trump_posts_rss", fake_posts)
    monkeypatch.setattr("futures_scalp_analyzer.news_context._fetch_headlines_rss", fake_headlines)

    context = asyncio.run(fetch_news_context())

    assert context["trump_posts_recent_detailed"][0]["url"] == "https://truthsocial.com/@realDonaldTrump/posts/1234567890"
    assert context["trump_posts_recent"][0] == (
        "Policy statement. Second sentence. -- https://truthsocial.com/@realDonaldTrump/posts/1234567890"
    )
    assert context["top_headlines_detailed"][0]["url"] == "https://example.com/fed-headline"
    assert context["top_headlines_detailed"][0]["summary"] == "Officials said inflation cooled. Futures traders repriced cuts. Extra sentence."
    assert context["top_headlines"][0] == "Fed headline. Officials said inflation cooled. -- https://example.com/fed-headline"
