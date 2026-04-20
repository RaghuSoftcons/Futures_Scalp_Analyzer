"""Pure account and trade risk helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AccountRiskTemplate:
    account_size: int
    daily_loss_limit: float
    per_trade_risk: float
    per_trade_target: float
    daily_profit_target: float


ACCOUNT_RISK_TEMPLATES: dict[int, AccountRiskTemplate] = {
    50000: AccountRiskTemplate(50000, daily_loss_limit=300.0, per_trade_risk=100.0, per_trade_target=200.0, daily_profit_target=600.0),
    100000: AccountRiskTemplate(100000, daily_loss_limit=600.0, per_trade_risk=200.0, per_trade_target=400.0, daily_profit_target=1200.0),
    150000: AccountRiskTemplate(150000, daily_loss_limit=900.0, per_trade_risk=300.0, per_trade_target=600.0, daily_profit_target=1800.0),
    250000: AccountRiskTemplate(250000, daily_loss_limit=1500.0, per_trade_risk=500.0, per_trade_target=1000.0, daily_profit_target=3000.0),
}


def get_account_risk_template(account_size: int) -> dict[str, float | int]:
    """Return the configured prop-firm risk template for a supported account."""
    template = ACCOUNT_RISK_TEMPLATES.get(account_size)
    if template is None:
        raise ValueError(f"Unsupported account size: {account_size}")
    return asdict(template)


def evaluate_session_status(account_size: int, losses_today: int, pnl_today: float) -> dict[str, float | int | bool | str]:
    """Return session-wide risk status before any new trade is considered."""
    template = get_account_risk_template(account_size)
    daily_loss_limit = float(template["daily_loss_limit"])
    daily_profit_target = float(template["daily_profit_target"])

    if pnl_today <= -daily_loss_limit:
        session_status = "STOP_LOSS_HIT"
        can_trade = False
        reason = "STOP TRADING - Daily loss limit reached."
    elif losses_today >= 3:
        session_status = "MAX_LOSSES_HIT"
        can_trade = False
        reason = "STOP TRADING - Max losing trades reached."
    elif pnl_today >= daily_profit_target:
        session_status = "TARGET_HIT"
        can_trade = False
        reason = "STOP TRADING - Daily target achieved. Lock in profits."
    else:
        session_status = "ACTIVE"
        can_trade = True
        reason = "ACTIVE"

    return {
        "can_trade": can_trade,
        "reason": reason,
        "trades_remaining": max(0, 3 - losses_today),
        "dollars_to_target": max(daily_profit_target - pnl_today, 0.0),
        "dollars_to_limit": pnl_today + daily_loss_limit,
        "session_status": session_status,
        "daily_loss_limit": daily_loss_limit,
        "daily_profit_target": daily_profit_target,
        "per_trade_risk_limit": float(template["per_trade_risk"]),
        "per_trade_profit_target": float(template["per_trade_target"]),
    }
