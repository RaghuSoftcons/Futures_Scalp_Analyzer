"""Async economic calendar helpers — powered by Forex Factory via faireconomy.media mirror.

No API key required. Fetches this week's FF calendar JSON server-side (Railway).
High-impact (red folder) USD events are filtered for relevance to the traded symbol.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import httpx


# ---------------------------------------------------------------------------
# Forex Factory JSON mirror — updated every ~15 min, no auth required.
# Returns a list of events with keys:
#   title, country, date (YYYY-MM-DD), time (HH:MM am/pm or "Tentative"/"All Day"),
#   impact ("High" / "Medium" / "Low"), forecast, previous
# ---------------------------------------------------------------------------
_FF_THIS_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FF_NEXT_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

_FF_HEADERS = {
    "User-Agent": "FuturesScalpAnalyzer/1.0 (+https://github.com/RaghuSoftcons/Futures_Scalp_Analyzer)",
    "Accept": "application/json",
}

# Eastern time — FF calendar times are in US/Eastern
_ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# NQ / equity-relevant red-folder keywords
# Broad enough to catch Fed Chair speeches, Treasury Secretary statements,
# FOMC minutes, etc. — not just the big data releases.
# ---------------------------------------------------------------------------
_NQ_RED_KEYWORDS = (
    "fomc", "federal reserve", "fed chair", "powell", "fed",
    "cpi", "core cpi", "pce", "core pce",
    "nfp", "non-farm", "nonfarm", "unemployment", "jobless",
    "gdp", "retail sales",
    "pmi", "ism",
    "treasury", "debt ceiling", "budget",
    "tariff", "trade", "earnings",
    "press conference", "speech", "testimony", "remarks",
)

_OIL_RED_KEYWORDS = ("eia", "crude", "opec", "oil", "energy")
_METALS_RED_KEYWORDS = ("fomc", "cpi", "pce", "nfp", "federal reserve", "fed")
_TREASURY_RED_KEYWORDS = ("fomc", "cpi", "nfp", "treasury", "auction", "bond", "yield", "federal reserve")


def _default_calendar() -> dict:
    return {
        "events_today": [],
        "next_event": "",
        "minutes_to_next": None,
        "event_warning": False,
        "event_block": False,
        "warning_message": "",
    }


def _keywords_for_symbol(symbol: str) -> tuple[str, ...]:
    s = symbol.upper()
    if s in {"NQ", "ES", "MNQ", "MES"}:
        return _NQ_RED_KEYWORDS
    if s in {"CL", "MCL"}:
        return _OIL_RED_KEYWORDS
    if s in {"GC", "SI", "MGC", "SIL"}:
        return _METALS_RED_KEYWORDS
    if s in {"ZB", "UB"}:
        return _TREASURY_RED_KEYWORDS
    return _NQ_RED_KEYWORDS  # default to macro


def _is_relevant(symbol: str, title: str) -> bool:
    """Return True if this event title matches any keyword for the given symbol."""
    lowered = title.lower()
    return any(kw in lowered for kw in _keywords_for_symbol(symbol))


def _parse_ff_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse a Forex Factory date + time string into a UTC-aware datetime.

    FF date format:  YYYY-MM-DDT00:00:00-05:00  (ISO with ET offset)
    FF time format:  '8:30am' / '2:00pm' / 'Tentative' / 'All Day' / ''
    """
    # date_str from FF JSON looks like: "2026-04-21T00:00:00-04:00"
    # Extract just the date part
    try:
        date_part = date_str[:10]  # "2026-04-21"
    except Exception:
        return None

    time_str = (time_str or "").strip()
    if not time_str or time_str.lower() in {"tentative", "all day", ""}:
        # Treat as start of US Eastern day (midnight ET)
        try:
            dt_et = datetime.strptime(date_part, "%Y-%m-%d").replace(
                hour=0, minute=0, second=0, tzinfo=_ET
            )
            return dt_et.astimezone(timezone.utc)
        except Exception:
            return None

    # Parse "8:30am", "2:00pm", "12:00pm", etc.
    for fmt in ("%I:%M%p", "%I%p"):
        try:
            t = datetime.strptime(time_str.lower(), fmt)
            dt_et = datetime.strptime(date_part, "%Y-%m-%d").replace(
                hour=t.hour, minute=t.minute, second=0, tzinfo=_ET
            )
            return dt_et.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


async def _fetch_ff_events(url: str, timeout: httpx.Timeout) -> list[dict]:
    """Fetch and return raw FF calendar events from the given URL."""
    try:
        async with httpx.AsyncClient(headers=_FF_HEADERS, timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []
            return resp.json()
    except Exception:
        return []


async def fetch_economic_events(symbol: str) -> dict:
    """Return today's high-impact economic events relevant to *symbol*.

    Data source: Forex Factory calendar via nfs.faireconomy.media (no API key needed).
    Falls back gracefully to an empty calendar if the feed is unavailable.
    """
    timeout = httpx.Timeout(8.0)
    now_utc = datetime.now(tz=timezone.utc)
    now_et = now_utc.astimezone(_ET)
    today_et = now_et.date()

    # Fetch this week; if today is Sunday fetch next week too so Monday events appear
    raw = await _fetch_ff_events(_FF_THIS_WEEK_URL, timeout)
    if not raw:
        return _default_calendar()

    # On Sunday ET, also pull next week so upcoming Monday shows up
    if now_et.weekday() == 6:  # Sunday
        raw += await _fetch_ff_events(_FF_NEXT_WEEK_URL, timeout)

    relevant_today: list[dict] = []

    for item in raw:
        # Only USD events matter for US futures
        if str(item.get("country", "")).upper() != "USD":
            continue

        # Only red-folder (High impact)
        if str(item.get("impact", "")).lower() != "high":
            continue

        title = str(item.get("title") or "").strip()
        if not title:
            continue

        # Filter to symbol-relevant events
        if not _is_relevant(symbol, title):
            continue

        date_str = str(item.get("date") or "")
        time_str = str(item.get("time") or "")

        dt_utc = _parse_ff_datetime(date_str, time_str)
        if dt_utc is None:
            continue

        # Only today (ET date)
        if dt_utc.astimezone(_ET).date() != today_et:
            continue

        relevant_today.append({"event": title, "datetime": dt_utc})

    relevant_today.sort(key=lambda e: e["datetime"])
    upcoming = [e for e in relevant_today if e["datetime"] >= now_utc]

    result = _default_calendar()
    result["events_today"] = [e["event"] for e in relevant_today]

    if upcoming:
        next_event = upcoming[0]
        minutes_to_next = int((next_event["datetime"] - now_utc).total_seconds() // 60)
        event_warning = minutes_to_next <= 15
        event_block = minutes_to_next <= 5
        warning_message = ""
        if event_block:
            warning_message = f"BLOCK: {next_event['event']} in {max(minutes_to_next, 0)} min — do NOT enter new trades."
        elif event_warning:
            warning_message = f"WARNING: {next_event['event']} in {minutes_to_next} min — tighten stops or stand aside."

        result.update(
            {
                "next_event": next_event["event"],
                "minutes_to_next": minutes_to_next,
                "event_warning": event_warning,
                "event_block": event_block,
                "warning_message": warning_message,
            }
        )

    return result
