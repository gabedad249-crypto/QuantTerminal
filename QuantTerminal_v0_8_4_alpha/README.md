# Quant Terminal v0.8.4 Alpha

Paper-mode BTC15 research terminal. No real-money automation.

## What changed in v0.8.4

- Professional resizable UI overhaul.
- Right-side AI / Thinking + paper controls now fills the full right side.
- Drag splitters to resize watchlist, chart, journal, AI panel, and planner.
- Compact risk/reward visual box on chart.
- Green/red zones no longer stretch across the whole chart.
- Stop/target lines sit on the edges of the compact red/green boxes.
- Live paper P/L is cash-scaled:
  - target hit = configured target payout USD
  - stop hit = configured stop loss USD
  - live payout moves between those values every tick
- SHORT/DOWN P/L now updates correctly when BTC moves down.
- Stop/target chart distances are based on recent BTC volatility, not buy-in percentage.
- More Trades now waits a few closed candles before opening paper.
- Max Training Data still enters faster, but still waits for a fresh read.
- Each BTC15 window resets GAP locks and starts a fresh read.

## Install / run

```bat
install.bat
run_quant_terminal.bat
```

## Commit

```bash
git add .
git commit -m "Add pro UI cash scaled payout and compact risk zones"
git push
```
