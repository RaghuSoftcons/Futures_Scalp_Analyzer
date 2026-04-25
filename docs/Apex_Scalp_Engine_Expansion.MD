# Apex Scalp Engine — Codex Implementation Spec

## Project Context

You are working inside the existing **Futures Scalp Advisor** project folder/repository.

This is **not** a brand-new project and **not** a separate repo.

The existing project already has:

- Schwab data integration
- Railway deployment configuration
- Existing environment variable handling
- Existing trade-evaluation logic
- Existing project structure that must be preserved
- Codex access to the current project folder

The new work is an expansion of this project under the broader platform name:

# Apex Scalp Engine

Apex Scalp Engine is a professional, multi-user futures scalping decision-support system. It provides trade ideas, execution levels, risk controls, and trader accountability.

All trades are executed manually by users outside the system, such as in Tradovate.

---

## Critical Rules

1. Do **not** rewrite the existing app from scratch.
2. Do **not** create a separate disconnected project.
3. Do **not** remove or break the existing Schwab integration.
4. Do **not** remove or break Railway deployment files.
5. Do **not** add auto-trading.
6. Do **not** place live orders.
7. Do **not** use news for trade decisions.
8. News must be display-only.
9. Build one phase at a time.
10. After each phase, provide a summary of files changed, tests run, and remaining risks.
11. Risk control must be enforced before a trade recommendation is shown.
12. All numeric dollar values must be displayed with 2 decimals.

---

## Recommended Repo / Folder Strategy

Use the existing **Futures Scalp Advisor** repo.

Do **not** create a new folder or new repo unless explicitly instructed.

Create a new git branch before making changes:

```bash
git checkout -b feature/apex-scalp-engine-phase-1
```

Add the new Apex Scalp Engine code in a modular way.

Preferred structure:

```text
docs/
  APEX_SCALP_ENGINE_SPEC.md

apex_scalp_engine/
  __init__.py
  data/
  indicators/
  decision_engine/
  risk/
  dashboard/
  tests/
```

If the existing repo already has a better structure, adapt to it, but do not scatter new code randomly across unrelated files.

---

## Required First Step

Before coding, inspect the existing project and report:

1. Current framework/backend stack
2. Current Schwab integration files
3. Current Railway deployment files
4. Current environment variable pattern
5. Current app entry point
6. Recommended insertion points for Apex Scalp Engine
7. Any risks before implementation

Do not implement Phase 1 until this inspection is complete.

---

## Master Objective

Build Apex Scalp Engine as a modular extension of Futures Scalp Advisor.

The system must eventually support:

- Live Schwab-based market data where available
- Structured futures scalping recommendations
- Manual execution plans
- Risk control and prop-firm discipline
- Streamlit or web dashboard
- Display-only news
- Multi-user support for employee traders
- Admin monitoring
- Trade logging
- Rule violation tracking

---

# Global Business Rules

## 1. News Rule

News is display-only.

Truth Social / Trump post context may be included as display-only social/news context.

News must never be used in:

- recommendation direction
- sentiment score
- bias score
- confidence score
- trade approval
- trade rejection
- risk filtering
- lockout decisions

Allowed news output:

```json
{
  "news": [
    {
      "title": "string",
      "source": "string",
      "url": "string"
    }
  ]
}
```

Maximum 5 headlines.

The 5-item limit applies to the combined list of headlines and Truth Social/social posts.

No sentiment analysis.

No news-based bias.

No news-based trade filtering.

No Truth Social-based trade filtering.

---

## 2. Manual Execution Rule

The system must never execute trades automatically.

The system may only provide:

- setup idea
- direction
- entry zone
- stop loss
- targets
- risk
- reward
- R:R
- contract sizing
- manual execution notes

Users manually execute trades in Tradovate or another trading platform.

The system may show a message such as:

> Manual execution only. Review the plan and place the order manually in your trading platform.

---

## 3. Risk Control Rule

Risk control must be enforced before trade recommendation output.

If a trade violates risk settings, return `NO TRADE`.

Default risk settings:

```json
{
  "max_daily_loss": 2000.00,
  "max_risk_per_trade": 500.00,
  "preferred_risk_per_trade": 300.00,
  "minimum_rr_ratio": 2.00,
  "preferred_rr_ratio": 3.00,
  "max_trades_per_day": 5,
  "max_consecutive_losses": 3
}
```

If a user hits a risk limit, the system should not physically block trading in Tradovate because all execution is manual and external.

Instead, the system must:

- stop showing new trade recommendations
- display `LOCKED OUT`
- explain the rule violation
- log the violation
- require admin reset if multi-user controls are enabled

---

# Phase 0 — Project Alignment

## Goal

Prepare the existing Futures Scalp Advisor project for the Apex Scalp Engine expansion.

