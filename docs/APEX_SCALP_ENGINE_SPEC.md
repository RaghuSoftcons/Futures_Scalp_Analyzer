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

The current Schwab integration is HTTP quote/history based, so Phase 3 uses safe polling rather than WebSocket streaming. Stale or unavailable data must return `NO TRADE` and must not produce `LONG` or `SHORT`.

Dashboard rules:

- Show data mode, provider status, and last update time near the header.
- Show `Data Stale - Verify Before Trading` when `is_stale` is true.
- Continue showing `Mock Data - Not Live Market Data` when mock data is used.
- Do not calculate trade decisions in the browser.
- Do not add broker order placement or auto-trading.
