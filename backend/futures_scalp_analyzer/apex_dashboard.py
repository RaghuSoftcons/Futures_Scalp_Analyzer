"""FastAPI-served Apex Scalp Engine dashboard."""

from __future__ import annotations

import json
from html import escape
from typing import Any

from .apex_pipeline import DISPLAY_CONTEXT_RULE, MANUAL_EXECUTION_NOTE


SUPPORTED_DASHBOARD_SYMBOLS = ("NQ", "ES", "GC", "SI")

DISPLAY_LABELS = {
    "symbol": "Symbol",
    "price": "Price",
    "session_high": "Session High",
    "session_low": "Session Low",
    "vwap": "VWAP",
    "ema9": "EMA 9",
    "ema20": "EMA 20",
    "rsi": "RSI",
    "trend": "Trend",
    "data_source": "Data Source",
    "data_mode": "Data Mode",
    "provider_status": "Provider Status",
    "last_update_time": "Last Update",
    "is_stale": "Stale",
    "stale_reason": "Stale Reason",
    "data_gate_status": "Data Gate",
    "reason": "Reason",
    "confidence": "Confidence",
    "risk_status": "Risk Status",
    "no_trade_reason": "No-Trade Reason",
    "manual_execution_note": "Manual Execution Note",
    "max_daily_loss": "Max Daily Loss",
    "max_risk_per_trade": "Max Risk Per Trade",
    "preferred_risk_per_trade": "Preferred Risk Per Trade",
    "minimum_rr_ratio": "Minimum R:R",
    "preferred_rr_ratio": "Preferred R:R",
    "max_trades_per_day": "Max Trades Per Day",
    "max_consecutive_losses": "Max Consecutive Losses",
}


