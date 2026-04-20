from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app import create_app
from futures_scalp_analyzer.models import FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import StaticPriceFeed
from futures_scalp_analyzer.service import analyze_request


def _request(account_size: int, pnl_today: float, losses_today: int) -> FuturesScalpIdeaRequest:
    return FuturesScalpIdeaRequest(
        symbol="ES",
        side="long",
        account_size=account_size,
        realized_pnl_today=pnl_today,
        realized_loss_count_today=losses_today,
    )


def test_stop_conditions_for_all_account_sizes():
    cases = [
        (50000, -300.0, 0, "STOP_LOSS_HIT"),
        (100000, -600.0, 0, "STOP_LOSS_HIT"),
        (150000, -900.0, 0, "STOP_LOSS_HIT"),
        (250000, -1500.0, 0, "STOP_LOSS_HIT"),
    ]
    for account_size, pnl_today, losses_today, expected_status in cases:
        response = asyncio.run(analyze_request(_request(account_size, pnl_today, losses_today), StaticPriceFeed({"ES": 5300.0})))
        assert response.verdict == "STOP TRADING"
        assert response.session_status == expected_status


def test_session_endpoint_returns_expected_shape():
    client = TestClient(create_app(StaticPriceFeed({"ES": 5300.0})))
    response = client.get("/futures/session?account_size=50000&losses_today=2&pnl_today=150")

    assert response.status_code == 200
    assert response.json() == {
        "can_trade": True,
        "reason": "ACTIVE",
        "trades_remaining": 1,
        "dollars_to_target": 450.0,
        "dollars_to_limit": 450.0,
        "session_status": "ACTIVE",
    }
