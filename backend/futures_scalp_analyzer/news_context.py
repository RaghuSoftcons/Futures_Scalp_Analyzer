"""Async news and geopolitical context helpers."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup, Tag

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
    """Scrape trumpstruth.org - public archive.
    DOM is flat inside #main-body. Each post block:
      [profile link] [name link] [@handle link] [dot span] [timestamp link /statuses/N] [Original Post link]
      [post text div]
    Walk forward from each timestamp link using Tag instances only."""
    posts: list[str] = []
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout, follow_redirects=True) as client:
            resp = await client.get("https://www.trumpstruth.org/")
            if resp.status_code != 200:
                log.warning("trumpstruth.org returned %s", resp.status_code)
                return posts
            soup = BeautifulSoup(resp.text, "html.parser")
            # Find all timestamp links: [April 21, 2026, 9:23 AM](/statuses/12345)
            ts_links = soup.find_all("a", href=re.compile(r"^/statuses/\d+$"))
            log.info("trumpstruth.org: found %d status links", len(ts_links))
            for ts_link in ts_links:
                if not isinstance(ts_link, Tag):
                    continue
                time_str = ts_link.get_text(strip=True)
                if not _TS_RE.match(time_str):
                    continue
                post_dt = _parse_post_time(time_str)
                if post_dt is None:
                    continue
                # posts are newest-first; stop when older than cutoff
                if post_dt < cutoff:
                    break
                # Iterate next siblings, looking only at Tag elements
                text = None
                for sibling in ts_link.next_siblings:
                    if not isinstance(sibling, Tag):
                        continue  # skip NavigableString / text nodes
                    sibling_href = str(sibling.get("href") or "")
                    sibling_name = str(sibling.name or "")
                    # Skip 'Original Post' link (external truthsocial link)
                    if sibling_name == "a" and ("truthsocial.com" in sibling_href or "statuses" in sibling_href):
                        continue
                    # Skip profile/name links pointing to /#
                    if sibling_name == "a" and sibling_href == "/#":
                        continue
                    # If we hit the next post's timestamp link, stop
                    if sibling_name == "a" and re.match(r"^/statuses/\d+$", sibling_href):
                        break
                    # Skip profile image links and short/empty elements
                    sibling_text = sibling.get_text(separator=" ", strip=True)
                    if not sibling_text or len(sibling_text) < 5:
                        continue
                    if "@realDonaldTrump" in sibling_text:
                        continue
                    if "Donald J. Trump" in sibling_text and len(sibling_text) < 30:
                        continue
                    # This should be the post content
                    text = " ".join(sibling_text.split())
                    break
                if text:
                    posts.append(text[:280])
                if len(posts) >= 10:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("trumpstruth.org fetch failed: %s", exc)
    log.info("trumpstruth.org: collected %d posts", len(posts))
    return posts


async def get_news_context(timeout: httpx.Timeout | None = None) -> dict:
    """Return news bias, Trump posts and top headlines."""
    if timeout is None:
        timeout = httpx.Timeout(15.0)

    now = datetime.now(tz=timezone.utc)
    # Use 2-hour cutoff for Trump posts to get recent ones
    trump_cutoff = now - timedelta(hours=2)
    finnhub_cutoff = now - timedelta(hours=4)

    context: dict = _default_news_context()
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
                    published_at_raw = item.get("datetime")
                    try:
                        published_at = int(float(str(published_at_raw))) if published_at_raw is not None else 0
                    except (ValueError, TypeError):
                        published_at = 0
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


# Backward-compatible alias used by service.py
fetch_news_context = get_news_context
