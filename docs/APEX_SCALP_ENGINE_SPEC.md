# Apex Scalp Engine Spec

## Phase 0 Architecture Note

This repository is the existing Futures Scalp Advisor / Futures Scalp Analyzer codebase. Apex Scalp Engine must be built as a modular expansion inside this repo, not as a separate project.

The full implementation spec is stored in `docs/Apex_Scalp_Engine_Expansion.md`. This file is the repo-local architecture and implementation alignment note.

## Current Stack

- Backend framework: FastAPI
- Runtime: Python 3.11+
- Data validation: Pydantic v2
- HTTP client: httpx
- Test runner: pytest
- App entry point: `backend/app.py`
- Main package: `backend/futures_scalp_analyzer`

## Existing Schwab Integration

Schwab market data is implemented in `backend/futures_scalp_analyzer/price_feed.py`.

Key components:

- `PriceFeed`: async read-only abstraction for live price and bars.
- `SchwabQuotePriceFeed`: read-only Schwab quote and price history client.
- `ActiveContractResolver`: resolves and caches active futures contracts.
- `StaticPriceFeed`: in-memory test/development feed.
- `normalize_root_symbol`: maps user-facing futures symbols to Schwab root symbols.

The Schwab client reads access token, refresh token, client ID, client secret, API base URL, and token URL from environment variables. Token refresh is implemented in memory.

No order placement or broker execution path is present.

## Existing Railway Deployment

Railway deployment is configured through `backend/Procfile`:

```text
web: uvicorn app:app --host 0.0.0.0 --port $PORT
```

Runtime dependencies for Railway are listed in `backend/requirements.txt`.

The deployment expects the Railway service root to run from `backend`, where `app:app` resolves to `backend/app.py`.

## Environment Variable Pattern

Environment variables are read directly with `os.getenv` in the modules that need them.

Known Schwab variables:

- `SCHWAB_ACCESS_TOKEN`
- `SCHWAB_REFRESH_TOKEN`
- `SCHWAB_CLIENT_ID`
- `SCHWAB_CLIENT_SECRET`
- `SCHWAB_API_BASE_URL`
- `SCHWAB_TOKEN_URL`

Other external data sources currently use safe fallback behavior when unavailable.

## Current API Surface

`backend/app.py` defines the FastAPI app and endpoints:

- `GET /health`
- `GET /futures/active-contracts`
- `GET /price/{symbol}`
- `GET /futures/session`
- `POST /futures/analyze`
- `POST /futures/position`
- `GET /privacy`

The main analysis path is `analyze_request` in `backend/futures_scalp_analyzer/service.py`.

## Recommended Apex Insertion Points

- Market data pipeline: extend or wrap `PriceFeed` and `SchwabQuotePriceFeed` in `backend/futures_scalp_analyzer/price_feed.py` instead of duplicating Schwab auth.
- Indicator/payload pipeline: add new modules under `backend/futures_scalp_analyzer` unless a future package split is explicitly approved.
- Decision logic: keep technical-only decision functions isolated from news helpers.
- Risk controls: reuse and extend `backend/futures_scalp_analyzer/risk.py` and `backend/futures_scalp_analyzer/session_guard.py`.
- News display: reuse `backend/futures_scalp_analyzer/news_context.py`, including Truth Social / Trump post context if useful, but strip decision fields before any Apex decision payload.
- API endpoints: add new Apex endpoints in `backend/app.py` only after the module-level functions are tested.

## Phase 0 Risks

- Prior Apex scaffold edits exist in the current worktree from earlier work; they should be reviewed before merging.
- Existing news context currently computes a `news_bias` for display fields and can fetch Truth Social / Trump post context. Apex decision logic must not consume either as signal.
- Existing risk templates are prop-account-size based and differ from the new global default risk settings. Phase 1 must define compatibility rather than silently replacing current behavior.
- `docs/api.md` says the Schwab feed is a placeholder, but the current code contains a read-only Schwab quote/history implementation. Documentation should be reconciled in a later doc cleanup.
- No persistent trade log, user model, admin reset, or multi-user risk state exists yet.

## Phase 1 Recommendation

Implement the Phase 1 data pipeline as a small, tested module inside the existing backend package. Reuse the existing `PriceFeed` abstraction and `SchwabQuotePriceFeed`; add `SchwabMarketDataProvider` and `MockMarketDataProvider` around the existing read-only data paths rather than duplicating Schwab authentication.

Phase 1 must provide `build_payload(symbol)` and `generate_trade_decision(payload)`. The payload must include `market_data`, `context`, `risk_settings`, and `timestamp`. The decision engine must be technical-only, risk-first, and return `LONG`, `SHORT`, or `NO TRADE`.

News and Truth Social/social context may appear only under display context. They must not affect recommendation, confidence, trend, bias, risk decision, approval, rejection, or no-trade logic.

Phase 1 should not add dashboard code, authentication, trade logging persistence, broker order placement, or auto-trading.

## Phase 3 Near-Real-Time Data Notes

Phase 3 preserves the `/apex/payload/{symbol}` and `/apex/decision/{symbol}` API envelopes while adding freshness metadata inside `market_data`.

Required freshness fields:

