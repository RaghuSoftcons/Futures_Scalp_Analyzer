"""Pydantic request and response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


SupportedSymbol = Literal["NQ", "ES", "CL", "GC", "SI", "ZB", "UB"]
TradeSide = Literal["long", "short"]
TradeMode = Literal["idea_eval", "position_mgmt"]
TradeSession = Literal["RTH", "ETH"]
Recommendation = Literal["take", "take only on pullback", "scalp only", "flatten", "pass", "unavailable"]
EntryVerdict = Literal["attractive", "fair", "rich", "unavailable"]
TradeVerdict = Literal["favorable", "neutral", "speculative", "avoid", "unavailable"]
LiquidityScore = Literal["good", "acceptable", "weak"]


class OpenPosition(BaseModel):
    symbol: str | None = None
    contracts: int | None = None


class FuturesScalpIdeaRequest(BaseModel):
    symbol: SupportedSymbol
    side: TradeSide
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    contracts: int = Field(ge=1)
    account_size: Literal[50000, 100000, 150000, 250000]
    mode: TradeMode
    session: TradeSession
    realized_pnl_today: float = 0.0
    realized_loss_count_today: int = Field(ge=0)
    open_positions: list[OpenPosition] = Field(default_factory=list)

    @field_validator("stop_price")
    @classmethod
    def validate_stop_side(cls, value: float, info) -> float:
        entry_price = info.data.get("entry_price")
        side = info.data.get("side")
        if entry_price is None or side is None:
            return value
        if side == "long" and value >= entry_price:
            raise ValueError("Long stop_price must be below entry_price")
        if side == "short" and value <= entry_price:
            raise ValueError("Short stop_price must be above entry_price")
        return value

    @field_validator("target_price")
    @classmethod
    def validate_target_side(cls, value: float, info) -> float:
        entry_price = info.data.get("entry_price")
        side = info.data.get("side")
        if entry_price is None or side is None:
            return value
        if side == "long" and value <= entry_price:
            raise ValueError("Long target_price must be above entry_price")
        if side == "short" and value >= entry_price:
            raise ValueError("Short target_price must be below entry_price")
        return value


class RiskRuleViolations(BaseModel):
    per_trade_risk_exceeds_limit: bool
    max_loss_trades_reached: bool
    daily_profit_target_reached: bool


class FuturesScalpAnalysisResponse(BaseModel):
    symbol: str
    side: str
    entry_price: float
    stop_price: float
    target_price: float
    contracts: int
    tick_value: float
    point_value: float
    risk_per_contract: float
    reward_per_contract: float
    rr_ratio: float
    atr_multiple_risk: float
    live_price: float | None
    distance_entry_to_live: float | None
    entry_verdict: EntryVerdict
    trade_verdict: TradeVerdict
    liquidity_score: LiquidityScore
    risk_rule_violations: RiskRuleViolations
    realized_pnl_today: float
    realized_loss_count_today: int
    daily_profit_target: float
    per_trade_risk_limit: float
    per_trade_profit_target: float
    final_recommendation: Recommendation
    final_recommendation_comment: str
    as_of: datetime