def format_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def format_count(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def decision_display_state(recommendation: str | None) -> dict[str, str]:
    normalized = (recommendation or "NO TRADE").upper()
    if normalized == "LONG":
        return {"label": "LONG", "class_name": "state-long"}
    if normalized == "SHORT":
        return {"label": "SHORT", "class_name": "state-short"}
    return {"label": "NO TRADE", "class_name": "state-none"}


def risk_display_state(risk_status: str | None) -> dict[str, str]:
    if (risk_status or "").lower() == "blocked":
        return {"label": "RISK GATE CLOSED", "class_name": "risk-blocked"}
    return {"label": "RISK GATE OPEN", "class_name": "risk-allowed"}


def data_gate_display_state(data_gate_status: str | None) -> dict[str, str]:
    if (data_gate_status or "").lower() == "open":
        return {"label": "DATA GATE OPEN", "class_name": "data-allowed"}
    return {"label": "DATA GATE CLOSED", "class_name": "data-blocked"}


def validate_dashboard_response(payload: dict[str, Any], decision_response: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("market_data"), dict):
        errors.append("missing market_data")
    if not isinstance(payload.get("context"), dict):
        errors.append("missing context")
    if not isinstance(payload.get("risk_settings"), dict):
        errors.append("missing risk_settings")
    if not isinstance(decision_response.get("decision"), dict):
        errors.append("missing decision")
    return errors


def render_apex_dashboard() -> str:
    symbol_options = "\n".join(
        f'<option value="{escape(symbol)}">/{escape(symbol)}</option>' for symbol in SUPPORTED_DASHBOARD_SYMBOLS
    )
    labels_json = json.dumps(DISPLAY_LABELS, sort_keys=True)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Apex Scalp Engine</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b0f14;
      --panel: #111820;
      --panel-2: #151f29;
      --text: #e8eef5;
      --muted: #8fa2b5;
      --line: #263442;
      --long: #16a36f;
      --short: #d24b5a;
      --none: #d19a38;
      --blocked: #ff5c5c;
      --allowed: #58c48d;
      --focus: #6db7ff;
      --mock: #f2bd45;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 16px;
      line-height: 1.45;
      letter-spacing: 0;
    }}
    button, select, input {{ font: inherit; }}
    .shell {{ max-width: 1480px; margin: 0 auto; padding: 22px; overflow-x: hidden; }}
    .topbar {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: end;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{ margin: 0 0 8px; font-size: 32px; line-height: 1.1; }}
    .subline {{ color: #b8c6d4; font-size: 16px; }}
    .controls {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }}
    select, button, label.toggle {{
      min-height: 42px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 6px;
      padding: 0 12px;
    }}
    button {{ cursor: pointer; }}
    button:focus, select:focus, input:focus {{ outline: 2px solid var(--focus); outline-offset: 2px; }}
    label.toggle {{ display: inline-flex; align-items: center; gap: 8px; }}
    .notice {{
      margin: 18px 0;
      padding: 13px 15px;
      border: 1px solid var(--line);
      background: #101923;
      border-left: 4px solid var(--focus);
      border-radius: 6px;
      color: var(--text);
      font-size: 16px;
    }}
    .mock-warning {{
      display: none;
      margin: -6px 0 18px;
      padding: 13px 15px;
      border: 1px solid rgba(242, 189, 69, .55);
      background: rgba(242, 189, 69, .12);
      border-left: 4px solid var(--mock);
      border-radius: 6px;
      color: #ffe0a3;
      font-weight: 700;
      font-size: 17px;
    }}
    .stale-warning {{
      display: none;
      margin: -6px 0 18px;
      padding: 13px 15px;
      border: 1px solid rgba(255, 92, 92, .6);
      background: rgba(255, 92, 92, .13);
      border-left: 4px solid var(--blocked);
      border-radius: 6px;
      color: #ffc4c4;
      font-weight: 800;
      font-size: 17px;
    }}
    .market-session-warning {{
      display: none;
      margin: -6px 0 18px;
      padding: 13px 15px;
      border: 1px solid rgba(255, 209, 139, .55);
      background: rgba(209, 154, 56, .11);
      border-left: 4px solid var(--none);
      border-radius: 6px;
      color: #ffe0a3;
      font-weight: 800;
      font-size: 17px;
    }}
    .market-session-warning.open {{
      border-color: rgba(88, 196, 141, .35);
      background: rgba(88, 196, 141, .08);
      border-left-color: var(--allowed);
      color: #b9efcf;
    }}
    .status-message {{
      min-height: 20px;
      margin-left: 2px;
      color: var(--muted);
      font-size: 14px;
    }}
    .status-message.error {{ color: #ffb0b0; font-weight: 700; }}
    .quick-status {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      align-items: center;
      margin: 0 0 18px;
      padding: 12px;
      border: 1px solid var(--line);
      background: #0f1720;
      border-radius: 8px;
    }}
    .quick-status-title {{
      color: #c7d4e1;
      font-size: 15px;
      font-weight: 750;
      margin-right: 2px;
    }}
    .quick-chip {{
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      padding: 0 12px;
      border: 1px solid #243545;
      background: #111d28;
      color: #edf4fb;
      border-radius: 999px;
      font-size: 16px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }}
    .quick-chip.strong {{ font-size: 18px; font-weight: 850; }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(280px, 1fr) minmax(320px, 1.1fr);
      gap: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      min-width: 0;
    }}
    .panel h2 {{ margin: 0 0 14px; font-size: 20px; line-height: 1.2; }}
    .metrics {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 11px; }}
    .metric {{
      background: #0e151d;
      border: 1px solid #1f2c38;
      border-radius: 6px;
      padding: 11px;
      min-height: 74px;
    }}
    .metric span {{ display: block; color: #b3c0ce; font-size: 14px; font-weight: 650; margin-bottom: 6px; }}
    .metric strong {{ display: block; font-size: 21px; line-height: 1.22; overflow-wrap: anywhere; }}
    .metric.primary {{ border-color: rgba(109, 183, 255, .45); background: #101b26; }}
    .metric.primary strong {{ font-size: 25px; }}
    .metric.warning {{ border-color: rgba(209, 154, 56, .5); background: rgba(209, 154, 56, .08); }}
    .status-row {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }}
    .badge {{ display: inline-flex; align-items: center; min-height: 40px; padding: 0 15px; border-radius: 999px; font-size: 18px; font-weight: 850; }}
    .state-long {{ background: rgba(22, 163, 111, .16); color: #5ee0aa; border: 1px solid rgba(94, 224, 170, .45); }}
    .state-short {{ background: rgba(210, 75, 90, .16); color: #ff9aa5; border: 1px solid rgba(255, 154, 165, .45); }}
    .state-none {{ background: rgba(209, 154, 56, .14); color: #ffd18b; border: 1px solid rgba(255, 209, 139, .45); }}
    .risk-blocked {{ background: rgba(255, 92, 92, .16); color: #ffb0b0; border: 1px solid rgba(255, 176, 176, .45); }}
    .risk-allowed {{ background: rgba(88, 196, 141, .14); color: #9ee6bd; border: 1px solid rgba(158, 230, 189, .45); }}
    .data-blocked {{ background: rgba(255, 92, 92, .16); color: #ffb0b0; border: 1px solid rgba(255, 176, 176, .45); }}
    .data-allowed {{ background: rgba(109, 183, 255, .14); color: #abd8ff; border: 1px solid rgba(171, 216, 255, .45); }}
    .trend-uptrend {{ color: #5ee0aa; }}
    .trend-downtrend {{ color: #ff9aa5; }}
    .trend-neutral {{ color: #ffd18b; }}
    .context-list {{ display: grid; gap: 10px; }}
    .context-item {{ padding: 12px; border: 1px solid #1f2c38; border-radius: 6px; background: #0e151d; font-size: 16px; }}
    .context-item a {{ color: #8cc8ff; overflow-wrap: anywhere; }}
    .readout {{ display: grid; gap: 10px; }}
    .readout-summary {{
      padding: 14px;
      border: 1px solid rgba(109, 183, 255, .35);
      background: #101b26;
      border-radius: 6px;
      font-size: 18px;
      font-weight: 650;
      line-height: 1.5;
    }}
    .readout-list {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .readout-item {{
      padding: 12px;
      border: 1px solid #1f2c38;
      border-radius: 6px;
      background: #0e151d;
      font-size: 16px;
      line-height: 1.4;
    }}
    .readout-item span {{ display: block; color: #b3c0ce; font-size: 14px; font-weight: 650; margin-bottom: 5px; }}
    .mtf-table {{ display: grid; gap: 8px; }}
    .mtf-row {{
      display: grid;
      grid-template-columns: .7fr 1fr 1fr .9fr .9fr .9fr 1fr;
      gap: 8px;
      align-items: center;
      padding: 10px;
      border: 1px solid #1f2c38;
      border-radius: 6px;
      background: #0e151d;
      font-size: 15px;
    }}
    .mtf-row.header {{ color: #b3c0ce; font-weight: 750; background: transparent; border: 0; padding-top: 0; }}
    .mini-badge {{ display: inline-flex; width: fit-content; padding: 4px 8px; border-radius: 999px; font-size: 13px; font-weight: 800; }}
    .mini-bullish {{ color: #9ee6bd; background: rgba(88, 196, 141, .14); border: 1px solid rgba(158, 230, 189, .35); }}
    .mini-bearish {{ color: #ffb0b0; background: rgba(255, 92, 92, .14); border: 1px solid rgba(255, 176, 176, .35); }}
    .mini-mixed {{ color: #ffd18b; background: rgba(209, 154, 56, .14); border: 1px solid rgba(255, 209, 139, .35); }}
    .mini-stale {{ color: #ffc4c4; background: rgba(255, 92, 92, .18); border: 1px solid rgba(255, 176, 176, .45); }}
    .muted {{ color: var(--muted); }}
    .error {{ color: #ffb0b0; }}
    .wide {{ grid-column: 1 / -1; }}
    @media (max-width: 860px) {{
      .shell {{ padding: 16px; }}
      .topbar, .grid {{ grid-template-columns: 1fr; }}
      .controls {{ justify-content: flex-start; }}
      .metrics, .readout-list {{ grid-template-columns: 1fr; }}
      .mtf-row {{ grid-template-columns: 1fr; }}
      .mtf-row.header {{ display: none; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="topbar">
      <div>
        <h1>Apex Scalp Engine</h1>
        <div class="subline">
          <span id="selected-symbol">/NQ</span> ·
          <span id="current-time">Last Update: Loading...</span> ·
          <span id="data-source">Data Source: Pending</span> ·
          <span id="data-mode">Mode: Pending</span> ·
          <span id="provider-status">Provider: Pending</span>
        </div>
      </div>
      <div class="controls">
        <select id="symbol-select" aria-label="Symbol">{symbol_options}</select>
        <button id="refresh-button" type="button">Refresh</button>
        <label class="toggle"><input id="auto-refresh" type="checkbox"> Auto 8s</label>
        <span id="status-line" class="status-message" aria-live="polite"></span>
      </div>
    </section>

    <div class="notice">{MANUAL_EXECUTION_NOTE}</div>
    <div id="market-session-warning" class="market-session-warning"></div>
    <div id="mock-warning" class="mock-warning">Mock Data &mdash; Not Live Market Data</div>
    <div id="stale-warning" class="stale-warning">Data Stale &mdash; Verify Before Trading</div>
    <div id="quick-status" class="quick-status" aria-label="Quick Status">
      <span class="quick-status-title">Quick Status</span>
      <span class="quick-chip">Loading market state...</span>
    </div>

    <section class="grid">
      <section class="panel">
        <h2>Market Data</h2>
        <div class="metrics" id="market-data"></div>
      </section>

      <section class="panel">
        <h2>Recommendation</h2>
        <div class="status-row">
          <span id="recommendation-badge" class="badge state-none">NO TRADE</span>
          <span id="risk-badge" class="badge risk-allowed">RISK GATE OPEN</span>
          <span id="data-gate-badge" class="badge data-blocked">DATA GATE CLOSED</span>
        </div>
        <div class="metrics" id="decision-data"></div>
      </section>

      <section class="panel wide">
        <h2>Multi-Timeframe Trend</h2>
        <div id="multi-timeframe-trend" class="mtf-table"></div>
      </section>

      <section class="panel wide">
        <h2>Technical Readout</h2>
        <div class="readout" id="technical-readout"></div>
      </section>

      <section class="panel">
        <h2>Risk Settings</h2>
        <div class="metrics" id="risk-settings"></div>
      </section>

      <section class="panel">
        <h2>Display-only Context</h2>
        <div class="notice">{DISPLAY_CONTEXT_RULE}</div>
        <div class="context-list" id="context-list"></div>
      </section>

    </section>
  </main>

  <script>
    const labels = {labels_json};
    const moneyKeys = new Set(["max_daily_loss", "max_risk_per_trade", "preferred_risk_per_trade"]);
    const integerKeys = new Set(["max_trades_per_day", "max_consecutive_losses"]);
    const rrKeys = new Set(["minimum_rr_ratio", "preferred_rr_ratio"]);
    const primaryKeys = new Set(["price", "trend"]);
    const marketKeys = ["symbol", "price", "trend", "vwap", "ema9", "ema20", "rsi", "session_high", "session_low", "data_source"];
    const riskKeys = ["max_daily_loss", "max_risk_per_trade", "preferred_risk_per_trade", "minimum_rr_ratio", "preferred_rr_ratio", "max_trades_per_day", "max_consecutive_losses"];
    let timer = null;

    function fmtMoney(value) {{
      const number = Number(value || 0);
      return "$" + number.toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
    }}

    function prettyTimestamp(value) {{
      if (!value) return "unavailable";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat(undefined, {{
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        timeZone: "America/New_York",
        timeZoneName: "short"
      }}).format(date);
    }}

    function prettyTrend(value) {{
      const trend = String(value || "neutral").toLowerCase();
      if (trend === "uptrend") return "Uptrend";
      if (trend === "downtrend") return "Downtrend";
      return "Neutral";
    }}

    function fmtValue(key, value) {{
      if (value === null || value === undefined || value === "") return "unavailable";
      if (key === "symbol") return String(value).startsWith("/") ? String(value) : "/" + String(value);
      if (key === "timestamp") return prettyTimestamp(value);
      if (key === "last_update_time") return prettyTimestamp(value);
      if (key === "trend") return prettyTrend(value);
      if (key === "data_mode") return String(value).replaceAll("_", " ").toUpperCase();
      if (key === "provider_status") return String(value).replaceAll("_", " ").toUpperCase();
      if (key === "is_stale") return value ? "Yes" : "No";
      if (key === "risk_status") return String(value).toLowerCase() === "blocked" ? "RISK GATE CLOSED" : "RISK GATE OPEN";
      if (key === "data_gate_status") return String(value).toLowerCase() === "open" ? "DATA GATE OPEN" : "DATA GATE CLOSED";
      if (key === "confidence") return Number(value || 0).toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) + "%";
      if (moneyKeys.has(key)) return fmtMoney(value);
      if (integerKeys.has(key)) return String(Number(value || 0).toFixed(0));
      if (rrKeys.has(key)) return Number(value || 0).toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
      if (typeof value === "number") return value.toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
      return String(value);
    }}

    function metric(key, value, options = {{}}) {{
      const label = labels[key] || key;
      const extraClass = options.className || "";
      const valueClass = key === "trend" ? "trend-" + String(value || "neutral").toLowerCase() : "";
      return `<div class="metric ${{extraClass}}"><span>${{label}}</span><strong class="${{valueClass}}">${{fmtValue(key, value)}}</strong></div>`;
    }}

    function badgeClass(recommendation) {{
      if (recommendation === "LONG") return "badge state-long";
      if (recommendation === "SHORT") return "badge state-short";
      return "badge state-none";
    }}

    function riskClass(status) {{
      return status === "blocked" ? "badge risk-blocked" : "badge risk-allowed";
    }}

    function dataGateClass(status) {{
      return status === "open" ? "badge data-allowed" : "badge data-blocked";
    }}

    function renderContext(decision) {{
      const context = decision.display_context || {{}};
      const news = context.news || [];
      const social = context.social || [];
      const items = [];
      for (const item of news) items.push({{...item, kind: "News"}});
      for (const item of social) items.push({{...item, kind: "Social"}});
      if (!items.length) {{
        document.getElementById("context-list").innerHTML = '<div class="context-item muted">No display-only news or social context available.</div>';
        return;
      }}
      document.getElementById("context-list").innerHTML = items.map((item) => {{
        const url = item.url ? `<a href="${{item.url}}" target="_blank" rel="noreferrer">${{item.url}}</a>` : '<span class="muted">no URL</span>';
        return `<div class="context-item"><strong>${{item.kind}}: ${{item.title || "Untitled"}}</strong><div class="muted">${{item.source || "source unavailable"}}</div><div>${{url}}</div></div>`;
      }}).join("");
    }}

    function renderTechnicalReadout(readout) {{
      if (!readout || !readout.summary) {{
        document.getElementById("technical-readout").innerHTML = '<div class="readout-summary muted">Technical readout unavailable.</div>';
        return;
      }}
      const relationships = readout.price_relationships || [];
      const items = [
        ["Price vs VWAP", relationships[0] || "Unavailable."],
        ["Price vs EMA 9", relationships[1] || "Unavailable."],
        ["Price vs EMA 20", relationships[2] || "Unavailable."],
        ["EMA 9 vs EMA 20", readout.moving_average_alignment || "Unavailable."],
        ["RSI Comment", readout.rsi_comment || "Unavailable."],
        ["Trend Comment", readout.trend_comment || "Unavailable."],
        ["Decision Comment", readout.decision_comment || "Unavailable."]
      ];
      document.getElementById("technical-readout").innerHTML = `
        <div class="readout-summary">${{readout.summary}}</div>
        <div class="readout-list">
          ${{items.map(([label, text]) => `<div class="readout-item"><span>${{label}}</span>${{text}}</div>`).join("")}}
        </div>
      `;
    }}

    function labelize(value) {{
      return String(value || "unavailable").replaceAll("_", " ").replace(/\\b\\w/g, (char) => char.toUpperCase());
    }}

    function trendMiniClass(value) {{
      const normalized = String(value || "").toLowerCase();
      if (normalized.includes("stale")) return "mini-badge mini-stale";
      if (normalized.includes("bullish")) return "mini-badge mini-bullish";
      if (normalized.includes("bearish")) return "mini-badge mini-bearish";
      return "mini-badge mini-mixed";
    }}

    function stackMiniClass(value) {{
      const normalized = String(value || "").toLowerCase();
      if (normalized === "bullish_stack") return "mini-badge mini-bullish";
      if (normalized === "bearish_stack") return "mini-badge mini-bearish";
      return "mini-badge mini-mixed";
    }}

    function renderMultiTimeframeTrend(mtf, marketSession = {{}}) {{
      const container = document.getElementById("multi-timeframe-trend");
      if (!mtf || !mtf.timeframes) {{
        container.innerHTML = '<div class="context-item muted">Multi-timeframe trend unavailable.</div>';
        return;
      }}
      const order = ["30m", "15m", "5m", "3m", "1m"];
      const isMarketClosed = marketSession.status === "closed" || marketSession.status === "maintenance";
      const rows = order.map((timeframe) => {{
        const row = mtf.timeframes[timeframe] || {{}};
        const trendText = isMarketClosed ? "Market Closed" : (row.is_stale ? "Stale" : labelize(row.trend));
        const stackText = isMarketClosed ? "Market Closed" : (row.is_stale ? "Stale" : labelize(row.ema_stack_status));
        return `
          <div class="mtf-row">
            <strong>${{timeframe}}</strong>
            <span class="${{trendMiniClass(trendText)}}">${{trendText}}</span>
            <span class="${{stackMiniClass(row.is_stale ? "stale" : row.ema_stack_status)}}">${{stackText}}</span>
            <span>${{labelize(row.price_vs_ema9)}}</span>
            <span>${{labelize(row.price_vs_ema21)}}</span>
            <span>${{labelize(row.price_vs_ema50)}}</span>
            <span>${{row.last_bar_time ? prettyTimestamp(row.last_bar_time) : (row.stale_reason || "Unavailable")}}</span>
          </div>
        `;
      }}).join("");
      container.innerHTML = `
        <div class="readout-summary">${{mtf.alignment_summary || "Multi-timeframe trend unavailable."}}</div>
        <div class="mtf-row header">
          <span>Timeframe</span><span>Trend</span><span>EMA Stack</span><span>Price vs EMA 9</span><span>Price vs EMA 21</span><span>Price vs EMA 50</span><span>Last Bar</span>
        </div>
        ${{rows}}
      `;
    }}

    function renderQuickStatus(market, decision, readout, marketSession = {{}}) {{
      const relationships = readout.price_relationships || [];
      const mtf = window.currentMultiTimeframeTrend || {{}};
      const recommendation = decision.recommendation || "NO TRADE";
      const riskStatus = decision.risk_status || "allowed";
      const dataGateStatus = decision.data_gate_status || market.data_gate_status || "closed";
      const riskText = riskStatus === "blocked" ? "RISK GATE CLOSED" : "RISK GATE OPEN";
      const dataGateText = dataGateStatus === "open" ? "DATA GATE OPEN" : "DATA GATE CLOSED";
      const mtfRows = Object.values(mtf.timeframes || {{}});
      const mtfText = marketSession.status === "closed" || marketSession.status === "maintenance" ? "MTF: Market Closed" : (mtfRows.some((row) => row && row.is_stale) ? "MTF: Stale" : "MTF: " + labelize(mtf.dominant_trend || "mixed"));
      const trendText = prettyTrend(market.trend || "neutral").toUpperCase();
      const items = [
        [recommendation, "strong"],
        [riskText, "strong"],
        [dataGateText, "strong"],
        [mtfText, "strong"],
        [trendText, "strong"],
        [relationships[0] || "Price vs VWAP unavailable.", ""],
        [relationships[1] || "Price vs EMA 9 unavailable.", ""],
        [relationships[2] || "Price vs EMA 20 unavailable.", ""]
      ];
      document.getElementById("quick-status").innerHTML = `
        <span class="quick-status-title">Quick Status</span>
        ${{items.map(([text, className]) => `<span class="quick-chip ${{className}}">${{String(text).replace(/\\.$/, "")}}</span>`).join("")}}
      `;
    }}

    async function refreshDashboard() {{
      const symbol = document.getElementById("symbol-select").value;
      document.getElementById("status-line").textContent = "Loading " + symbol + "...";
      try {{
        const [payloadResponse, decisionResponse] = await Promise.all([
          fetch(`/apex/payload/${{symbol}}`),
          fetch(`/apex/decision/${{symbol}}`)
        ]);
        if (!payloadResponse.ok || !decisionResponse.ok) throw new Error("API unavailable");
        const payload = await payloadResponse.json();
        const decisionEnvelope = await decisionResponse.json();
        const market = payload.market_data || {{}};
        const marketSession = payload.market_session || {{}};
        window.currentMultiTimeframeTrend = payload.multi_timeframe_trend || {{}};
        const decision = decisionEnvelope.decision || {{}};
        const technicalReadout = decisionEnvelope.technical_readout || {{}};
        if (!payload.market_data || !payload.context || !payload.risk_settings || !decisionEnvelope.decision) {{
          throw new Error("Malformed dashboard response");
        }}

        document.getElementById("selected-symbol").textContent = "/" + symbol;
        document.getElementById("current-time").textContent = "Last Update: " + prettyTimestamp(market.last_update_time || market.timestamp || decisionEnvelope.timestamp || payload.timestamp || new Date().toISOString());
        document.getElementById("data-source").textContent = "Data Source: " + fmtValue("data_source", market.data_source || "unavailable");
        document.getElementById("data-mode").textContent = "Mode: " + fmtValue("data_mode", market.data_mode || "unavailable");
        const isKnownMarketClosure = marketSession.status === "closed" || marketSession.status === "maintenance" || decision.no_trade_reason === "market closed";
        const providerDisplay = isKnownMarketClosure && market.data_source === "schwab" ? "MARKET CLOSED" : fmtValue("provider_status", market.provider_status || "unavailable");
        document.getElementById("provider-status").textContent = "Provider: " + providerDisplay;
        document.getElementById("mock-warning").style.display = market.data_source === "mock" ? "block" : "none";
        const sessionWarning = document.getElementById("market-session-warning");
        if (marketSession.message) {{
          sessionWarning.style.display = "block";
          sessionWarning.className = marketSession.status === "open" ? "market-session-warning open" : "market-session-warning";
          sessionWarning.textContent = marketSession.message + (marketSession.current_time_et ? " Current ET: " + marketSession.current_time_et : "");
        }} else {{
          sessionWarning.style.display = "none";
          sessionWarning.textContent = "";
        }}
        const staleWarning = document.getElementById("stale-warning");
        staleWarning.style.display = market.is_stale && !isKnownMarketClosure ? "block" : "none";
        staleWarning.textContent = market.stale_reason ? "Data Stale — Verify Before Trading: " + market.stale_reason : "Data Stale — Verify Before Trading";
        document.getElementById("market-data").innerHTML = marketKeys.map((key) => metric(key, market[key], {{ className: primaryKeys.has(key) ? "primary" : "" }})).join("");
        document.getElementById("risk-settings").innerHTML = riskKeys.map((key) => metric(key, payload.risk_settings[key])).join("");

        const recommendation = decision.recommendation || "NO TRADE";
        const riskStatus = decision.risk_status || "allowed";
        const recBadge = document.getElementById("recommendation-badge");
        recBadge.className = badgeClass(recommendation);
        recBadge.textContent = recommendation;
        const riskBadge = document.getElementById("risk-badge");
        riskBadge.className = riskClass(riskStatus);
        riskBadge.textContent = riskStatus === "blocked" ? "RISK GATE CLOSED" : "RISK GATE OPEN";
        const dataGateStatus = decision.data_gate_status || market.data_gate_status || "closed";
        const dataGateBadge = document.getElementById("data-gate-badge");
        dataGateBadge.className = dataGateClass(dataGateStatus);
        dataGateBadge.textContent = dataGateStatus === "open" ? "DATA GATE OPEN" : "DATA GATE CLOSED";

        document.getElementById("decision-data").innerHTML = [
          metric("reason", decision.reason),
          metric("confidence", decision.confidence, {{ className: "primary" }}),
          metric("risk_status", decision.risk_status, {{ className: riskStatus === "blocked" ? "warning" : "" }}),
          metric("data_gate_status", dataGateStatus, {{ className: dataGateStatus === "open" ? "" : "warning" }}),
          metric("no_trade_reason", decision.no_trade_reason || "none", {{ className: recommendation === "NO TRADE" ? "warning" : "" }}),
          metric("manual_execution_note", decision.manual_execution_note)
        ].join("");
        renderMultiTimeframeTrend(payload.multi_timeframe_trend || {{}}, marketSession);
        renderTechnicalReadout(technicalReadout);
        renderQuickStatus(market, decision, technicalReadout, marketSession);
        renderContext(decision);
        document.getElementById("status-line").textContent = "Updated";
        document.getElementById("status-line").className = "status-message";
      }} catch (error) {{
        document.getElementById("status-line").textContent = error.message || "Dashboard error";
        document.getElementById("status-line").className = "status-message error";
      }}
    }}

    document.getElementById("refresh-button").addEventListener("click", refreshDashboard);
    document.getElementById("symbol-select").addEventListener("change", refreshDashboard);
    document.getElementById("auto-refresh").addEventListener("change", (event) => {{
      if (timer) clearInterval(timer);
      timer = event.target.checked ? setInterval(refreshDashboard, 8000) : null;
    }});
    refreshDashboard();
  </script>
</body>
</html>"""
