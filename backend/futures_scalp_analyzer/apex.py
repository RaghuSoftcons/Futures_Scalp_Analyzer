"""Apex Scalp Engine platform metadata and guardrails."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal


PLATFORM_NAME = "Apex Scalp Engine"
EXECUTION_MODE: Literal["manual_only"] = "manual_only"
ORDER_ROUTING_ENABLED = False
NEWS_DECISION_POLICY: Literal["display_only"] = "display_only"


def build_manual_execution_notice() -> str:
    return (
        "Decision-support only. No live orders are placed or routed; traders must execute "
        "manually in their chosen platform."
    )


def build_accountability_status(
    trader_id: str | None,
    trade_plan_id: str | None,
) -> Literal["identified", "anonymous"]:
    if trader_id or trade_plan_id:
        return "identified"
    return "anonymous"


def build_platform_status() -> dict[str, object]:
    return {
        "platform": PLATFORM_NAME,
        "execution_mode": EXECUTION_MODE,
        "order_routing_enabled": ORDER_ROUTING_ENABLED,
        "news_decision_policy": NEWS_DECISION_POLICY,
        "manual_execution_notice": build_manual_execution_notice(),
        "as_of": datetime.now(timezone.utc).isoformat(),
    }
