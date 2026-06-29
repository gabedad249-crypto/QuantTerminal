# Quant Terminal v0.7.2 Alpha

## What changed

This release is focused on making the bot actually take paper-training plays while staying logical.

### Added
- TradersNotes-style entry model: **5m bias → 1m FVG execution**.
- Paper-training probe mode so the bot can collect outcomes instead of waiting all day for perfect A+ setups.
- Looser but still guarded entry logic:
  - 35 candle warmup
  - 35 second BTC15 safety window
  - 5m FVG bias can guide direction
  - 1m momentum/displacement can confirm B-grade paper probes
- Better labels saved to memory:
  - entry model
  - 5m bias
  - trigger quality
  - training probe flag
- AI / Thinking now shows model, bias, trigger quality, and probe status.

### Still protected
- One open trade max.
- One focused GAP at a time.
- No real money execution.
- BTC15 expiry closes paper trades.
- Recommend Only still does not paper trade.

## Run

```bat
python -m app.main
```

## Commit

```bat
git add .
git commit -m "Add 5m to 1m entry model and paper training probes"
git push
```
