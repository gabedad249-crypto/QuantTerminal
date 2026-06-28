# Quant Terminal v0.4.1 Alpha

Major fixes/features:
- LONG/SHORT engine can auto-plan either direction based on FVG + confirmation logic.
- Open paper trades now expire at the active BTC15 market end.
- Live price/P&L line is shown on the chart while a paper trade is open.
- Paper trade open uses Kalshi close time as `expires_at` when available.
- Self auto-tune runs conservatively in the background when enough paper outcomes exist.
- Scroll panels preserve scroll position better instead of snapping.

Notes:
- LONG = buy/up idea.
- SHORT = sell/down idea.
- Paper trading is simulation only.
- Kalshi sync still depends on what the public Kalshi endpoints/page expose to your PC.


## v0.4.1 hotfix
- Fixes startup crash from audit panel text updater.
- Adds Signal Timeline tab for step-by-step setup reasoning.
- Makes key text panels scroll-safe to reduce snap-back.
- Keeps v0.4.0 features: BTC15 paper expiry, live P/L chart, self auto-tune.
