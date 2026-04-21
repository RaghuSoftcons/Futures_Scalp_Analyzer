"""Economic calendar awareness for high-impact event risk."""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

FINNHUB_ECONOMIC_CALENDAR_URL = "https://finnhub.io/api/v1/calendar/economic"
WARNING_WINDOW_MINUTES = 15
BLOCK_WINDOW_MINUTES = 5
EASTERN_TZ = ZoneInfo("America/New_York")

SYMBOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "NQ": ("fomc", "cpi", "nfp", "gdp", "ppi", "retail sales"),
    "MNQ": ("fomc", "cpi", "nfp", "gdp", "ppi", "retail sales"),
    "ES": ("fomc", "cpi", "nfp", "gdp", "ppi", "retail sales"),
    "MES": ("fomc", "cpi", "nfp", "gdp", "ppi", "retail sales"),
    "CL": ("eia", "petroleum", "inventory", "opec"),
    "MCL": ("eia", "petroleum", "inventory", "opec"),
    "GC": ("fomc", "cpi", "nfp", "usd"),
    "MGC": ("fomc", "cpi", "nfp", "usd"),
    "SI": ("fomc", "cpi", "nfp", "usd"),
    "SIL": ("fomc", "cpi", "nfp", "usd"),
    "ZB": ("fomc", "cpi", "nfp", "treasury auction", "auction"),
    "UB": ("fomc", "cpi", "nfp", "treasury auction", "auction"),
}


def _default_payload() -> dict:
    return {
        "events_today": [],
        "next_event": None,
        "minutes_to_next": None,
        "event_warning": False,
        "event_block": False,
        "warning_message": "",
    }


def _event_datetime(event: dict, now_et: datetime) -> datetime | None:
    event_date = str(event.get("date") or "")
    event_time = str(event.get("time") or "")

    if not event_date or not event_time or event_time.lower() in {"all day", "tentative"}:
        return None

    time_clean = event_time.strip().upper().replace(" ET", "")
    try:
        parsed_time = datetime.strptime(time_clean, "%H:%M").time()
    except ValueError:
        try:
            parsed_time = datetime.strptime(time_clean, "%I:%M%p").time()
        except ValueError:
            return None

    try:
        parsed_date = date.fromisoformat(event_date)
    except ValueError:
        return None

    return datetime.combine(parsed_date, parsed_time, tzinfo=EASTERN_TZ)


def _is_event_relevant(symbol: str, event_name: str) -> bool:
    keywords = SYMBOL_KEYWORDS.get(symbol)
    if not keywords:
        return True
    event_name_lower = event_name.lower()
    return any(keyword in event_name_lower for keyword in keywords)


def _normalize_event(event: dict, event_dt: datetime) -> dict:
    event_name = str(event.get("event") or event.get("country") or "Unknown event")
    return {
        "time": event_dt.strftime("%H:%M ET"),
        "event": event_name,
        "impact": "high",
    }


async def _load_calendar_payload(api_key: str) -> dict:
    params = {"token": api_key}
    timeout = httpx.Timeout(5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(FINNHUB_ECONOMIC_CALENDAR_URL, params=params)
        response.raise_for_status()
        return response.json()


async def fetch_economic_events(symbol: str) -> dict:
    defaults = _default_payload()
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return defaults

    try:
        payload = await _load_calendar_payload(api_key)
        events_raw = payload.get("economicCalendar") or payload.get("events") or []
        now_et = datetime.now(EASTERN_TZ)
        today_et = now_et.date()

        relevant_events: list[tuple[datetime, dict]] = []
        events_today: list[dict] = []

        for event in events_raw:
            if str(event.get("impact", "")).lower() != "high":
                continue

            event_dt = _event_datetime(event, now_et)
            if event_dt is None or event_dt.date() != today_et:
                continue

            event_name = str(event.get("event") or "")
            if not _is_event_relevant(symbol, event_name):
                continue

            normalized = _normalize_event(event, event_dt)
            events_today.append(normalized)
            relevant_events.append((event_dt, normalized))

        if not relevant_events:
            defaults["events_today"] = events_today
            return defaults

        relevant_events.sort(key=lambda row: abs((row[0] - now_et).total_seconds()))
        nearest_dt, nearest_event = relevant_events[0]
        minutes_offset = int((nearest_dt - now_et).total_seconds() / 60)
        distance = abs(minutes_offset)

        warning = distance <= WARNING_WINDOW_MINUTES
        block = distance <= BLOCK_WINDOW_MINUTES

        direction = "in" if minutes_offset >= 0 else "was"
        minutes_abs = abs(minutes_offset)
        if direction == "in":
            warning_message = f"{nearest_event['event']} release in {minutes_abs} minutes - high volatility expected"
        else:
            warning_message = f"{nearest_event['event']} release was {minutes_abs} minutes ago - high volatility expected"

        return {
            "events_today": events_today,
            "next_event": nearest_event,
            "minutes_to_next": minutes_offset,
            "event_warning": warning,
            "event_block": block,
            "warning_message": warning_message if warning else "",
        }
    except Exception:
        return defaults
