"""Session-level daily loss guard."""

from __future__ import annotations


def check_session_allowed(account_size: float, losses_today: float, pnl_today: float) -> dict:
    daily_loss_limit = float(account_size) * 0.03
    loss_amount = abs(min(float(pnl_today), 0.0))
    daily_loss_pct = (loss_amount / daily_loss_limit * 100.0) if daily_loss_limit > 0 else 0.0

    if loss_amount >= daily_loss_limit:
        return {
            "allowed": False,
            "reason": "LOCKED: Daily loss limit breached.",
            "daily_loss_pct": round(daily_loss_pct, 2),
            "daily_loss_limit_pct": 3.0,
            "session_status": "locked",
        }

    warning_threshold = daily_loss_limit * 0.75
    if loss_amount >= warning_threshold:
        return {
            "allowed": True,
            "reason": "WARNING: Approaching daily loss limit.",
            "daily_loss_pct": round(daily_loss_pct, 2),
            "daily_loss_limit_pct": 3.0,
            "session_status": "warning",
        }

    del losses_today
    return {
        "allowed": True,
        "reason": "ACTIVE",
        "daily_loss_pct": round(daily_loss_pct, 2),
        "daily_loss_limit_pct": 3.0,
        "session_status": "active",
    }
