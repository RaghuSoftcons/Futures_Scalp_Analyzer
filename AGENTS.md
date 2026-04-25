# AGENTS

- This system is a futures scalping engine (NOT swing trading)
- Priority = execution timing over signal confirmation
- Prefer more trades with controlled risk over fewer perfect trades
- Preserve the existing Schwab integration; do not duplicate or remove Schwab auth/data code.
- Preserve Railway deployment files and assumptions.
- Do not add auto-trading, broker order placement, or live-order routing.
- News is display-only and must not affect trade direction, confidence, approval, rejection, or risk decisions.
- Build Apex Scalp Engine one phase at a time and stop for review after each phase.
- Enforce risk controls before showing any trade recommendation.
- Display numeric dollar values with 2 decimals.
- Document files changed, tests run, and remaining risks after every phase.