- `data_mode`: `near_real_time`, `mock`, or `unavailable`
- `provider_status`: `connected`, `degraded`, `fallback`, or `unavailable`
- `last_update_time`
- `is_stale`
- `stale_reason`
- `data_gate_status`: `open` or `closed`
- `data_gate_reason`

The current Schwab integration is HTTP quote/history based, so Phase 3 uses safe polling rather than WebSocket streaming. Stale or unavailable data must return `NO TRADE` and must not produce `LONG` or `SHORT`.

Data Gate rules:

- `DATA GATE OPEN` only when provider status is connected, data source is valid, data mode is live or near-real-time, data is not stale, and required market data fields are present.
- `DATA GATE CLOSED` when data is stale, unavailable, malformed, incomplete, or outside the freshness threshold.
- Risk Gate remains separate and reflects account/risk rules only.

Dashboard rules:

- Show data mode, provider status, and last update time near the header.
- Show Data Gate separately from Risk Gate.
- Show `Data Stale - Verify Before Trading` when `is_stale` is true.
- Continue showing `Mock Data - Not Live Market Data` when mock data is used.
- Do not calculate trade decisions in the browser.
- Do not add broker order placement or auto-trading.

## Phase 3A Multi-Timeframe EMA Stack Notes

Phase 3A adds `multi_timeframe_trend` to `/apex/payload/{symbol}` and `/apex/decision/{symbol}`.

Required timeframes:

- `30m`
- `15m`
- `5m`
- `3m`
- `1m`

Each timeframe row includes EMA 9, EMA 21, EMA 50, stack status, trend, price-vs-EMA relationships, last bar time, stale status, and stale reason.

Stack rules:

- `bullish_stack`: EMA 9 > EMA 21 > EMA 50
- `bearish_stack`: EMA 9 < EMA 21 < EMA 50
- `mixed_stack`: anything else

Trend rules:

- `strong_bullish`: price > EMA 9 and bullish stack
- `bullish`: bullish stack but price is not above EMA 9
- `strong_bearish`: price < EMA 9 and bearish stack
- `bearish`: bearish stack but price is not below EMA 9
- `mixed`: EMAs are not clearly stacked

The multi-timeframe panel is context-only in Phase 3A. It must not change the main trade decision rules unless separately approved. News, Truth Social, and social context must not affect multi-timeframe trend.

## Saturday Phase 3 Cleanup Notes

Known futures market closures are handled as a market-session state, not as a Schwab provider failure.

During Saturday/weekend closure:

- Show the Market Closed banner as the primary warning.
- Show `Provider: MARKET CLOSED` when Schwab quote access is reachable but the futures session is closed.
- Keep `Risk Gate` separate from market/data status.
- Keep `Risk Gate` open when risk rules are okay.
- Keep `Data Gate` closed.
- Return `NO TRADE` with `no_trade_reason = market closed`.
- Show the last available quote if Schwab provides one.
- Suppress the red stale-data banner unless the market should be open and an unexpected data/provider problem exists.

The payload includes `data_diagnostics` so Railway responses can be inspected without guessing from the dashboard. Diagnostics include quote status, bar status, bars returned, latest bar time, missing fields, stale reasons, provider status, and Data Gate reason. Secrets and tokens must never be logged or emitted.

## Asset-Class Preparation

The instrument model is prepared for:

- `future`
- `stock`
- `etf`

Futures remain the only asset class currently enabled for Apex trade decisions. Stocks and ETFs are metadata-only until a later approved phase.

Prepared instruments:

- Futures: `/ES`, `/NQ`, `/GC`, `/SI` and the existing futures metadata set.
- ETFs: `SPY`, `QQQ`, `IWM`, `DIA`.
- Stocks: `AAPL`, `MSFT`, `NVDA`, `TSLA`.

Each instrument supports:

- `symbol`
- `display_symbol`
- `provider_symbol`
- `asset_class`
- `exchange`
- `session_type`
- `tick_size`
- `tick_value`
- `point_value`
- `position_unit`

Later equity-specific TODOs:

- equity session handling
- premarket and after-hours handling
- equity VWAP reset
- share-based risk math
- stock/ETF-specific Data Gate rules
- equity Level 2/tape differences
- options support later

## Sunday Open Validation Checklist

Run this between Sunday 6:05 PM and 6:15 PM ET after futures reopen:

- Confirm `Provider` changes from `MARKET CLOSED` to `CONNECTED` or another valid provider status.
- Confirm `Data Gate` opens once fresh bars are available.
- Confirm `Last Update` changes to current market time.
- Confirm VWAP populates.
- Confirm EMA 9 and EMA 20 populate.
- Confirm RSI populates.
- Confirm Session High and Session Low populate.
- Confirm Multi-Timeframe Trend populates for `30m`, `15m`, `5m`, `3m`, and `1m` when enough bars are available.
- Confirm stale warning disappears when data is fresh.
- Confirm `NO TRADE`, `LONG`, or `SHORT` is based only on technical criteria plus data/risk gates.
- Confirm no Schwab order APIs, Tradovate order APIs, or broker order APIs are called.

Do not close Phase 3 until this live Sunday validation confirms fresh bars, indicators, MTF updates, and Data Gate behavior.