## Tasks

1. Inspect the repo.
2. Identify existing Schwab service/module.
3. Identify existing Railway config.
4. Identify existing API/web app entry point.
5. Create or update:

```text
docs/APEX_SCALP_ENGINE_SPEC.md
```

6. Create or update:

```text
AGENTS.md
```

`AGENTS.md` should include the permanent rules for this project:

- preserve Schwab integration
- preserve Railway deployment
- no auto-trading
- news display-only
- build one phase at a time
- risk control first
- use 2 decimals for numeric output
- document all changes

## Acceptance Criteria

Phase 0 is complete only when:

1. The repo has been inspected.
2. A short architecture note is added to `docs/APEX_SCALP_ENGINE_SPEC.md`.
3. `AGENTS.md` exists or has been updated.
4. No existing functionality is broken.
5. No live-order or execution logic is added.
6. Codex stops and reports findings before Phase 1 begins.

---

# Phase 1 — Data Pipeline

Start Phase 1 inside the existing Futures Scalp Advisor repo.

Do not create a new repo.
Do not create a disconnected project.
Do not break existing Schwab integration.
Do not break Railway deployment.
Do not remove or rewrite existing Futures Scalp Advisor functionality.
Do not add auto-trading.
Do not place broker orders.
Stop after Phase 1 and report results before moving to Phase 2.

## Goal

Build the structured data pipeline and technical-only decision engine for Apex Scalp Engine.

## Core Work

1. Reuse existing Schwab market data where practical.
2. Add a clean market data provider abstraction.
3. Add a mock provider fallback for local/testing use.
4. Build `build_payload(symbol)`.
5. Build `generate_trade_decision(payload)`.
6. Add EMA9, EMA20, VWAP, RSI, and trend classification.
7. Include news and Truth Social/social context only as display-only context.
8. Ensure news/social context never affects recommendation, confidence, trend, bias, risk decision, approval, rejection, or no-trade logic.
9. Check risk before showing any trade recommendation.
10. Add unit tests.

## Provider Requirements

Create a `MarketDataProvider` abstraction with:

```python
class MarketDataProvider:
    def get_quote(self, symbol: str) -> dict:
        pass

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> list[dict]:
        pass
```

Implement:

- `SchwabMarketDataProvider`
- `MockMarketDataProvider`

Use the existing Schwab code where possible. Do not duplicate Schwab authentication logic if it already exists.

## Provider Priority

1. Use Schwab provider when valid market data is available.
2. Use Mock provider only when Schwab is unavailable, incomplete, or running tests.
3. Clearly label `data_source` as `schwab`, `mock`, or `unavailable`.

## Build Payload

Create:

```python
build_payload(symbol: str) -> dict
```

`build_payload(symbol)` must return:

- `market_data`
- `context`
- `risk_settings`
- `timestamp`

Required `market_data` fields:

- `symbol`
- `price`
- `session_high`
- `session_low`
- `vwap`
- `ema9`
- `ema20`
- `rsi`
- `trend`
- `data_source`
- `timestamp`

Required `context` fields:

- `news`
- `social`
- `context_rule = Display only. Not used in trade decisions.`

## Risk Settings Defaults

```json
{
  "max_daily_loss": 2000.00,
  "max_risk_per_trade": 500.00,
  "preferred_risk_per_trade": 300.00,
  "minimum_rr_ratio": 2.00,
  "preferred_rr_ratio": 3.00,
  "max_trades_per_day": 5,
  "max_consecutive_losses": 3
}
```

## Indicator Rules

- EMA9 = close-based EMA, period 9.
- EMA20 = close-based EMA, period 20.
- RSI = close-based RSI, period 14.
- VWAP = session VWAP using `sum(price * volume) / sum(volume)`.

Trend classification:

- `uptrend` when price > VWAP and EMA9 > EMA20
- `downtrend` when price < VWAP and EMA9 < EMA20
- otherwise `neutral`

## Generate Trade Decision

Create:

```python
generate_trade_decision(payload: dict) -> dict
```

`generate_trade_decision(payload)` must return:

- `recommendation`: `LONG`, `SHORT`, or `NO TRADE`
- `reason`: `technical only`
- `confidence`
- `risk_status`: `allowed` or `blocked`
- `no_trade_reason`
- `manual_execution_note`
- `display_context` with news and social

Every decision output must include:

```text
Manual execution only. No broker order has been placed.
```

## Phase 1 Decision Logic

Keep the logic simple and technical-only.

Return `LONG` only if:

- trend = `uptrend`
- price > VWAP
- EMA9 > EMA20
- RSI >= 50
- RSI <= 70
- risk_status = `allowed`

Return `SHORT` only if:

- trend = `downtrend`
- price < VWAP
- EMA9 < EMA20
- RSI >= 30
- RSI <= 50
- risk_status = `allowed`

