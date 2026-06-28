# Quant Terminal v0.6.0 Alpha

FVG-focused paper-training and recommendation terminal.

## What changed in v0.6.0

- Added a real **state machine** for the FVG method:
  `BUILDING_CONTEXT -> WAIT_TREND -> WAIT_FVG -> WAIT_PULLBACK -> WAIT_CONFIRMATION -> WAIT_RR -> READY`.
- Added **confidence breakdown** so the score is built from actual logic instead of a random number.
- Added **Logic Coach** panel.
- Added richer **setup signatures** so Paper Training results can train Recommend Only mode.
- Added **setup clustering**: the memory engine groups similar setups and shows win rate / average P&L.
- Added stricter **safety rules**:
  - one open trade max
  - one plan per GAP
  - no buy-in unless the state reaches READY
  - BTC15 expiry closes paper trades
  - auto-tune only makes tiny threshold changes after enough closed paper trades
- Auto-tune now needs 50+ closed paper trades before applying changes.

## Modes

### Paper Training
The bot can auto-open paper trades only when the FVG checklist reaches READY. Completed paper outcomes are saved to memory.

### Recommend Only
The bot does not open trades. It uses what it learned from Paper Training to recommend when to buy in, where the stop is, and where the target is.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add state machine logic coach and setup clustering"
git push
```
