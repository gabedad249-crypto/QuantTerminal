# Quant Terminal v0.3.3 Alpha

FVG-focused research and paper-trading terminal.

## What's new

- New **Thinking Checklist** tab next to the chart/decision panel.
- Cleaner chart overlays: fewer GAP boxes by default, no BULL/BEAR spam on every box.
- Grey GAP boxes now show simple status: `GAP`, `TOUCHED`, or `FILLED`.
- Added chart controls:
  - `Clean Chart`
  - `Toggle Filled Gaps`
  - `Toggle H/L`
- BTC15 timer now tries to follow the active Kalshi BTC15 market `close_time`.
  - If Kalshi lookup fails, it clearly falls back to estimated quarter-hour timing.
- FVG method still requires:
  - enough candles
  - 15m/5m trend context
  - FVG/GAP
  - pullback into the GAP
  - engulfing/rejection confirmation
  - RR >= configured minimum

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add thinking panel and Kalshi BTC15 timer"
git push
```

## Note

No chart is literally 100% perfect. This terminal uses Coinbase BTC-USD candles for chart logic and attempts to sync the BTC15 countdown to Kalshi market close_time when available.


## v0.3.3
- Stabilized Decision/Thinking tabs so they do not visually rebuild every tick.
- Cleaner chart defaults: fewer GAP boxes, no swing labels by default, less clutter.
- Better Kalshi BTC15 matching using KXBTC15M series search first.
- Throttled chart/text updates while keeping price and paper P/L live.
