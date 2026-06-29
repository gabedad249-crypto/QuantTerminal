# Quant Terminal v0.7.0 Alpha

FVG-focused paper-training and recommendation terminal.

## What changed in v0.7.0

This release tightens the core logic instead of adding clutter.

- Clean state machine: `SCANNING → FOUND_GAP → WAIT_PULLBACK → WAIT_CONFIRMATION → READY_CHECK → READY → IN_TRADE → LEARNING`.
- One focused GAP at a time. The bot locks onto one GAP/FVG until it confirms, fills, expires, or invalidates.
- Invalidation rules: filled GAP, expired GAP, trend flip against the focus, price too far away, or BTC15 time safety failure.
- Direction lock: after a focused UP/LONG or DOWN/SHORT setup is selected, it does not flip every candle unless invalidated.
- Active trade state: when a paper trade is open, the logic engine pauses new entries and only manages stop/target/BTC15 expiry.
- Better trade manager text: hold/watch, danger near stop, near target, or expiry soon.
- Richer paper-training labels saved to memory: trend, confirmation, GAP key/status, session, confidence, grade, time left, impulse score, GAP quality, cash RR.
- Recommend Only uses trained paper-trade memory and never opens paper trades.
- UI cleanup: removed duplicate Planned buy-in/stop/target rows from the control panel. Chart lines show those visually.
- Clean numeric inputs: stop/payout/filter fields no longer show extra suffix words inside the box.

## Planner controls

- Buy-in USD = fake position size.
- Stop loss USD = cash risk. Example: `0.50` means fifty cents.
- Target payout USD = cash goal.
- Ratio = target payout USD ÷ stop loss USD.
- Min setup RR filter = quality threshold auto-tune can adjust.

## Modes

### Paper Training
The bot can auto-open paper trades only when the FVG state reaches READY. Completed paper outcomes are saved to memory.

### Recommend Only
The bot does not open paper trades. It uses what it learned from Paper Training to recommend when to buy in, where the stop is, and where the payout target is.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add clean state machine gap lifecycle and richer training labels"
git push
```
