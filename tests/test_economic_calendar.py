import asyncio
from datetime import timedelta

from futures_scalp_analyzer import economic_calendar


def _event_payload(event_name: str, minutes_from_now: int, impact: str = "high") -> dict:
    now_et = economic_calendar.datetime.now(economic_calendar.EASTERN_TZ)
    event_dt = now_et + timedelta(minutes=minutes_from_now)
    return {
        "economicCalendar": [
            {
                "date": event_dt.date().isoformat(),
                "time": event_dt.strftime("%H:%M"),
                "event": event_name,
                "impact": impact,
            }
        ]
    }


def test_fetch_economic_events_no_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    result = asyncio.run(economic_calendar.fetch_economic_events("NQ"))

    assert result["events_today"] == []
    assert result["next_event"] is None
    assert result["minutes_to_next"] is None
    assert result["event_warning"] is False
    assert result["event_block"] is False


def test_fetch_economic_events_blocks_when_3_minutes_away(monkeypatch):
    async def _mock_load(_api_key: str):
        return _event_payload("CPI m/m", 3)

    monkeypatch.setenv("FINNHUB_API_KEY", "test")
    monkeypatch.setattr(economic_calendar, "_load_calendar_payload", _mock_load)

    result = asyncio.run(economic_calendar.fetch_economic_events("NQ"))

    assert result["event_warning"] is True
    assert result["event_block"] is True
    assert isinstance(result["warning_message"], str) and result["warning_message"]


def test_fetch_economic_events_warns_when_10_minutes_away(monkeypatch):
    async def _mock_load(_api_key: str):
        return _event_payload("FOMC Rate Decision", 10)

    monkeypatch.setenv("FINNHUB_API_KEY", "test")
    monkeypatch.setattr(economic_calendar, "_load_calendar_payload", _mock_load)

    result = asyncio.run(economic_calendar.fetch_economic_events("ES"))

    assert result["event_warning"] is True
    assert result["event_block"] is False


def test_fetch_economic_events_ignores_when_30_minutes_away(monkeypatch):
    async def _mock_load(_api_key: str):
        return _event_payload("NFP", 30)

    monkeypatch.setenv("FINNHUB_API_KEY", "test")
    monkeypatch.setattr(economic_calendar, "_load_calendar_payload", _mock_load)

    result = asyncio.run(economic_calendar.fetch_economic_events("NQ"))

    assert result["event_warning"] is False
    assert result["event_block"] is False
