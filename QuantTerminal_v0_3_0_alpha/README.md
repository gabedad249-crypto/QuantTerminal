# Quant Terminal v0.3.0 Alpha

FVG Confirmation Engine build.

## What changed
- Loads recent Coinbase 1-minute historical candles on startup so the chart/AI has real context instead of starting empty.
- Adds a real FVG confirmation checklist:
  - 15m/5m trend context
  - impulse/displacement
  - aligned FVG
  - pullback into the FVG
  - engulfing or rejection confirmation
  - RR >= 2.0
- Buy-in suggestions are now blocked unless the full setup is confirmed.
- AI panel explains why it is waiting instead of randomly suggesting entries.
- Paper account/trade stats update automatically when TP or SL is hit.
- Recent closed paper trades show in the Paper Trading tab.

## Run
Double click:

```bat
run_quant_terminal.bat
```

## Git commit
```bat
git add .
git commit -m "Add FVG confirmation engine"
git push
```
