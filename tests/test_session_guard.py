from futures_scalp_analyzer.session_guard import check_session_allowed


def test_losses_within_limit_are_allowed():
    state = check_session_allowed(account_size=50000, losses_today=1, pnl_today=-500.0)

    assert state["allowed"] is True
    assert state["session_status"] == "active"
    assert state["daily_loss_limit_pct"] == 3.0


def test_losses_at_80_percent_of_limit_triggers_warning():
    state = check_session_allowed(account_size=50000, losses_today=2, pnl_today=-1200.0)

    assert state["allowed"] is True
    assert state["session_status"] == "warning"
    assert state["daily_loss_pct"] == 2.4


def test_losses_exceed_limit_locks_session():
    state = check_session_allowed(account_size=50000, losses_today=3, pnl_today=-1600.0)

    assert state["allowed"] is False
    assert state["session_status"] == "locked"
    assert "Daily loss limit" in state["reason"]


def test_zero_losses_allowed():
    state = check_session_allowed(account_size=50000, losses_today=0, pnl_today=0.0)

    assert state["allowed"] is True
    assert state["session_status"] == "active"
    assert state["daily_loss_pct"] == 0.0
