from futures_scalp_analyzer.session_guard import check_session_allowed


def test_session_guard_active():
    result = check_session_allowed(account_size=100000, losses_today=0, pnl_today=0.0)
    assert result["allowed"] is True
    assert result["session_status"] == "active"
    assert result["daily_loss_limit_pct"] == 3.0


def test_session_guard_warning():
    # 75% of $3,000 limit is $2,250
    result = check_session_allowed(account_size=100000, losses_today=2, pnl_today=-2250.0)
    assert result["allowed"] is True
    assert result["session_status"] == "warning"


def test_session_guard_locked():
    result = check_session_allowed(account_size=50000, losses_today=1, pnl_today=-1600.0)
    assert result["allowed"] is False
    assert result["session_status"] == "locked"
