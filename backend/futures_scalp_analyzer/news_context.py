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

# Free financial news RSS feeds - no API key required
_NEWS_RSS_FEEDS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://finance.yahoo.com/news/rssindex",
    "https://feeds.marketwatch.com/marketwatch/marketpulse/",
]


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


async def _fetch_trump_posts_rss(cutoff: datetime, timeout: httpx.Timeout) -> list[str]:
    """Fetch Trump posts via trumpstruth.org RSS feed (no Cloudflare challenge).

    RSS feed supports ?start_date=YYYY-MM-DD parameter.
    Each <item> has <title> (post text) and <pubDate> (RFC 2822 date).
    """
    posts: list[str] = []
    try:
        today_str = cutoff.strftime("%Y-%m-%d")
        url = f"https://trumpstruth.org/feed?start_date={today_str}&per_page=25"
        async with httpx.AsyncClient(headers=_RSS_HEADERS, timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            log.info("trumpstruth.org RSS status: %s, content-type: %s", resp.status_code, resp.headers.get("content-type", ""))
            if resp.status_code != 200:
                log.warning("trumpstruth.org RSS returned %s", resp.status_code)
                return posts
            root = ET.fromstring(resp.text)
            channel = root.find("channel")
            if channel is None:
                log.warning("trumpstruth.org RSS: no <channel> element found")
                return posts
            items = channel.findall("item")
            log.info("trumpstruth.org RSS: found %d items", len(items))
            for item in items:
                pub_date_el = item.find("pubDate")
                title_el = item.find("title")
                desc_el = item.find("description")
                if pub_date_el is None or title_el is None:
                    continue
                try:
                    pub_dt = parsedate_to_datetime(pub_date_el.text or "")
                    pub_dt = pub_dt.astimezone(timezone.utc)
                except Exception:
                    continue
                if pub_dt < cutoff:
                    continue
                raw = (desc_el.text if desc_el is not None else None) or (title_el.text or "")
                text = html.unescape(re.sub(r'<[^>]+>', '', raw)).strip()
                if not text or len(text) < 5:
                    continue
                posts.append(text)
                if len(posts) >= 10:
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("trumpstruth.org RSS fetch failed: %s", exc)
    log.info("trumpstruth.org RSS: collected %d posts", len(posts))
    return posts


async def _fetch_headlines_rss(cutoff: datetime, timeout: httpx.Timeout) -> list[str]:
    """Fetch top financial headlines from free RSS feeds - no API key required."""
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
                log.warning("News RSS %s parse error: %s", feed_url, exc)
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
                title_text = (title_el.text or "").strip()
                title_text = html.unescape(re.sub(r'<[^>]+>', '', title_text)).strip()
                if not title_text or len(title_text) < 5:
                    continue
                pub_date_el = item.find("pubDate") or item.find("published")
                if pub_date_el is not None and pub_date_el.text:
                    try:
                        pub_dt = parsedate_to_datetime(pub_date_el.text)
                        pub_dt = pub_dt.astimezone(timezone.utc)
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass
                headlines.append(title_text)
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

    # Fetch Trump posts via RSS (avoids Cloudflare block)
    trump_posts = await _fetch_trump_posts_rss(trump_cutoff, timeout)

    # Fetch financial headlines via free RSS feeds (no API key needed)
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
