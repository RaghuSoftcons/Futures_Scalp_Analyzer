# Futures Scalp Analyzer

AI-powered futures scalp analysis API for **NQ, ES, CL, GC, SI, ZB, UB** (plus micro variants), built for fast discretionary decision support with prop-firm guardrails.

## Project Overview

Futures Scalp Analyzer combines:
- live market data (Schwab)
- technical context (EMA/VWAP/RSI + structure)
- multi-timeframe trend bias
- optional news + macro event awareness
- account/session risk controls
- GPT-friendly response fields for concise actionable verdicts

The result is a structured response containing a final recommendation, entry/stop/target context, and risk-first warnings.

## Architecture

- **Backend**: FastAPI service (Python) deployable to Railway.
- **Frontend**: ChatGPT Custom GPT that sends user inputs to this backend.
- **Data integrations**:
  - Schwab market data API (live quote + candles)
  - Finnhub (optional): news headlines + economic calendar
  - Truth Social public Mastodon-compatible endpoint for recent post context

## Core Features

1. **Multi-timeframe bias engine (1m/3m/5m/15m)**
   - Computes per-timeframe bias (`long`, `short`, `neutral`) from EMA9/EMA20 + VWAP + RSI.
   - Produces a 4-timeframe alignment state (`aligned_long`, `aligned_short`, `mixed`, `neutral`).

2. **News & geopolitical context (optional)**
   - Pulls recent Truth Social posts (last ~4 hours).
   - Pulls Finnhub top recent headlines (last ~2 hours, top 5) when API key is present.
   - Returns `news_bias`, note, post count, recent posts, and top headlines.

3. **Economic calendar awareness (optional)**
   - Pulls high-impact events from Finnhub economic calendar.
   - Symbol relevance mapping by market (index, oil, metals, treasury).
   - Event timing gates:
     - warning window: **15 minutes**
     - block window: **5 minutes**
   - Returns warning/block flags and next event context.

4. **Session kill switch + daily loss enforcement**
   - Session guard uses a **3% daily loss cap** of account size.
   - `warning` at 75% consumed, `locked` at breach.
   - Lock state returns early and prevents trade approval.

5. **GPT-powered output contract**
   - Provides verdict (`GO` / `WAIT` / `NO GO` / `STOP TRADING`), rationale, and watch-outs.
   - Includes entry, stop, target, and risk/reward formatting suitable for ChatGPT display.

## Environment Variables

Required:
- `SCHWAB_API_KEY`
- `SCHWAB_SECRET`
- `OPENAI_API_KEY`

Optional:
- `FINNHUB_API_KEY` (enables headlines + economic calendar logic)

> If `FINNHUB_API_KEY` is not set, the service uses safe defaults and continues without crashing.

## Running Locally

```bash
pip install -e .[dev]
uvicorn backend.app:app --reload --port 8000
```

## Using Through ChatGPT Custom GPT

1. Configure your Custom GPT Action to call this service endpoint (`/futures/analyze` and optionally `/futures/position`).
2. In ChatGPT, provide:
   - symbol (e.g. `NQ`)
   - side (`long`/`short`)
   - account size
   - optional entry/stop/target and current PnL/loss count
3. GPT receives structured fields and should synthesize:
   - verdict and recommendation
   - why the setup is favored/not favored
   - key watch-outs (including event/news/session risk notes)

## Response Field Reference

| Field | Type | Description |
|---|---|---|
| `symbol`, `side`, `direction` | string | Trade instrument and directional intent |
| `entry_price`, `stop_price`, `target_price` | float | Evaluated trade levels |
| `risk_per_contract`, `reward_per_contract`, `rr_ratio` | float | Core risk/reward metrics |
| `final_recommendation` | string | Engine recommendation (`take`, `pass`, etc.) |
| `verdict` | string | GPT-ready action framing (`GO`, `WAIT`, etc.) |
| `bias_1m`, `bias_3m`, `bias_5m`, `bias_15m` | string | Timeframe-level directional bias |
| `timeframe_alignment` | string | Combined alignment status across 4 frames |
| `news_bias`, `news_bias_note` | string | Summarized directional read from news/posts |
| `trump_posts_count` | int | Number of recent posts captured |
| `trump_posts_recent` | list[string] | Recent post snippets |
| `top_headlines` | list[string] | Recent Finnhub headlines |
| `economic_event_warning` | bool | True when within warning window |
| `economic_event_block` | bool | True when within block window |
| `next_economic_event` | string | Next relevant event title |
| `daily_loss_pct` | float | % of daily loss cap consumed |
| `daily_loss_limit_pct` | float | Configured max daily loss percent (3.0) |
| `session_status` | string | Current session state |
| `watch_out_for`, `why` | string | Human-readable tactical guidance |

## Notes

- All external calls use short timeouts and fallback behavior.
- The system is designed for execution discipline; it is not financial advice.
