# Apex Scalp Engine Dashboard

## Overview

The Phase 2 dashboard is served by the existing FastAPI app at:

```text
/apex/dashboard
```

It consumes the Phase 1 API endpoints:

```text
GET /apex/payload/{symbol}
GET /apex/decision/{symbol}
```

The dashboard does not calculate EMA, RSI, VWAP, trend, risk status, or trade decisions. It displays the API responses from the Phase 1 backend.

## Run Locally

From the repo root:

```bash
uvicorn backend.app:app --reload --port 8000
```

Open:

```text
http://127.0.0.1:8000/apex/dashboard
```

No new dashboard-specific environment variables are required.

## Environment Variables

The dashboard uses the same backend environment as the existing app. Schwab data remains read-only and uses the existing Schwab environment variables when available:

- `SCHWAB_ACCESS_TOKEN`
- `SCHWAB_REFRESH_TOKEN`
- `SCHWAB_CLIENT_ID`
- `SCHWAB_CLIENT_SECRET`
- `SCHWAB_API_BASE_URL`
- `SCHWAB_TOKEN_URL`

If Schwab data is unavailable, the Apex payload can fall back to mock data and marks `data_source` accordingly.

When `data_source` is `mock`, the dashboard shows a visible warning:

```text
Mock Data - Not Live Market Data
```

The Phase 3 payload also includes freshness fields:

- `data_mode`: `near_real_time`, `mock`, or `unavailable`
- `provider_status`: `connected`, `degraded`, `fallback`, or `unavailable`
- `last_update_time`
- `is_stale`
- `stale_reason`

If `is_stale` is true, the dashboard shows:

```text
Data Stale - Verify Before Trading
```

## Refresh Behavior

The dashboard includes:

- Manual refresh button
- Optional auto-refresh every 8 seconds

The dashboard avoids excessive polling and makes one payload request plus one decision request per refresh. Successful refreshes use only a small subtle status message near the controls. Errors remain visible near the refresh controls instead of using a permanent bottom status panel. Phase 3 uses safe HTTP polling through the existing API endpoints; no browser WebSocket or broker order connection is added.

## Quick Status Bar

The dashboard shows a compact Quick Status Bar below the manual execution and mock-data notices. It displays:

- Recommendation
- Risk Status, displayed as `RISK GATE OPEN` or `RISK GATE CLOSED`
- Trend
- Price vs VWAP
- Price vs EMA 9
- Price vs EMA 20

The Quick Status Bar uses the backend decision and technical readout. It does not use news, Truth Social, social context, sentiment, or bias.

## Manual Execution Rule

The dashboard displays this disclaimer:

```text
Manual execution only. No broker order has been placed.
```

The dashboard does not place trades, route orders, call Schwab order APIs, or call Tradovate order APIs.

## Display-only Context Rule

News and Truth Social/social context are labeled:

```text
Display only. Not used in trade decisions.
```

The dashboard does not add sentiment scoring, bias scoring, or any context-based decision logic.

## Manual Validation Checklist

1. Start the API with `uvicorn backend.app:app --reload --port 8000`.
2. Open `http://127.0.0.1:8000/apex/dashboard`.
3. Confirm the page loads without crashing.
4. Confirm the header shows Apex Scalp Engine, selected symbol, Eastern last update time, data source, data mode, provider status, and manual execution disclaimer.
5. Confirm the Market Data panel does not include a duplicate Timestamp card.
6. Confirm field labels are user-friendly, such as `Session High`, `EMA 9`, `Risk Status`, and `Max Daily Loss`.
7. Confirm dollar values show two decimals, count values show whole numbers, and confidence shows as a percent.
8. Confirm `NO TRADE`, `LONG`, `SHORT`, `RISK GATE OPEN`, and `RISK GATE CLOSED` states are visually distinct when returned by the API.
9. Confirm mock data shows the mock-data warning when applicable.
10. Confirm stale data shows the stale-data warning when applicable.
11. Confirm the Quick Status Bar is visible without scrolling and summarizes recommendation, risk, trend, and price relationships.
12. Confirm there is no permanent bottom Status panel during normal operation.
13. Confirm news/social context appears only in the display-only panel.
14. Confirm no order-entry controls or broker action buttons are present.
15. Confirm the dashboard is readable at 100% browser zoom without needing to zoom in.
16. Confirm larger fonts do not create horizontal scrolling on a normal desktop-width browser window.
