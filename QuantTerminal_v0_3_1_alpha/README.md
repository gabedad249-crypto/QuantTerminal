# Quant Terminal v0.3.1 Alpha

FVG-focused research + paper trading terminal.

## Run

```bat
run_quant_terminal.bat
```

## New in v0.3.1

- Grey FVG boxes labeled `GAP`
- GAP boxes show bullish/bearish direction and filled/touched status
- Learning Mode tab
- Learning snapshots saved to `memory/learning_snapshots.jsonl`
- Paper trade outcomes saved to `memory/paper_trade_outcomes.jsonl`
- AI panel still only suggests a buy-in after the full FVG confirmation checklist:
  - 15m/5m trend context
  - impulse/FVG
  - retrace into FVG
  - engulfing/rejection confirmation
  - RR >= 2

## Notes

This is still alpha. The chart is improving, but the next big technical milestone is making the chart engine feel closer to TradingView and adding historical similarity scoring from the learning files.
