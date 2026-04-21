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

# Matches e.g. "April 21, 2026, 9:23 AM" or "April 3, 2026, 11:05 PM"
_TS_RE = re.compile(r"(\w+ \d{1,2}, \d{4}, \d{1,2}:\d{2} [AP]M)")


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
    for fmt in ("%B %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M%p"):
        try:
            dt = datetime.strptime(time_str, fmt)
            # trumpstruth.org displays Eastern time
            return dt.replace(tzinfo=timezone(timedelta(hours=-4)))
        except ValueError:
            continue
    return None


async def _fetch_trump_posts_from_archive(cutoff: datetime, timeout: httpx.Timeout) -> list[str]:
    """Scrape trumpstruth.org - reliable public archive, not blocked by Cloudflare.

    Page structure (confirmed via live DOM inspection):
      - Timestamp links: <a href="/statuses/{id}">April 21, 2026, 9:23 AM</a>
      - Post content: the next sibling <div> or <p> after the timestamp link's
        parent header block.
    Strategy: find all <a> whose href matches /statuses/\d+ AND whose text
    matches a timestamp, parse the time, then walk siblings to collect post text.
    """
    posts: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get("https://www.trumpstruth.org/")
            log.info("trumpstruth.org status: %s", resp.status_code)
            if resp.status_code != 200:
                log.warning("trumpstruth.org returned %s", resp.status_code)
                return posts

            soup = BeautifulSoup(resp.text, "html.parser")

            # Find all timestamp anchor links: <a href="/statuses/NNN">...
            ts_links = soup.find_all(
                "a",
                href=re.compile(r"^/statuses/\d+$"),
                string=_TS_RE,
            )
            log.info("trumpstruth.org timestamp links found: %d", len(ts_links))

            for ts_link in ts_links:
                raw_time = ts_link.get_text(strip=True)
                post_time = _parse_post_time(raw_time)

                if post_time and post_time < cutoff:
                    log.debug("Post at %s is before cutoff, stopping", post_time)
                    break

                # Walk up to the parent block (usually 2-3 levels up)
                # then find the next sibling that contains the post text
                container = ts_link.parent
                for _ in range(4):  # walk up to 4 levels
                    if container is None:
                        break
                    # The content sibling is typically a div/p that comes
                    # after the header row containing the timestamp link
                    sibling = container.find_next_sibling(["div", "p"])
                    if sibling:
                        text = sibling.get_text(separator=" ", strip=True)
                        # Skip if it's another header (contains @realDonaldTrump)
                        if "@realDonaldTrump" not in text and len(text) > 10:
                            text = " ".join(text.split())
                            posts.append(text[:220])
                            break
                    container = container.parent

            log.info("trumpstruth.org posts parsed: %d", len(posts))
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

    # Primary: scrape public archive (bypasses Cloudflare block on Truth Social)
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
