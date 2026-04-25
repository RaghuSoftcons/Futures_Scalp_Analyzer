from __future__ import annotations

from futures_scalp_analyzer.apex_pipeline import (
    DEFAULT_RISK_SETTINGS,
    MANUAL_EXECUTION_NOTE,
    MarketDataProvider,
    MockMarketDataProvider,
    build_technical_readout,
    build_payload,
    calculate_ema,
    calculate_rsi,
    calculate_vwap,
    classify_trend,
    generate_trade_decision,
)


CURRENT_TIMESTAMP = "2026-04-24T14:00:00Z"
STALE_TIMESTAMP = "2026-04-24T13:00:00Z"


class EmptyProvider(MarketDataProvider):
    data_source = "schwab"

    def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": None, "data_source": "unavailable"}

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict]:
        return []


class FreshSchwabProvider(MarketDataProvider):
    data_source = "schwab"

    def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 130.0, "timestamp": None, "data_source": self.data_source}

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict]:
        return _bars_from_closes([120.0 + idx for idx in range(30)], timestamp=1_800_000_000_000)


class StaleSchwabProvider(MarketDataProvider):
    data_source = "schwab"

    def get_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "price": 130.0, "timestamp": STALE_TIMESTAMP, "data_source": self.data_source}

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict]:
        return _bars_from_closes([120.0 + idx for idx in range(30)], timestamp=STALE_TIMESTAMP)


def _bars_from_closes(closes: list[float], volume: float = 100.0, timestamp=0) -> list[dict]:
    return [
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
            "datetime": timestamp if timestamp else idx,
        }
        for idx, close in enumerate(closes)
    ]


def _payload_for_decision(**market_overrides):
    market_data = {
        "symbol": "NQ",
        "price": 110.0,
        "session_high": 111.0,
        "session_low": 95.0,
        "vwap": 105.0,
        "ema9": 108.0,
        "ema20": 104.0,
        "rsi": 60.0,
        "trend": "uptrend",
        "data_source": "schwab",
        "data_mode": "near_real_time",
        "provider_status": "connected",
        "timestamp": CURRENT_TIMESTAMP,
        "last_update_time": CURRENT_TIMESTAMP,
        "is_stale": False,
        "stale_reason": "",
        "data_gate_status": "open",
        "data_gate_reason": "",
    }
    market_data.update(market_overrides)
    return {
        "market_data": market_data,
        "context": {
            "news": [{"title": "Headline", "source": "news", "url": "https://example.com"}],
            "social": [{"title": "Post", "source": "Truth Social", "url": ""}],
            "context_rule": "Display only. Not used in trade decisions.",
        },
        "risk_settings": dict(DEFAULT_RISK_SETTINGS),
        "risk_state": {
            "daily_loss": 0.0,
            "estimated_risk": 0.0,
            "trades_today": 0,
            "consecutive_losses": 0,
            "locked_out": False,
        },
        "timestamp": CURRENT_TIMESTAMP,
    }


def test_ema_calculation():
    values = [float(i) for i in range(1, 11)]
    assert calculate_ema(values, 3) == 9.0


def test_rsi_calculation():
    closes = [44, 45, 46, 45, 47, 48, 49, 48, 50, 51, 52, 53, 52, 54, 55, 56]
    rsi = calculate_rsi([float(value) for value in closes], 14)
    assert rsi is not None
    assert round(rsi, 2) == 83.40


def test_vwap_calculation():
    bars = [
        {"high": 11.0, "low": 9.0, "close": 10.0, "volume": 100.0},
        {"high": 13.0, "low": 11.0, "close": 12.0, "volume": 300.0},
    ]
    assert calculate_vwap(bars) == 11.5


def test_trend_classification():
    assert classify_trend(110.0, 105.0, 108.0, 104.0) == "uptrend"
    assert classify_trend(100.0, 105.0, 102.0, 104.0) == "downtrend"
    assert classify_trend(100.0, 105.0, 106.0, 104.0) == "neutral"


def test_mock_provider_fallback_when_primary_incomplete():
    fallback = MockMarketDataProvider(
        quote={"symbol": "NQ", "price": 108.0},
        bars=_bars_from_closes([100.0 + idx for idx in range(30)]),
    )

    payload = build_payload("NQ", provider=EmptyProvider(), fallback_provider=fallback)

    assert payload["market_data"]["symbol"] == "NQ"
    assert payload["market_data"]["data_source"] == "mock"
    assert payload["market_data"]["data_mode"] == "mock"
    assert payload["market_data"]["provider_status"] == "fallback"
    assert payload["market_data"]["is_stale"] is False
    assert payload["market_data"]["data_gate_status"] == "closed"
    assert payload["market_data"]["data_gate_reason"] == "market data unavailable"
    assert payload["market_data"]["price"] == 108.0


