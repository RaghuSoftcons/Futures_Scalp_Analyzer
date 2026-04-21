from futures_scalp_analyzer.recommendations import (
    compute_final_recommendation,
    compute_scalper_decision,
    detect_extension,
    detect_pullback,
)
from futures_scalp_analyzer.risk import get_account_risk_template


def make_ctx(**overrides):
    ctx = {
        "mode": "idea_eval",
        "live_price": 100.0,
        "entry_verdict": "attractive",
        "trade_verdict": "favorable",
        "liquidity_score": "good",
        "rr_ratio": 2.0,
        "pricing_percentage_difference": 2.0,
        "risk_rule_violations": {
            "per_trade_risk_exceeds_limit": False,
            "max_loss_trades_reached": False,
            "daily_profit_target_reached": False,
        },
        "risk_reward_asymmetric": False,
        "is_far_from_key_levels": False,
        "final_recommendation": None,
        "final_recommendation_comment": "",
    }
    ctx.update(overrides)
    return ctx


def test_take_recommendation():
    ctx = make_ctx()
    assert compute_final_recommendation(ctx) == "take"


def test_take_only_on_pullback_recommendation():
    ctx = make_ctx(
        entry_verdict="rich",
        pricing_percentage_difference=10.0,
        liquidity_score="acceptable",
    )
    assert compute_final_recommendation(ctx) == "take only on pullback"


def test_scalp_only_for_speculative_trade():
    ctx = make_ctx(trade_verdict="speculative")
    assert compute_final_recommendation(ctx) == "scalp only"


def test_pass_when_per_trade_risk_limit_exceeded():
    ctx = make_ctx(
        risk_rule_violations={
            "per_trade_risk_exceeds_limit": True,
            "max_loss_trades_reached": False,
            "daily_profit_target_reached": False,
        }
    )
    assert compute_final_recommendation(ctx) == "pass"


def test_pass_when_max_loss_trades_reached():
    ctx = make_ctx(
        risk_rule_violations={
            "per_trade_risk_exceeds_limit": False,
            "max_loss_trades_reached": True,
            "daily_profit_target_reached": False,
        }
    )
    assert compute_final_recommendation(ctx) == "pass"


def test_pass_when_daily_profit_target_reached():
    ctx = make_ctx(
        risk_rule_violations={
            "per_trade_risk_exceeds_limit": False,
            "max_loss_trades_reached": False,
            "daily_profit_target_reached": True,
        }
    )
    assert compute_final_recommendation(ctx) == "pass"


def test_flatten_for_asymmetric_position_management():
    ctx = make_ctx(mode="position_mgmt", risk_reward_asymmetric=True)
    assert compute_final_recommendation(ctx) == "flatten"


def test_unavailable_when_live_price_missing():
    ctx = make_ctx(live_price=None)
    assert compute_final_recommendation(ctx) == "unavailable"


def test_account_scaling_templates():
    assert get_account_risk_template(100000) == {
        "account_size": 100000,
        "daily_loss_limit": 600.0,
        "per_trade_risk": 200.0,
        "per_trade_target": 400.0,
        "daily_profit_target": 1200.0,
    }
    assert get_account_risk_template(150000)["daily_profit_target"] == 1800.0
    assert get_account_risk_template(250000)["per_trade_risk"] == 500.0


def test_preserve_existing_recommendation():
    ctx = make_ctx(final_recommendation="flatten")
    assert compute_final_recommendation(ctx) == "flatten"


def test_short_scalp_pullback_below_vwap_downtrend_returns_short():
    ctx = make_ctx(
        side="short",
        market_data_available=True,
        live_price=19910.0,
        vwap=19940.0,
        trend="downtrend",
        session_low=19900.0,
        session_high=20010.0,
        live_atr=100.0,
        ema9=19915.0,
        rsi=42.0,
        vwap_position="below_vwap",
        volume_condition="normal_volume",
    )
    assert detect_pullback(ctx) is True
    decision = compute_scalper_decision(ctx)
    assert decision["final_recommendation"] == "SHORT"
    assert decision["setup_type"] == "PULLBACK"
    assert compute_final_recommendation(ctx) == "take"


def test_short_scalp_extension_blocks_trade():
    ctx = make_ctx(
        side="short",
        market_data_available=True,
        live_price=19903.0,
        vwap=19945.0,
        trend="downtrend",
        session_low=19900.0,
        session_high=20010.0,
        live_atr=100.0,
        ema9=19910.0,
        rsi=27.0,
        vwap_position="below_vwap",
        volume_condition="high_volume",
    )
    assert detect_pullback(ctx) is False
    assert detect_extension(ctx) is True
    decision = compute_scalper_decision(ctx)
    assert decision["final_recommendation"] == "NO TRADE"
    assert decision["setup_type"] == "EXTENSION"
    assert compute_final_recommendation(ctx) == "pass"


def test_long_reversal_near_session_low_with_strong_bounce_returns_long():
    ctx = make_ctx(
        side="long",
        market_data_available=True,
        live_price=19908.0,
        vwap=19925.0,
        trend="downtrend",
        session_low=19900.0,
        session_high=20010.0,
        live_atr=100.0,
        ema9=19905.0,
        rsi=28.0,
        vwap_position="below_vwap",
        volume_condition="high_volume",
    )
    decision = compute_scalper_decision(ctx)
    assert decision["final_recommendation"] == "LONG"
    assert decision["setup_type"] == "REVERSAL"
    assert compute_final_recommendation(ctx) == "scalp only"


def test_long_pullback_above_vwap_uptrend_returns_long():
    ctx = make_ctx(
        side="long",
        market_data_available=True,
        live_price=19900.0,
        vwap=19880.0,
        trend="uptrend",
        session_low=19780.0,
        session_high=19910.0,
        live_atr=100.0,
        ema9=19898.0,
        rsi=56.0,
        vwap_position="above_vwap",
        volume_condition="normal_volume",
    )
    assert detect_pullback(ctx) is True
    assert detect_extension(ctx) is False
    decision = compute_scalper_decision(ctx)
    assert decision["final_recommendation"] == "LONG"
    assert decision["setup_type"] == "PULLBACK"
    assert compute_final_recommendation(ctx) == "take"
