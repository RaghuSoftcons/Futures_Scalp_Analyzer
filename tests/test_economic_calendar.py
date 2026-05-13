import asyncio
from datetime import datetime, timedelta, timezone

from futures_scalp_analyzer import economic_calendar
from futures_scalp_analyzer.economic_calendar import fetch_economic_events

def test_economic_calendar_defaults_without_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    async def fake_fetch(_url, _timeout):
        return []

    monkeypatch.setattr(economic_calendar, "_fetch_ff_events", fake_fetch)
    result = asyncio.run(fetch_economic_events("ES"))
    assert result["event_warning"] is False
    assert result["event_block"] is False
    assert result["next_event"] == ""


def test_economic_calendar_populates_context_for_relevant_event_today(monkeypatch):
    now_et = datetime.now(timezone.utc).astimezone(economic_calendar._ET)
    event_time = now_et + timedelta(minutes=45)

    async def fake_fetch(_url, _timeout):
        return [
            {
                "country": "USD",
                "impact": "High",
                "title": "FOMC Press Conference",
                "date": event_time.isoformat(),
                "time": event_time.strftime("%I:%M%p").lstrip("0").lower(),
            }
        ]

    monkeypatch.setattr(economic_calendar, "_fetch_ff_events", fake_fetch)

    result = asyncio.run(fetch_economic_events("ES"))

    assert result["next_event"] == "FOMC Press Conference"
    assert result["events_today"] == ["FOMC Press Conference"]
    assert result["warning_message"].startswith("Upcoming economic event today:")
    assert result["event_warning"] is False
    assert result["event_block"] is False
