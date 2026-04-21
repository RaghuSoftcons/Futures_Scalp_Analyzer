"""Async news and geopolitical context helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

TRUMP_ACCOUNT_ID = "107780257626128497"


def _default_news_context() -> dict:
    return {
        "news_bias": "neutral",
        "news_bias_note": "No material high-confidence news signals detected.",
        "trump_posts_recent": [],
        "trump_posts_count": 0,
        "top_headlines": [],
    }


def _infer_news_bias(headlines: list[str], trump_posts: list[str]) -> tuple[str, str]:
    positive_terms = ("rally", "surge", "deal", "cut", "cooling inflation", "dovish", "stimulus")
    negative_terms = ("selloff", "war", "tariff", "hawkish", "hot inflation", "shutdown", "sanction")
    score = 0
    corpus = [*headlines, *trump_posts]
    for line in corpus:
        lowered = line.lower()
        if any(term in lowered for term in positive_terms):
            score += 1
        if any(term in lowered for term in negative_terms):
            score -= 1

    if score > 0:
        return "bullish", "News flow leans risk-on across recent headlines/posts."
    if score < 0:
        return "bearish", "News flow leans risk-off across recent headlines/posts."
    return "neutral", "News flow is mixed or low-signal."


async def fetch_news_context(symbol: str) -> dict:
    del symbol
    context = _default_news_context()
    timeout = httpx.Timeout(5.0)

    now = datetime.now(timezone.utc)
    trump_cutoff = now - timedelta(hours=4)
    finnhub_cutoff = now - timedelta(hours=2)

    trump_posts: list[str] = []
    top_headlines: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            truth_url = f"https://truthsocial.com/api/v1/accounts/{TRUMP_ACCOUNT_ID}/statuses?limit=20"
            truth_response = await client.get(truth_url)
            if truth_response.status_code == 200:
                payload = truth_response.json()
                for post in payload:
                    created_at = post.get("created_at")
                    content = str(post.get("content") or "")
                    if not created_at or not content:
                        continue
                    post_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if post_time >= trump_cutoff:
                        compact = " ".join(content.replace("<p>", " ").replace("</p>", " ").split())
                        if compact:
                            trump_posts.append(compact[:220])
    except Exception:
        trump_posts = []

    finnhub_key = os.getenv("FINNHUB_API_KEY")
    if finnhub_key:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    "https://finnhub.io/api/v1/news",
                    params={"category": "general", "token": finnhub_key},
                )
                if response.status_code == 200:
                    for item in response.json():
                        headline = str(item.get("headline") or "").strip()
                        published_at = int(item.get("datetime") or 0)
                        if not headline or published_at <= 0:
                            continue
                        published_dt = datetime.fromtimestamp(published_at, tz=timezone.utc)
                        if published_dt >= finnhub_cutoff:
                            top_headlines.append(headline)
                        if len(top_headlines) >= 5:
                            break
        except Exception:
            top_headlines = []

    news_bias, news_bias_note = _infer_news_bias(top_headlines, trump_posts)
    context.update(
        {
            "news_bias": news_bias,
            "news_bias_note": news_bias_note,
            "trump_posts_recent": trump_posts[:5],
            "trump_posts_count": len(trump_posts),
            "top_headlines": top_headlines[:5],
        }
    )
    return context
