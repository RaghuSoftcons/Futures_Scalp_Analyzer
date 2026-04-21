"""Pydantic request and response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


SupportedSymbol = Literal["NQ", "ES", "CL", "GC", "SI", "ZB", "UB", "MNQ", "MES", "MCL", "MGC", "SIL"]
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


class RiskRuleViolations(BaseModel):
    per_trade_risk_exceeds_limit: bool = False
    max_loss_trades_reached: bool = False
    daily_profit_target_reached: bool = False


class FuturesScalpIdeaRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    symbol: SupportedSymbol
    side: TradeSide | None = Field(default=None, validation_alias=AliasChoices("side", "direction"))
    entry_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    contracts: int = Field(default=1, ge=1)
    account_size: Literal[50000, 100000, 150000, 250000]
    mode: TradeMode = "idea_eval"
    session: TradeSession = "RTH"
    realized_pnl_today: float = Field(default=0.0, validation_alias=AliasChoices("realized_pnl_today", "pnl_today"))
    realized_loss_count_today: int = Field(default=0, ge=0, validation_alias=AliasChoices("realized_loss_count_today", "loss_count_today"))
    open_positions: list[OpenPosition] = Field(default_factory=list)

    @field_validator("account_size", mode="before")
    @classmethod
    def coerce_account_size(cls, v: object) -> int:
        return int(v)


class FuturesScalpAnalysisResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    symbol: SupportedSymbol
    side: TradeSide
    direction: str
    requested_side: TradeSide | None = None
    auto_selected: bool = False
    evaluated_sides: list[TradeSide] = Field(default_factory=list)
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    contracts: int | None = None
    tick_value: float | None = None
    point_value: float | None = None
    risk_per_contract: float | None = None
    reward_per_contract: float | None = None
    rr_ratio: float | str | None = None
    atr_multiple_risk: float | None = None
    live_price: float | None = None
    distance_entry_to_live: float | None = None
    entry_verdict: EntryVerdict
    trade_verdict: TradeVerdict
    liquidity_score: LiquidityScore
    risk_rule_violations: RiskRuleViolations = Field(default_factory=RiskRuleViolations)
    realized_pnl_today: float = 0.0
    realized_loss_count_today: int = 0
    daily_profit_target: float = 0.0
    daily_loss_limit: float = 0.0
    per_trade_risk_limit: float = 0.0
    per_trade_profit_target: float = 0.0
    active_contract: str = ""
    verdict: str
    entry_zone: str
    stop_loss: str
    target: str
    rr_ratio_display: str
    why: str
    watch_out_for: str
    account_summary: str
    session_status: str
    final_recommendation: Recommendation
    final_recommendation_comment: str
    directional_score: float = 0.0
    momentum_bias: str = "neutral"
    bias_1m: str = "neutral"
    bias_3m: str = "neutral"
    bias_5m: str = "neutral"
    bias_15m: str = "neutral"
    timeframe_alignment: str = "neutral"
    news_bias: str = "neutral"
    news_bias_note: str = ""
    trump_posts_count: int = 0
    trump_posts_recent: list[str] = Field(default_factory=list)
    top_headlines: list[str] = Field(default_factory=list)
    economic_event_warning: bool = False
    economic_event_block: bool = False
    next_economic_event: str = ""
    economic_events_today: list[str] = Field(default_factory=list)
    economic_warning_message: str = ""
    daily_loss_pct: float = 0.0
    daily_loss_limit_pct: float = 3.0
    ema9: float | str | None = None
    ema20: float | str | None = None
    vwap: float | str | None = None
    rsi: float | str | None = None
    live_atr: float | str | None = None
    volume_ratio: float | None = None
    trend: str | None = None
    market_structure: str | None = None
    vwap_position: str | None = None
    rsi_condition: str | None = None
    volume_condition: str | None = None
    session_high: float | str | None = None
    session_low: float | str | None = None
    prior_day_high: float | str | None = None
    prior_day_low: float | str | None = None
    market_data_available: bool = False
    as_of: datetime | None = None
    analysis_long: str = ""
    analysis_short: str = ""