Otherwise return:

```text
NO TRADE
```

News and Truth Social/social context must not affect this decision.

## Risk Rule

Risk must be checked before showing a recommendation.

If risk check fails, return:

- `recommendation = NO TRADE`
- `risk_status = blocked`
- `no_trade_reason = risk rule violated`
- `manual_execution_note = Manual execution only. No broker order has been placed.`

## Manual Execution Rule

The system must not execute trades.
The system must not place orders.
The system must not call Schwab order APIs.
The system must not call Tradovate order APIs.

## Unit Tests Required

1. EMA calculation
2. RSI calculation
3. VWAP calculation
4. Trend classification
5. Mock provider fallback
6. `build_payload("NQ")` returns valid structured JSON
7. `generate_trade_decision(payload)` returns valid decision JSON
8. News does not affect decision
9. Truth Social/social context does not affect decision
10. `NO TRADE` behavior
11. Risk-blocked behavior
12. Existing behavior is not broken

## Phase 1 Acceptance Criteria

Phase 1 is complete only when:

1. `build_payload("NQ")` returns valid structured JSON.
2. `generate_trade_decision(payload)` returns `LONG`, `SHORT`, or `NO TRADE`.
3. News appears only as display context.
4. Truth Social/social context appears only as display context.
5. News/social context does not affect trade decisions.
6. Risk rules can block a recommendation.
7. Schwab provider is reused where practical.
8. Mock provider works as fallback.
9. Existing Schwab integration is preserved.
10. Existing Railway deployment is preserved.
11. Existing Futures Scalp Advisor behavior is preserved.
12. Tests are added and run.
13. Test results are reported.
14. Codex stops before Phase 2.

## Required Final Phase 1 Report

After completing Phase 1, report:

1. Files created
2. Files modified
3. Existing Schwab integration reused
4. Mock provider behavior
5. Example output from `build_payload("NQ")`
6. Example output from `generate_trade_decision(payload)`
7. Tests added
8. Tests run
9. Test results
10. Any blockers or risks
11. Recommended next steps for Phase 2

---

# Phase 2 — Dashboard

Do not implement Phase 2 until Phase 1 is complete and reviewed.

## Goal

Create a clean dashboard for displaying market data, recommendation status, display-only news, and risk/trade stats.

## Preferred UI

Use the existing project UI framework if one already exists.

If not, use Streamlit.

## Layout

### Left Panel

Display:

- symbol
- price
- VWAP
- EMA9
- EMA20
- RSI
- trend
- session high
- session low
- data source

### Right Top

Display:

- recommendation
- reason
- confidence
- no-trade reason if applicable

### Right Middle

Display:

- news headlines
- source
- URL

News must be labeled:

```text
Display only — not used in trade decision.
```

### Right Bottom

Display:

- daily P/L
- trades taken
- remaining daily loss room
- risk state
- lockout status

## Requirements

- Auto refresh every 5 to 10 seconds
- Dark theme
- Clean layout
- No auto-trading buttons
- No live-order placement
- Manual execution disclaimer

---

# Phase 3 — Real-Time Data

Do not implement Phase 3 until Phase 2 is complete and reviewed.

## Goal

Add real-time or near-real-time data updates.

## Requirements

- Use WebSocket if available
- Use polling fallback if WebSocket is unavailable
- Update:
  - price
  - session high
  - session low
  - VWAP
  - EMA
  - RSI
  - trend

## Technical Requirements

- Async or threading allowed
- Auto reconnect
- Graceful degradation if data provider fails
- Clear display of data source status

---

# Phase 4 — Order Flow Display

Do not implement Phase 4 until Phase 3 is complete and reviewed.

## Goal

Display order-flow information if data source supports it.

## DOM Display

Show top 10 levels if available:

- bid price
- bid size
- ask price
- ask size

## Tape Display

Show:

- price
- size
- time
- side

## Detection

Display-only detection for:

- imbalance
- absorption
- large orders

## Rule

Order flow is display-only until separately approved for decision logic.

Do not add order-flow-based trade decisions unless explicitly instructed.

---

# Phase 5 — Setup Detection

Do not implement Phase 5 until Phase 4 is complete and reviewed.

## Goal

Detect common futures scalping setups.

## Setups

Detect:

- VWAP pullback
- EMA reclaim
- liquidity sweep
- breakout
- failed breakout
- continuation pullback

## Output

```json
{
  "setup_detected": true,
  "setup_type": "VWAP_PULLBACK",
  "confidence": 0,
  "reason": "string"
}
```

## Rules

- Require confluence
- Avoid single-indicator signals
- Prefer no trade when structure is unclear
- Do not use news
- Do not auto-execute

---

# Phase 6 — Execution Mode: Manual Only

