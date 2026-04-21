"""News and geopolitical context helpers for futures bias scoring.

Optional environment variables:
- FINNHUB_API_KEY: Enables Finnhub headline enrichment. If missing, news fetch is skipped.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any

import httpx

USER_AGENT = {"User-Agent": "FuturesScalpAnalyzer/1.0"}
TRUTH_SOCIAL_LOOKUP_URL = "https://truthsocial.com/api/v1/accounts/lookup?acct=realDonaldTrump"
TRUTH_SOCIAL_POSTS_URL = "https://truthsocial.com/api/v1/accounts/{account_id}/statuses?limit=5"
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news?category=general&token={api_key}"

BULLISH_KEYWORDS = [
    "deal",
    "agreement",
    "cut rates",
    "stimulus",
    "ceasefire",
    "pause tariffs",
    "trade deal",
    "strong economy",
    "growth",
    "jobs",
    "hire",
    "boom",
    "rally",
    "surge",
]
BEARISH_KEYWORDS = [
    "tariff",
    "sanction",
    "war",
    "conflict",
    "inflation",
    "rate hike",
    "recession",
    "crash",
    "ban",
    "escalat",
    "attack",
    "default",
    "crisis",
    "shutdown",
]

SYMBOL_KEYWORDS: dict[str, list[str]] = {
    "ES": ["stock", "market", "s&p", "equity", "wall street", "economy", "tariff"],
    "MES": ["stock", "market", "s&p", "equity", "wall street", "economy", "tariff"],
    "SPX": ["stock", "market", "s&p", "equity", "wall street", "economy", "tariff"],
    "NQ": ["tech", "nasdaq", "ai", "semiconductor", "chip", "apple", "nvidia", "microsoft"],
    "MNQ": ["tech", "nasdaq", "ai", "semiconductor", "chip", "apple", "nvidia", "microsoft"],
    "GC": ["gold", "inflation", "dollar", "fed", "rates", "safe haven", "geopolit"],
    "MGC": ["gold", "inflation", "dollar", "fed", "rates", "safe haven", "geopolit"],
    "CL": ["oil", "opec", "energy", "crude", "iran", "russia", "pipeline", "venezuela"],
    "MCL": ["oil", "opec", "energy", "crude", "iran", "russia", "pipeline", "venezuela"],
    "ZB": ["bond", "treasury", "yield", "fed", "rate", "debt", "deficit"],
    "UB": ["bond", "treasury", "yield", "fed", "rate", "debt", "deficit"],
    "SI": ["silver", "metal", "industrial", "china", "manufacturing"],
    "SIL": ["silver", "metal", "industrial", "china", "manufacturing"],
}

HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw_text: str) -> str:
    cleaned = HTML_TAG_RE.sub(" ", raw_text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _age_minutes(timestamp: datetime, now: datetime) -> int:
    return max(0, int((now - timestamp).total_seconds() // 60))


async def _fetch_trump_posts(client: httpx.AsyncClient, now: datetime) -> list[dict[str, Any]]:
    try:
        lookup_resp = await client.get(TRUTH_SOCIAL_LOOKUP_URL, headers=USER_AGENT)
        lookup_resp.raise_for_status()
        account_id = lookup_resp.json().get("id")
        if not account_id:
            return []

        posts_resp = await client.get(TRUTH_SOCIAL_POSTS_URL.format(account_id=account_id), headers=USER_AGENT)
        posts_resp.raise_for_status()
        posts_payload = posts_resp.json() or []
    except Exception:
        return []

    filtered_posts: list[dict[str, Any]] = []
    for post in posts_payload:
        created_at = _parse_iso_datetime(post.get("created_at"))
        if created_at is None:
            continue
        age_minutes = _age_minutes(created_at, now)
        if age_minutes > 240:
            continue
        text = _strip_html(str(post.get("content") or ""))
        if not text:
            continue
        filtered_posts.append(
            {
                "text": text,
                "created_at": created_at.isoformat(),
                "age_minutes": age_minutes,
            }
        )
    return filtered_posts


async def _fetch_finnhub_headlines(client: httpx.AsyncClient, now: datetime) -> list[dict[str, Any]]:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return []

    try:
        response = await client.get(FINNHUB_NEWS_URL.format(api_key=api_key), headers=USER_AGENT)
        response.raise_for_status()
        payload = response.json() or []
    except Exception:
        return []

    recent_headlines: list[dict[str, Any]] = []
    for item in payload:
        dt_value = item.get("datetime")
        if dt_value is None:
            continue
        try:
            published = datetime.fromtimestamp(int(dt_value), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            continue
        age_minutes = _age_minutes(published, now)
        if age_minutes > 120:
            continue
        summary = str(item.get("summary") or "").strip()
        recent_headlines.append(
            {
                "headline": str(item.get("headline") or "").strip(),
                "summary": summary[:200],
                "source": str(item.get("source") or "").strip(),
                "datetime": published.isoformat(),
                "age_minutes": age_minutes,
            }
        )
        if len(recent_headlines) >= 5:
            break
    return [h for h in recent_headlines if h["headline"]]


def _extract_themes(text_blobs: list[str]) -> list[str]:
    themes: list[str] = []
    theme_map = {
        "tariff escalation": ["tariff", "sanction", "trade war"],
        "Fed rate uncertainty": ["fed", "rate", "inflation", "yield"],
        "geopolitical tension": ["war", "conflict", "attack", "ceasefire"],
        "energy supply risk": ["oil", "opec", "pipeline", "crude"],
        "growth optimism": ["jobs", "growth", "strong economy", "rally", "surge"],
    }
    normalized_blobs = " ".join(text_blobs).lower()
    for label, keys in theme_map.items():
        if any(key in normalized_blobs for key in keys):
            themes.append(label)
        if len(themes) >= 3:
            break
    return themes


def _score_news_bias(trump_posts: list[dict[str, Any]], headlines: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    symbol_keys = SYMBOL_KEYWORDS.get(symbol.upper(), [])
    bullish_count = 0
    bearish_count = 0
    symbol_relevant = False
    text_blobs: list[str] = []

    items: list[str] = [str(post.get("text") or "") for post in trump_posts]
    items.extend(
        f"{str(headline.get('headline') or '')} {str(headline.get('summary') or '')}".strip()
        for headline in headlines
    )

    for text in items:
        normalized = text.lower()
        text_blobs.append(normalized)
        bullish_count += sum(1 for kw in BULLISH_KEYWORDS if kw in normalized)
        bearish_count += sum(1 for kw in BEARISH_KEYWORDS if kw in normalized)
        if symbol_keys and any(kw in normalized for kw in symbol_keys):
            symbol_relevant = True

    if bullish_count > bearish_count:
        overall_bias = "bullish"
    elif bearish_count > bullish_count:
        overall_bias = "bearish"
    else:
        overall_bias = "neutral"

    key_themes = _extract_themes(text_blobs)
    if not symbol_relevant:
        bias_note = "News flow is mixed with no direct symbol-specific news found."
    elif overall_bias == "bullish":
        bias_note = "Recent macro and headline flow leans risk-on for this symbol."
    elif overall_bias == "bearish":
        bias_note = "Recent macro and headline flow leans risk-off for this symbol."
    else:
        bias_note = "Recent headlines are balanced, with no strong directional bias."

    return {
        "overall_bias": overall_bias,
        "symbol_relevant": symbol_relevant,
        "key_themes": key_themes,
        "bias_note": bias_note,
    }


async def fetch_news_context(symbol: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    trump_posts: list[dict[str, Any]] = []
    headlines: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            trump_posts, headlines = await _fetch_trump_posts(client, now), await _fetch_finnhub_headlines(client, now)
    except Exception:
        trump_posts, headlines = [], []

    scored = _score_news_bias(trump_posts, headlines, symbol)
    return {
        "news_available": bool(trump_posts or headlines),
        "overall_bias": scored["overall_bias"],
        "symbol_relevant": scored["symbol_relevant"],
        "trump_posts": trump_posts,
        "headlines": [
            {"headline": item["headline"], "source": item["source"], "age_minutes": item["age_minutes"]}
            for item in headlines
        ],
        "key_themes": scored["key_themes"],
        "bias_note": scored["bias_note"],
    }
