"""Async news and geopolitical context helpers."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

TRUMP_ACCOUNT_ID = "107780257626128497"

# Browser-like User-Agent to avoid being blocked by Truth Social
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


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
    timeout = httpx.Timeout(8.0)

    now = datetime.now(timezone.utc)
    # Extended to 8 hours to catch posts that might be just outside the old 4-hour window
    trump_cutoff = now - timedelta(hours=8)
    finnhub_cutoff = now - timedelta(hours=2)

    trump_posts: list[str] = []
    top_headlines: list[str] = []

    # Build headers - add Bearer token if available
    truth_headers = dict(_HEADERS)
    truth_token = os.getenv("TRUTH_SOCIAL_TOKEN")
    if truth_token:
        truth_headers["Authorization"] = f"Bearer {truth_token}"

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=truth_headers, follow_redirects=True) as client:
            truth_url = (
                f"https://truthsocial.com/api/v1/accounts/{TRUMP_ACCOUNT_ID}/statuses"
                "?limit=40&exclude_replies=true"
            )
            truth_response = await client.get(truth_url)
            log.info("Truth Social status: %s", truth_response.status_code)
            if truth_response.status_code == 200:
                payload = truth_response.json()
                log.info("Truth Social posts returned: %d", len(payload))
                for post in payload:
                    created_at = post.get("created_at")
                    content = str(post.get("content") or "")
                    if not created_at or not content:
                        continue
                    post_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    log.debug("Post time: %s, cutoff: %s", post_time, trump_cutoff)
                    if post_time >= trump_cutoff:
                        compact = " ".join(content.replace("\n\n", " ").replace("\n", " ").split())
                        if compact:
                            trump_posts.append(compact[:220])
            else:
                log.warning(
                    "Truth Social returned %s: %s",
                    truth_response.status_code,
                    truth_response.text[:200],
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("Truth Social fetch failed: %s", exc)
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
        except Exception as exc:  # noqa: BLE001
            log.warning("Finnhub fetch failed: %s", exc)
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
