from futures_scalp_analyzer.recommendations import compute_final_recommendation
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
        "per_trade_risk": 200.0,
        "per_trade_target": 400.0,
        "daily_profit_target": 1200.0,
    }
    assert get_account_risk_template(150000)["daily_profit_target"] == 1800.0
    assert get_account_risk_template(250000)["per_trade_risk"] == 500.0


def test_preserve_existing_recommendation():
    ctx = make_ctx(final_recommendation="flatten")
    assert compute_final_recommendation(ctx) == "flatten"
