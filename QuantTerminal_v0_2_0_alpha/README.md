# Quant Terminal v0.2.0 Alpha

This build replaces the bad placeholder chart with a QGraphicsView chart engine.

## Run

Double-click `run_quant_terminal.bat`.

## What changed

- Rewritten chart engine
- Mouse wheel zoom should actually change candle density
- Drag-pan across candles
- Crosshair price readout
- Cleaner candle sizing
- Shorter FVG boxes
- Range high / range low lines
- Swing high / swing low labels
- Entry / stop / target lines still sync with the paper planner
- Order panel spinboxes no longer hijack scrolling unless focused

## Next

The next build should add the auto FVG confirmation scanner: impulse -> FVG -> retrace -> engulfing/rejection -> planned paper trade.
