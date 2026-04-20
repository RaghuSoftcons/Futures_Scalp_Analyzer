# Futures Scalp Analyzer API

## Overview

`Futures_Scalp_Analyzer` is a standalone REST service for evaluating intraday futures scalp ideas and open positions against prop-firm risk rules.

- No order placement.
- No shared code with any options workflow.
- Schwab live pricing is read-only and isolated behind a local price-feed interface.

## Run

```bash
uvicorn backend.app:app --reload
```

## Endpoints

### `POST /futures/analyze`

Evaluates a futures scalp idea in `idea_eval` mode.

### `POST /futures/position`

Uses the same request schema, forces `mode="position_mgmt"`, and applies flatten-first logic when the position profile becomes asymmetric or daily rules are already hit.

## Request Schema

```json
{
  "symbol": "NQ",
  "side": "long",
  "entry_price": 18250.0,
  "stop_price": 18240.0,
  "target_price": 18270.0,
  "contracts": 1,
  "account_size": 50000,
  "mode": "idea_eval",
  "session": "RTH",
  "realized_pnl_today": 0.0,
  "realized_loss_count_today": 0,
  "open_positions": []
}
```

## Notes

- Supported symbols: `NQ`, `ES`, `CL`, `GC`, `SI`, `ZB`, `UB`
- Account scaling is implemented by `get_account_risk_template(account_size: int)`.
- Final recommendation selection is implemented by `compute_final_recommendation(ctx)`.
- The default `SchwabQuotePriceFeed` is intentionally a local placeholder until a read-only quote bridge is wired into this project.