def test_build_payload_returns_valid_structured_json():
    payload = build_payload(
        "NQ",
        provider=MockMarketDataProvider(),
        context={
            "news": [{"title": "Market headline", "source": "CNBC", "url": "https://example.com/news"}],
            "trump_posts_recent": ["Display-only social post"],
        },
    )

    assert set(payload) == {"market_data", "context", "risk_settings", "risk_state", "timestamp"}
    assert set(payload["market_data"]) == {
        "symbol",
        "price",
        "session_high",
        "session_low",
        "vwap",
        "ema9",
        "ema20",
        "rsi",
            "trend",
            "data_source",
            "data_mode",
            "provider_status",
            "timestamp",
            "last_update_time",
            "is_stale",
            "stale_reason",
            "data_gate_status",
            "data_gate_reason",
        }
    assert payload["context"]["context_rule"] == "Display only. Not used in trade decisions."
    assert payload["context"]["social"][0]["source"] == "Truth Social"


def test_schwab_success_path_marks_near_real_time_when_fresh():
    payload = build_payload("NQ", provider=FreshSchwabProvider(), allow_mock_fallback=False)

    assert payload["market_data"]["data_source"] == "schwab"
    assert payload["market_data"]["data_mode"] == "near_real_time"
    assert payload["market_data"]["provider_status"] == "connected"
    assert payload["market_data"]["is_stale"] is False
    assert payload["market_data"]["data_gate_status"] == "open"


def test_provider_unavailable_without_mock_fallback_marks_unavailable():
    payload = build_payload("NQ", provider=EmptyProvider(), allow_mock_fallback=False)

    assert payload["market_data"]["data_source"] == "unavailable"
    assert payload["market_data"]["data_mode"] == "unavailable"
    assert payload["market_data"]["provider_status"] == "unavailable"
    assert payload["market_data"]["is_stale"] is True
    assert payload["market_data"]["stale_reason"] == "market data unavailable"
    assert payload["market_data"]["data_gate_status"] == "closed"


def test_unavailable_market_data_returns_no_trade():
    payload = build_payload("NQ", provider=EmptyProvider(), allow_mock_fallback=False)

    decision = generate_trade_decision(payload)

    assert decision["recommendation"] == "NO TRADE"
    assert decision["no_trade_reason"] == "market data unavailable"
    assert decision["risk_status"] == "allowed"
    assert decision["data_gate_status"] == "closed"


def test_stale_market_data_returns_no_trade():
    payload = build_payload("NQ", provider=StaleSchwabProvider(), allow_mock_fallback=False)

    decision = generate_trade_decision(payload)

    assert payload["market_data"]["data_source"] == "schwab"
    assert payload["market_data"]["is_stale"] is True
    assert payload["market_data"]["stale_reason"] == "market data stale"
    assert payload["market_data"]["data_gate_status"] == "closed"
    assert decision["recommendation"] == "NO TRADE"
    assert decision["no_trade_reason"] == "market data stale"
    assert decision["risk_status"] == "allowed"
    assert decision["data_gate_status"] == "closed"


def test_required_market_data_missing_closes_data_gate():
    payload = _payload_for_decision(ema9=None)

    decision = generate_trade_decision(payload)

    assert decision["recommendation"] == "NO TRADE"
    assert decision["risk_status"] == "allowed"
    assert decision["data_gate_status"] == "closed"
    assert decision["no_trade_reason"] == "required market data missing"


def test_generate_trade_decision_returns_valid_long_json():
    decision = generate_trade_decision(_payload_for_decision())

    assert decision == {
        "recommendation": "LONG",
        "reason": "technical only",
        "confidence": 70,
        "risk_status": "allowed",
        "data_gate_status": "open",
        "data_gate_reason": "",
        "no_trade_reason": "",
        "manual_execution_note": MANUAL_EXECUTION_NOTE,
        "display_context": {
            "news": [{"title": "Headline", "source": "news", "url": "https://example.com"}],
            "social": [{"title": "Post", "source": "Truth Social", "url": ""}],
            "context_rule": "Display only. Not used in trade decisions.",
        },
    }


def test_generate_trade_decision_returns_short():
    payload = _payload_for_decision(
        price=95.0,
        vwap=100.0,
        ema9=96.0,
        ema20=98.0,
        rsi=40.0,
        trend="downtrend",
    )

    assert generate_trade_decision(payload)["recommendation"] == "SHORT"


def test_news_does_not_affect_decision():
    payload_a = _payload_for_decision()
    payload_b = _payload_for_decision()
    payload_b["context"]["news"] = [
        {"title": "Different headline", "source": "news", "url": "https://example.com/other"}
    ]

    decision_a = generate_trade_decision(payload_a)
    decision_b = generate_trade_decision(payload_b)

    assert decision_a["recommendation"] == decision_b["recommendation"] == "LONG"
    assert decision_a["confidence"] == decision_b["confidence"] == 70


def test_social_context_does_not_affect_decision():
    payload_a = _payload_for_decision()
    payload_b = _payload_for_decision()
    payload_b["context"]["social"] = [{"title": "Different social context", "source": "Truth Social", "url": ""}]

    decision_a = generate_trade_decision(payload_a)
    decision_b = generate_trade_decision(payload_b)

    assert decision_a["recommendation"] == decision_b["recommendation"] == "LONG"
    assert decision_a["confidence"] == decision_b["confidence"] == 70


