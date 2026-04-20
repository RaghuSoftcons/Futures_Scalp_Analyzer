"""Pure account and trade risk helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AccountRiskTemplate:
    account_size: int
    per_trade_risk: float
    per_trade_target: float
    daily_profit_target: float


ACCOUNT_RISK_TEMPLATES: dict[int, AccountRiskTemplate] = {
    50000: AccountRiskTemplate(50000, per_trade_risk=100.0, per_trade_target=200.0, daily_profit_target=600.0),
    100000: AccountRiskTemplate(100000, per_trade_risk=200.0, per_trade_target=400.0, daily_profit_target=1200.0),
    150000: AccountRiskTemplate(150000, per_trade_risk=300.0, per_trade_target=600.0, daily_profit_target=1800.0),
    250000: AccountRiskTemplate(250000, per_trade_risk=500.0, per_trade_target=1000.0, daily_profit_target=3000.0),
}


def get_account_risk_template(account_size: int) -> dict[str, float | int]:
    """Return the configured prop-firm risk template for a supported account."""
    template = ACCOUNT_RISK_TEMPLATES.get(account_size)
    if template is None:
        raise ValueError(f"Unsupported account size: {account_size}")
    return asdict(template)

