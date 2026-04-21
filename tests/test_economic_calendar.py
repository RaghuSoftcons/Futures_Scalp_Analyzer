import asyncio

from futures_scalp_analyzer.economic_calendar import fetch_economic_events

def test_economic_calendar_defaults_without_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    result = asyncio.run(fetch_economic_events("ES"))
    assert result["event_warning"] is False
    assert result["event_block"] is False
    assert result["next_event"] == ""
