# Quant Terminal v0.8.3 Alpha

Paper-training BTC15 research terminal.

## v0.8.3 changes

- Live payout/P&L updates are refreshed directly from the open paper trade every tick.
- Paper Trading tab now shows a clear OPEN TRADE ACTIVE indicator.
- Stop/target risk zones are visually capped so they do not cover the whole chart.
- Actual target and stop lines still stay visible at the edge if the real value is off-screen.
- Candle hover card now only appears when the mouse is actually on a candle body or wick.
- Added Save paper settings button for buy-in, stop loss, target payout, min RR, mode, training speed, and auto-paper.
- Saved paper settings reload on app start.
- New BTC15 window clears per-window GAP locks and forces a fresh read.
- Paper Training waits for setup confirmation candles before auto-opening, depending on training speed:
  - Strict Quality: waits 2 closed candles
  - More Trades: waits 1 closed candle
  - Max Training Data: no extra wait
- Open paper trades still force-close on target, stop, or BTC15 expiry.

## Run

```bash
python -m app.main
```

## Commit

```bash
git add .
git commit -m "Fix live payout hover zones and saved paper settings"
git push
```