def test_no_trade_behavior_when_technical_criteria_fail():
    payload = _payload_for_decision(rsi=75.0)

    decision = generate_trade_decision(payload)

    assert decision["recommendation"] == "NO TRADE"
    assert decision["risk_status"] == "allowed"
    assert decision["no_trade_reason"] == "technical criteria not met"


def test_risk_blocked_behavior():
    payload = _payload_for_decision()
    payload["risk_state"]["estimated_risk"] = 501.0

    decision = generate_trade_decision(payload)

    assert decision["recommendation"] == "NO TRADE"
    assert decision["risk_status"] == "blocked"
    assert decision["data_gate_status"] == "open"
    assert decision["no_trade_reason"] == "risk rule violated"
    assert decision["manual_execution_note"] == MANUAL_EXECUTION_NOTE


def test_technical_readout_price_above_and_bullish_alignment():
    payload = _payload_for_decision()
    decision = generate_trade_decision(payload)

    readout = build_technical_readout(payload, decision)

    assert "Price is above VWAP." in readout["price_relationships"]
    assert "Price is above EMA 9." in readout["price_relationships"]
    assert "Price is above EMA 20." in readout["price_relationships"]
    assert readout["moving_average_alignment"] == "EMA 9 is above EMA 20, short-term momentum is above the slower average."
    assert readout["rsi_comment"] == "RSI is bullish/positive."
    assert readout["trend_comment"].startswith("Alignment is bullish")
    assert readout["decision_comment"] == "Technical criteria are aligned bullish and risk is allowed."


def test_technical_readout_price_below_and_bearish_alignment():
    payload = _payload_for_decision(
        price=90.0,
        vwap=95.0,
        ema9=91.0,
        ema20=93.0,
        rsi=40.0,
        trend="downtrend",
    )
    decision = generate_trade_decision(payload)

    readout = build_technical_readout(payload, decision)

    assert "Price is below VWAP." in readout["price_relationships"]
    assert "Price is below EMA 9." in readout["price_relationships"]
    assert "Price is below EMA 20." in readout["price_relationships"]
    assert readout["moving_average_alignment"] == "EMA 9 is below EMA 20, short-term momentum is below the slower average."
    assert readout["rsi_comment"] == "RSI is bearish/weak."
    assert readout["trend_comment"].startswith("Alignment is bearish")
    assert readout["decision_comment"] == "Technical criteria are aligned bearish and risk is allowed."


def test_technical_readout_mixed_alignment_and_no_trade_comment():
    payload = _payload_for_decision(price=100.0, vwap=105.0, ema9=102.0, ema20=99.0, rsi=50.0, trend="neutral")
    decision = generate_trade_decision(payload)

    readout = build_technical_readout(payload, decision)

    assert readout["trend_comment"] == "Alignment is mixed because price and moving averages are not fully aligned."
    assert readout["rsi_comment"] == "RSI is neutral."
    assert readout["decision_comment"] == "Decision remains NO TRADE because technical criteria are not fully aligned."


def test_technical_readout_rsi_threshold_comments():
    cases = [
        (75.0, "RSI is overbought."),
        (60.0, "RSI is bullish/positive."),
        (50.0, "RSI is neutral."),
        (40.0, "RSI is bearish/weak."),
        (25.0, "RSI is oversold."),
    ]
    for rsi, expected in cases:
        payload = _payload_for_decision(rsi=rsi)
        decision = generate_trade_decision(payload)
        assert build_technical_readout(payload, decision)["rsi_comment"] == expected


def test_technical_readout_risk_blocked_comment():
    payload = _payload_for_decision()
    payload["risk_state"]["locked_out"] = True
    decision = generate_trade_decision(payload)

    readout = build_technical_readout(payload, decision)

    assert readout["decision_comment"] == "Risk rules are blocking new recommendations."


def test_technical_readout_data_gate_closed_stale_safety_note():
    payload = _payload_for_decision(is_stale=True, stale_reason="market data stale", data_gate_status="closed", data_gate_reason="market data stale")
    decision = generate_trade_decision(payload)

    readout = build_technical_readout(payload, decision)

    assert readout["summary"].startswith(
        "Market data is stale. Technical readout is shown for context only. "
        "Trade recommendations are blocked until data freshness is restored."
    )


def test_technical_readout_ignores_news_and_social_context():
    payload_a = _payload_for_decision()
    payload_b = _payload_for_decision()
    payload_b["context"]["news"] = [{"title": "Different headline", "source": "news", "url": ""}]
    payload_b["context"]["social"] = [{"title": "Different post", "source": "Truth Social", "url": ""}]
    decision_a = generate_trade_decision(payload_a)
    decision_b = generate_trade_decision(payload_b)

    assert build_technical_readout(payload_a, decision_a) == build_technical_readout(payload_b, decision_b)
