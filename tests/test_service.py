from __future__ import annotations

from futures_scalp_analyzer.service import _build_gpt_fields


def _base_kwargs() -> dict:
    return {
        "account_size": 50000,
        "losses_today": 0,
        "pnl_today": 0.0,
        "symbol": "ES",
        "side": "long",
        "live_price": 5000.0,
        "entry_price": 5000.0,
        "stop_price": 4990.0,
        "target_price": 5020.0,
        "risk_per_contract": 500.0,
        "reward_per_contract": 1000.0,
        "rr_ratio": 2.0,
        "entry_verdict": "attractive",
        "trade_verdict": "favorable",
        "directional_score": 70.0,
        "momentum_bias": "bullish",
        "ema9": 5001.0,
        "ema20": 4998.0,
        "vwap": 4999.0,
        "rsi": 58.0,
        "trend": "uptrend",
        "market_structure": "higher highs",
        "volume_condition": "healthy",
        "rsi_condition": "not overbought",
        "session_high": 5030.0,
        "session_low": 4970.0,
        "prior_day_high": 5040.0,
        "prior_day_low": 4960.0,
        "live_atr": 45.0,
        "market_data_available": True,
        "session_state": {"session_status": "ACTIVE"},
        "final_recommendation": "take",
    }


def test_build_gpt_fields_includes_bearish_news_bias_guidance() -> None:
    fields = _build_gpt_fields(
        **_base_kwargs(),
        news_bias="bearish",
        news_bias_note="Tariff escalation risk",
        trump_posts_recent=["Post about reciprocal tariffs"],
        top_headlines=["US futures slide on trade tensions"],
    )

    assert "Overall Bias: bearish" in fields["user_message"]
    assert "bearish + long => lower conviction" in fields["system_prompt"]
    assert "Bearish news flow is a downside risk for long exposure." in fields["watch_out_for"]


def test_build_gpt_fields_includes_bullish_news_bias_guidance() -> None:
    fields = _build_gpt_fields(
        **_base_kwargs(),
        news_bias="bullish",
        news_bias_note="Cooling inflation supports risk assets",
        trump_posts_recent=["Post praising growth"],
        top_headlines=["Stocks rally after CPI surprise"],
    )

    assert "Overall Bias: bullish" in fields["user_message"]
    assert "bullish + long => higher conviction" in fields["system_prompt"]
    assert "News backdrop is bullish, supporting long-side conviction." in fields["why"]
