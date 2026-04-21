"""Async news and geopolitical context helpers."""
from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)

_RSS_HEADERS = {
    "User-Agent": "FuturesScalpAnalyzer/1.0 (RSS reader; +https://github.com/RaghuSoftcons/Futures_Scalp_Analyzer)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
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
            if pub_date_el is None or title_el is None:
                continue
            try:
                pub_dt = parsedate_to_datetime(pub_date_el.text or "")
                pub_dt = pub_dt.astimezone(timezone.utc)
            except Exception:
                continue
            if pub_dt < cutoff:
                continue
            text = (title_el.text or "").strip()
            if not text or len(text) < 5:
                continue
            posts.append(text[:280])
            if len(posts) >= 10:
                break
    except Exception as exc:  # noqa: BLE001
        log.warning("trumpstruth.org RSS fetch failed: %s", exc)
    log.info("trumpstruth.org RSS: collected %d posts", len(posts))
    return posts


async def get_news_context(timeout: httpx.Timeout | None = None) -> dict:
    """Return news bias, Trump posts and top headlines."""
    if timeout is None:
        timeout = httpx.Timeout(15.0)
    now = datetime.now(tz=timezone.utc)
    trump_cutoff = now - timedelta(hours=8)
    finnhub_cutoff = now - timedelta(hours=4)
    context: dict = _default_news_context()
    top_headlines: list[str] = []

    # Fetch Trump posts via RSS (avoids Cloudflare block)
    trump_posts = await _fetch_trump_posts_rss(trump_cutoff, timeout)

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