Do not implement Phase 6 until Phase 5 is complete and reviewed.

## Goal

Generate a precise manual trade plan.

## Conditions

Generate an execution plan only if:

- `setup_detected = true`
- `confidence >= 75`
- R:R is at least 2.00
- risk per trade is within configured user limit
- user is not locked out by daily risk rules

## Output

```json
{
  "direction": "LONG | SHORT",
  "entry": 0.00,
  "entry_zone_low": 0.00,
  "entry_zone_high": 0.00,
  "stop_loss": 0.00,
  "target_1": 0.00,
  "target_2": 0.00,
  "risk_per_contract": 0.00,
  "max_loss": 0.00,
  "max_profit_target_1": 0.00,
  "max_profit_target_2": 0.00,
  "rr_ratio_target_1": 0.00,
  "rr_ratio_target_2": 0.00,
  "contracts": 1,
  "manual_execution_note": "Manual execution only. Place the trade manually in Tradovate if accepted."
}
```

## Rules

- Entry should be near VWAP, EMA, or structure.
- Stop must be beyond invalidation.
- Target must be at least 2R.
- Prefer 3R when market structure supports it.
- Position sizing must be based on risk.
- Max loss must always be shown.
- Max profit must always be shown.
- Do not generate a trade if risk is too high.
- Do not generate a trade if R:R is poor.

## Fail Conditions

Return `NO TRADE` if:

- no setup
- confidence below threshold
- risk too high
- poor R:R
- daily loss limit reached
- max trades reached
- max consecutive losses reached
- data unavailable
- structure unclear

## Critical Rule

No auto execution.

No broker order placement.

No Tradovate order placement.

No Schwab order placement.

Manual execution only.

---

# Phase 7 — Alert System

Do not implement Phase 7 until Phase 6 is complete and reviewed.

## Goal

Notify users when a setup or key level condition occurs.

## Triggers

- setup detected
- price hits VWAP
- price hits EMA zone
- price hits prior high/low
- price hits planned entry zone
- user lockout triggered

## Alert Types

- dashboard notification
- sound
- optional email
- optional push notification later

## Cooldown

Default cooldown:

```text
30 seconds
```

Do not spam alerts.

---

# Phase 8 — Multi-User System

Do not implement Phase 8 until Phase 7 is complete and reviewed.

## Goal

Support multiple traders, including employees.

## Features

1. Authentication
   - username/password
   - secure password hashing

2. User Profiles
   - account size
   - risk limits
   - max daily loss
   - max trades
   - max consecutive losses

3. Trade Logging
   - recommendation
   - user action
   - result
   - timestamp
   - symbol
   - direction
   - risk
   - reward
   - notes

4. Rule Enforcement
   - block new recommendations if daily loss hit
   - block new recommendations if max losses reached
   - block new recommendations if risk exceeded
   - display locked-out status

5. Roles
   - Admin
   - Trader

6. Admin Dashboard
   - view users
   - monitor performance
   - track violations
   - reset lockout status
   - review trade history

7. Database
   - SQLite acceptable for development
   - PostgreSQL preferred for Railway production

---

## Minimum Database Tables

Create these tables when Phase 8 begins:

```text
users
user_profiles
trade_recommendations
user_trade_actions
daily_risk_state
violations
audit_log
```

## Suggested Table Purpose

### users

Stores login and role information.

### user_profiles

Stores risk settings and account-level configuration.

### trade_recommendations

Stores system-generated trade ideas.

### user_trade_actions

Stores whether the user accepted, ignored, rejected, or manually executed a trade.

### daily_risk_state

Stores daily P/L, number of trades, and lockout status.

### violations

Stores risk-rule violations or attempted rule violations.

### audit_log

Stores administrative and system events.

---

# Execution Environment

Trades are manually executed using:

```text
Tradovate
```

The system role is to:

- provide setups
- provide execution levels
- enforce discipline inside the recommendation workflow
- log activity
- support trader accountability

The system role is not to:

- execute trades
- route orders
- place live broker orders
- bypass risk rules

---

# Required Output Formatting

All dollar values must show 2 decimals.

Example:

```text
Max Loss: $300.00
Max Profit: $900.00
R:R: 3.00
```

All JSON outputs must use valid JSON formatting.

All internal calculations should be tested.

---

# Final Instruction to Codex

Start with **Phase 0 only**.

After Phase 0, stop and report:

1. What you found
2. What files you changed
3. How the existing Schwab integration works
4. How Railway deployment is configured
5. Recommended Phase 1 implementation plan
6. Any blockers or risks

Do not proceed to Phase 1 until instructed.

Build one phase at a time.

Do not create a new project.

Do not break the existing Futures Scalp Advisor app.

Do not add auto-trading.

Do not use news for trade decisions.

END OF SPEC
