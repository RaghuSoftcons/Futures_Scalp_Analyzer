"""Async economic calendar helpers."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx


def _default_calendar() -> dict:
    return {
        "events_today": [],
        "next_event": "",
        "minutes_to_next": None,
        "event_warning": False,
        "event_block": False,
        "warning_message": "",
    }


def _is_relevant(symbol: str, event_text: str) -> bool:
    symbol = symbol.upper()
    text = event_text.upper()

    macro_terms = ("FOMC", "FED", "CPI", "NFP", "PCE", "GDP", "PMI")
    oil_terms = ("EIA", "CRUDE", "OPEC")
    metals_terms = ("FOMC", "CPI", "NFP", "PCE")
    treasury_terms = ("TREASURY", "AUCTION", "BOND", "NOTE", "YIELD", "FOMC", "CPI", "NFP")

    if symbol in {"NQ", "ES", "MNQ", "MES"}:
        return any(term in text for term in macro_terms)
    if symbol in {"CL", "MCL"}:
        return any(term in text for term in oil_terms)
    if symbol in {"GC", "SI", "MGC", "SIL"}:
        return any(term in text for term in metals_terms)
    if symbol in {"ZB", "UB"}:
        return any(term in text for term in treasury_terms)
    return any(term in text for term in macro_terms)


async def fetch_economic_events(symbol: str) -> dict:
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return _default_calendar()

    now = datetime.now(timezone.utc)
    today = now.date()
    timeout = httpx.Timeout(5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={"token": api_key},
            )
            if response.status_code != 200:
                return _default_calendar()
            payload = response.json()
    except Exception:
        return _default_calendar()

    items = payload.get("economicCalendar") or payload.get("events") or []
    relevant_today: list[dict] = []

    for item in items:
        impact = str(item.get("impact") or item.get("importance") or "").lower()
        if impact not in {"high", "3", "high impact"}:
            continue

        event_name = str(item.get("event") or item.get("title") or "").strip()
        date_str = str(item.get("date") or "").strip()
        time_str = str(item.get("time") or "00:00").strip()
        if not event_name or not date_str:
            continue

        try:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")
        except ValueError:
            try:
                dt = datetime.fromisoformat(f"{date_str}T00:00:00+00:00")
            except ValueError:
                continue

        if dt.date() != today:
            continue
        if not _is_relevant(symbol, event_name):
            continue

        relevant_today.append({"event": event_name, "datetime": dt})

    relevant_today.sort(key=lambda event: event["datetime"])
    upcoming = [event for event in relevant_today if event["datetime"] >= now]

    result = _default_calendar()
    result["events_today"] = [event["event"] for event in relevant_today]

    if upcoming:
        next_event = upcoming[0]
        minutes_to_next = int((next_event["datetime"] - now).total_seconds() // 60)
        event_warning = minutes_to_next <= 15
        event_block = minutes_to_next <= 5
        warning_message = ""
        if event_block:
            warning_message = f"BLOCK: {next_event['event']} in {max(minutes_to_next, 0)} minutes."
        elif event_warning:
            warning_message = f"WARNING: {next_event['event']} in {max(minutes_to_next, 0)} minutes."

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
