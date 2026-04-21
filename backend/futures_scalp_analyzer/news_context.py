"""Async news and geopolitical context helpers."""
from __future__ import annotations

import logging
import os
import re
import html
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)

_RSS_HEADERS = {
    "User-Agent": "FuturesScalpAnalyzer/1.0 (RSS reader; +https://github.com/RaghuSoftcons/Futures_Scalp_Analyzer)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Market-moving news RSS feeds - focused on Fed, economy, rates, earnings, geopolitics
# No API key required. Fetched server-side (Railway), so CORS does not apply.
_NEWS_RSS_FEEDS = [
    "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "https://www.cnbc.com/id/15839135/device/rss/rss.html",
    "https://feeds.apnews.com/rss/apf-business",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.npr.org/1017/rss.xml",
]

_BULLISH_TERMS = (
    "rate cut", "rate cuts", "dovish", "stimulus", "rally", "surge", "beat",
    "better than expected", "strong jobs", "ceasefire", "trade deal", "deal reached",
    "pause tariffs", "earnings beat", "record high", "soft landing",
)
_BEARISH_TERMS = (
    "rate hike", "rate hikes", "hawkish", "selloff", "sell-off", "crash",
    "recession", "tariff", "tariffs", "sanction", "sanctions", "war", "conflict",
    "hot inflation", "miss", "worse than expected", "layoffs", "shutdown",
    "default", "downgrade", "fed raises", "unemployment rises",
)


def _default_news_context() -> dict:
    return {
        "news_bias": "neutral",
        "news_bias_note": "No material high-confidence news signals detected.",
        "trump_posts_recent": [],
        "trump_posts_count": 0,
        "top_headlines": [],
    }


def _infer_news_bias(headlines: list[str], trump_posts: list[str]) -> tuple[str, str]:
    score = 0
    headline_titles = [h.split(" -- ")[0] if " -- " in h else h for h in headlines]
    corpus = [*headline_titles, *trump_posts]
    for line in corpus:
        lowered = line.lower()
        if any(term in lowered for term in _BULLISH_TERMS):
            score += 1
        if any(term in lowered for term in _BEARISH_TERMS):
            score -= 1
    if score > 0:
        return "bullish", "News flow leans risk-on across recent headlines/posts."
    if score < 0:
        return "bearish", "News flow leans risk-off across recent headlines/posts."
    return "neutral", "News flow is mixed or low-signal."


async def _fetch_trump_posts_rss(cutoff: datetime, timeout: httpx.Timeout) -> list[str]:
    """Fetch Trump posts via trumpstruth.org RSS feed."""
    posts: list[str] = []
    try:
        today_str = cutoff.strftime("%Y-%m-%d")
        url = f"https://trumpstruth.org/feed?start_date={today_str}&per_page=25"
        async with httpx.AsyncClient(headers=_RSS_HEADERS, timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            log.info("trumpstruth.org RSS status: %s", resp.status_code)
            if resp.status_code != 200:
                return posts
            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                return posts
            for item in channel.findall("item"):
                pub_date_el = item.find("pubDate")
                title_el = item.find("title")
                desc_el = item.find("description")
                if pub_date_el is None or title_el is None:
                    continue
                try:
                    pub_dt = parsedate_to_datetime(pub_date_el.text or "").astimezone(timezone.utc)
                except Exception:
                    continue
                if pub_dt < cutoff:
                    continue
                raw = (desc_el.text if desc_el is not None else None) or (title_el.text or "")
                text = html.unescape(re.sub(r'<[^>]+>', '', raw)).strip()
                if text and len(text) >= 5:
                    posts.append(text)
                if len(posts) >= 10:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("trumpstruth.org RSS fetch failed: %s", exc)
    log.info("trumpstruth.org RSS: collected %d posts", len(posts))
    return posts


def _is_article_url(url: str) -> bool:
    """Return True if url looks like a specific article (has a path beyond just /)."""
    if not url or not url.startswith("http"):
        return False
    # Strip protocol and split on /
    try:
        path = url.split("/", 3)  # ['https:', '', 'domain.com', 'rest/of/path']
        if len(path) < 4:
            return False
        rest = path[3].strip("/")
        return len(rest) > 0
    except Exception:
        return False


async def _fetch_headlines_rss(cutoff: datetime, timeout: httpx.Timeout) -> list[str]:
    """Fetch top market-moving headlines with article URLs.

    Each entry is formatted as: "Headline title -- https://article-url"
    so the GPT can display the title and a clickable link to read more.
    """
    headlines: list[str] = []
    for feed_url in _NEWS_RSS_FEEDS:
        if len(headlines) >= 5:
            break
        try:
            async with httpx.AsyncClient(headers=_RSS_HEADERS, timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(feed_url)
                log.info("News RSS %s status: %s", feed_url, resp.status_code)
                if resp.status_code != 200:
                    continue
                try:
                    root = ET.fromstring(resp.text)
                except ET.ParseError as exc:
                    log.warning("News RSS parse error: %s", exc)
                    continue
                channel = root.find("channel")
                if channel is not None:
                    items = channel.findall("item")
                else:
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    items = root.findall("atom:entry", ns) or root.findall("entry")
                for item in items:
                    if len(headlines) >= 5:
                        break
                    title_el = item.find("title")
                    if title_el is None:
                        continue
                    title_text = html.unescape(re.sub(r'<[^>]+>', '', title_el.text or "")).strip()
                    if not title_text or len(title_text) < 5:
                        continue
                    # Extract article URL - try <link> first, then <guid> as fallback
                    article_url = ""
                    link_el = item.find("link")
                    if link_el is not None:
                        candidate = (link_el.text or "").strip() or link_el.get("href", "").strip()
                        if _is_article_url(candidate):
                            article_url = candidate
                    # Fallback: <guid isPermaLink="true"> often holds the real article URL
                    if not article_url:
                        guid_el = item.find("guid")
                        if guid_el is not None:
                            is_perma = guid_el.get("isPermaLink", "true").lower() != "false"
                            candidate = (guid_el.text or "").strip()
                            if is_perma and _is_article_url(candidate):
                                article_url = candidate
                    # Check pubDate freshness
                    pub_date_el = item.find("pubDate") or item.find("published")
                    if pub_date_el is not None and pub_date_el.text:
                        try:
                            pub_dt = parsedate_to_datetime(pub_date_el.text).astimezone(timezone.utc)
                            if pub_dt < cutoff:
                                continue
                        except Exception:
                            pass
                    entry = f"{title_text} -- {article_url}" if article_url else title_text
                    headlines.append(entry)
        except Exception as exc:  # noqa: BLE001
            log.warning("News RSS fetch failed for %s: %s", feed_url, exc)
    log.info("News RSS: collected %d headlines", len(headlines))
    return headlines


async def get_news_context(timeout: httpx.Timeout | None = None) -> dict:
    """Return news bias, Trump posts and top headlines."""
    if timeout is None:
        timeout = httpx.Timeout(15.0)
    now = datetime.now(tz=timezone.utc)
    trump_cutoff = now - timedelta(hours=8)
    news_cutoff = now - timedelta(hours=4)
    context: dict = _default_news_context()

    trump_posts = await _fetch_trump_posts_rss(trump_cutoff, timeout)
    top_headlines = await _fetch_headlines_rss(news_cutoff, timeout)

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
