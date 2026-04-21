"""Async news and geopolitical context helpers."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
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


def _parse_post_time(time_str: str) -> datetime | None:
    """Parse timestamps like 'April 21, 2026, 9:23 AM' from trumpstruth.org."""
    time_str = time_str.strip()
    for fmt in (
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y, %I:%M%p",
        "%B %-d, %Y, %I:%M %p",
    ):
        try:
            dt = datetime.strptime(time_str, fmt)
            # Site shows Eastern time - treat as UTC-4 (EDT)
            return dt.replace(tzinfo=timezone(timedelta(hours=-4)))
        except ValueError:
            continue
    return None


async def _fetch_trump_posts_from_archive(cutoff: datetime, timeout: httpx.Timeout) -> list[str]:
    """Scrape trumpstruth.org for recent Trump posts - reliable public archive."""
    posts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get("https://www.trumpstruth.org/")
            log.info("trumpstruth.org status: %s", resp.status_code)
            if resp.status_code != 200:
                log.warning("trumpstruth.org returned %s", resp.status_code)
                return posts

            soup = BeautifulSoup(resp.text, "html.parser")

            # Each post is in a div/article. Find all post containers.
            # The site shows: author name, @handle, date string, then post content.
            # Look for elements containing the timestamp pattern
            for article in soup.find_all(["article", "div"], class_=re.compile(r"post|status|truth|card", re.I)):
                # Try to extract timestamp
                time_el = article.find(["time", "span", "p"], string=re.compile(r"\w+ \d+, \d{4}"))
                if not time_el:
                    # Fallback: search for date-like text in any element
                    for el in article.find_all(string=re.compile(r"\w+ \d+, \d{4}, \d+:\d+ [AP]M")):
                        time_el = el
                        break

                post_time = None
                if time_el:
                    raw_time = time_el.get_text(strip=True) if hasattr(time_el, "get_text") else str(time_el)
                    post_time = _parse_post_time(raw_time)

                if post_time and post_time < cutoff:
                    log.debug("Post at %s is before cutoff %s, stopping", post_time, cutoff)
                    break

                # Extract post content - get all text from article, remove navigation/header noise
                content_el = article.find(["p", "div"], class_=re.compile(r"content|body|text|message", re.I))
                if not content_el:
                    # Use the full article text but strip out the header parts
                    content_el = article

                raw_text = content_el.get_text(separator=" ", strip=True)
                # Remove common UI text noise
                raw_text = re.sub(r"Donald J\.?\s*Trump", "", raw_text)
                raw_text = re.sub(r"@realDonaldTrump", "", raw_text)
                raw_text = re.sub(r"\w+ \d+, \d{4}, \d+:\d+ [AP]M", "", raw_text)
                raw_text = re.sub(r"Original Post", "", raw_text)
                raw_text = " ".join(raw_text.split())

                if raw_text and len(raw_text) > 10:
                    posts.append(raw_text[:220])

            log.info("trumpstruth.org posts found in window: %d", len(posts))
    except Exception as exc:  # noqa: BLE001
        log.warning("trumpstruth.org scrape failed: %s", exc)
    return posts


async def fetch_news_context(symbol: str) -> dict:
    del symbol
    context = _default_news_context()
    timeout = httpx.Timeout(10.0)

    now = datetime.now(timezone.utc)
    trump_cutoff = now - timedelta(hours=8)
    finnhub_cutoff = now - timedelta(hours=2)

    trump_posts: list[str] = []
    top_headlines: list[str] = []

    # Primary: scrape public archive (not blocked by Cloudflare)
    trump_posts = await _fetch_trump_posts_from_archive(trump_cutoff, timeout)

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
