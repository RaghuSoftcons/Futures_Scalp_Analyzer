"""Session-level daily loss protections."""

from __future__ import annotations


def check_session_allowed(account_size: float, losses_today: float, pnl_today: float) -> dict:
    """
    Evaluate whether a new trade is allowed for the current session.

    Returns:
    {
        "allowed": bool,
        "reason": str,
        "daily_loss_pct": float,
        "daily_loss_limit_pct": float,
        "session_status": str
    }
    """
    del losses_today  # currently informational; kept for API compatibility.

    daily_loss_limit_pct = 3.0
    if account_size <= 0:
        return {
            "allowed": False,
            "reason": "STOP TRADING - Invalid account size for session guard.",
            "daily_loss_pct": 0.0,
            "daily_loss_limit_pct": daily_loss_limit_pct,
            "session_status": "locked",
        }

    daily_loss_limit = account_size * 0.03
    daily_loss_pct = max((-pnl_today / account_size) * 100.0, 0.0)

    if pnl_today <= -daily_loss_limit:
        return {
            "allowed": False,
            "reason": "STOP TRADING - Daily loss limit breached for this session.",
            "daily_loss_pct": round(daily_loss_pct, 4),
            "daily_loss_limit_pct": daily_loss_limit_pct,
            "session_status": "locked",
        }

    if pnl_today <= -(account_size * 0.0225):
        return {
            "allowed": True,
            "reason": "WARNING - Daily drawdown is above 75% of the allowed loss limit.",
            "daily_loss_pct": round(daily_loss_pct, 4),
            "daily_loss_limit_pct": daily_loss_limit_pct,
            "session_status": "warning",
        }

    return {
        "allowed": True,
        "reason": "",
        "daily_loss_pct": round(daily_loss_pct, 4),
        "daily_loss_limit_pct": daily_loss_limit_pct,
        "session_status": "active",
    }
