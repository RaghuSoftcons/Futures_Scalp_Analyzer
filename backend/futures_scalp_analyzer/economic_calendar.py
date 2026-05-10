"""Async economic calendar helpers powered by the Forex Factory mirror."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx


_FF_THIS_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_FF_NEXT_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

_FF_HEADERS = {
    "User-Agent": "FuturesScalpAnalyzer/1.0 (+https://github.com/RaghuSoftcons/Futures_Scalp_Analyzer)",
    "Accept": "application/json",
}

_ET = ZoneInfo("America/New_York")

_NQ_RED_KEYWORDS = (
    "fomc",
    "federal reserve",
    "fed chair",
    "powell",
    "fed",
    "cpi",
    "core cpi",
    "pce",
    "core pce",
    "nfp",
    "non-farm",
    "nonfarm",
    "unemployment",
    "jobless",
    "gdp",
    "retail sales",
    "pmi",
    "ism",
    "treasury",
    "debt ceiling",
    "budget",
    "tariff",
    "trade",
    "earnings",
    "press conference",
    "speech",
    "testimony",
    "remarks",
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
    return _NQ_RED_KEYWORDS


def _is_relevant(symbol: str, title: str) -> bool:
    lowered = title.lower()
    return any(keyword in lowered for keyword in _keywords_for_symbol(symbol))


def _parse_ff_datetime(date_str: str, time_str: str) -> datetime | None:
    try:
        date_part = date_str[:10]
    except Exception:
        return None

    cleaned_time = (time_str or "").strip()
    if not cleaned_time or cleaned_time.lower() in {"tentative", "all day", ""}:
        try:
            dt_et = datetime.strptime(date_part, "%Y-%m-%d").replace(
                hour=0,
                minute=0,
                second=0,
                tzinfo=_ET,
            )
            return dt_et.astimezone(timezone.utc)
        except Exception:
            return None

    for fmt in ("%I:%M%p", "%I%p"):
        try:
            parsed_time = datetime.strptime(cleaned_time.lower(), fmt)
            dt_et = datetime.strptime(date_part, "%Y-%m-%d").replace(
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                second=0,
                tzinfo=_ET,
            )
            return dt_et.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


async def _fetch_ff_events(url: str, timeout: httpx.Timeout) -> list[dict]:
    try:
        async with httpx.AsyncClient(headers=_FF_HEADERS, timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            return response.json()
    except Exception:
        return []


async def fetch_economic_events(symbol: str) -> dict:
    """Return today's high-impact economic events relevant to *symbol*."""

    timeout = httpx.Timeout(8.0)
    now_utc = datetime.now(tz=timezone.utc)
    now_et = now_utc.astimezone(_ET)
    today_et = now_et.date()

    raw = await _fetch_ff_events(_FF_THIS_WEEK_URL, timeout)
    if not raw:
        return _default_calendar()

    if now_et.weekday() == 6:
        raw += await _fetch_ff_events(_FF_NEXT_WEEK_URL, timeout)

    relevant_today: list[dict] = []
    seen_events: set[tuple[str, datetime]] = set()

    for item in raw:
        if str(item.get("country", "")).upper() != "USD":
            continue
        if str(item.get("impact", "")).lower() != "high":
            continue

        title = str(item.get("title") or "").strip()
        if not title or not _is_relevant(symbol, title):
            continue

        dt_utc = _parse_ff_datetime(str(item.get("date") or ""), str(item.get("time") or ""))
        if dt_utc is None:
            continue
        if dt_utc.astimezone(_ET).date() != today_et:
            continue

        event_key = (title, dt_utc)
        if event_key in seen_events:
            continue
        seen_events.add(event_key)
        relevant_today.append({"event": title, "datetime": dt_utc})

    relevant_today.sort(key=lambda event: event["datetime"])
    upcoming = [event for event in relevant_today if event["datetime"] >= now_utc]

    result = _default_calendar()
    result["events_today"] = [event["event"] for event in relevant_today]

    if relevant_today:
        reference_event = upcoming[0] if upcoming else relevant_today[-1]
        minutes_to_next = None
        event_warning = False
        event_block = False

        if upcoming:
            minutes_to_next = int((reference_event["datetime"] - now_utc).total_seconds() // 60)
            event_warning = minutes_to_next <= 15
            event_block = minutes_to_next <= 5
            if event_block:
                warning_message = (
                    f"BLOCK: {reference_event['event']} in {max(minutes_to_next, 0)} min - do NOT enter new trades."
                )
            elif event_warning:
                warning_message = (
                    f"WARNING: {reference_event['event']} in {minutes_to_next} min - tighten stops or stand aside."
                )
            else:
                warning_message = f"Upcoming economic event today: {reference_event['event']} in {minutes_to_next} min."
        else:
            warning_message = f"Relevant economic event already occurred today: {reference_event['event']}."

        result.update(
            {
                "next_event": reference_event["event"],
                "minutes_to_next": minutes_to_next,
                "event_warning": event_warning,
                "event_block": event_block,
                "warning_message": warning_message,
            }
        )

    return result
