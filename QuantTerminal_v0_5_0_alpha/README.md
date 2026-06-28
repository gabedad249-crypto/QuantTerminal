# Quant Terminal v0.5.0 Alpha

FVG-focused BTC paper-trading research terminal.

## Run

```bat
run_quant_terminal.bat
```

## v0.5.0 changes

- Chart polish pass: fewer GAP boxes, focused GAP highlight, less label clutter.
- One-plan-per-FVG lifecycle: the engine focuses one GAP at a time and will not spam repeated plans from the same FVG.
- Watchlist navigation now changes the bottom tab.
- BTC15 Up/Down % tracker added in the top bar.
- Better paper panel updates with stable scrolling.
- Conservative self auto-tune remains active and uses learned paper-trade outcomes.

## Notes

LONG = buy/up. SHORT = sell/down. The app can evaluate both directions, but it only plans after the FVG confirmation checklist passes.
