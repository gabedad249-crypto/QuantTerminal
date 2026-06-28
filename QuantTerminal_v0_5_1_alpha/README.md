# Quant Terminal v0.5.1 Alpha

Focus: general logic tightening for paper-training mode.

## Added / changed
- Removed the first three watchlist rows (BTC-USD, BTC Up/Down %, ETH-USD).
- Watchlist is now pure navigation: Paper Trading, Journal, Signals, Timeline, Learning, Memory, Backtests, Kalshi, Logs.
- Removed manual trade workflow from the UI. The strategy decides direction and timing.
- Added Mode: Paper Training (auto paper) vs Recommend Only (alerts).
- Buy-in amount is controlled in USD and used for auto paper trades.
- Stop loss % and Target RR update the planned buy-in/stop/target dynamically.
- During an active paper trade, the Decision/Thinking panels switch to ACTIVE PAPER TRADE — WATCHING and stop looking for new trades.
- Resizable layout using draggable splitters for watchlist/chart/AI panels.
- Auto UP/DOWN: strategy can choose LONG/up or SHORT/down based on chart setup.

## Notes
Long = buy/up. Short = down/sell.
For Kalshi thinking, LONG maps to an up/YES-style idea and SHORT maps to a down/NO-style idea.

## Commit
```bash
git add .
git commit -m "Tighten paper training logic and resizable UI"
git push
```
