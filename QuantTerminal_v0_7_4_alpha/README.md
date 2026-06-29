# Quant Terminal v0.7.4 Alpha

CHoCH entry model update.

## What changed

- Renamed the entry logic around the correct concept: **Sweep is not CHoCH**.
- Added separate detection for:
  - liquidity sweep
  - CHoCH / Change of Character
  - displacement candle
  - 1m FVG execution
- Stronger A-grade entries now prefer: `5m bias -> 1m pullback -> Sweep -> CHoCH -> Displacement -> 1m FVG`.
- Paper-training probes can still fire with looser conditions so the bot collects trade data.
- AI / Thinking and Logic Coach now show the trigger sequence.
- Memory saves sweep / CHoCH / displacement labels so Recommend Only can learn which model works better.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add CHoCH sweep displacement entry model"
git push
```


## v0.7.4 Alpha

Trade-frequency update:
- Adds Training Speed: Strict Quality, More Trades, Max Training Data.
- More Trades is the default so Paper Training actually collects outcomes.
- Max Training Data can take labeled scout probes when no clean CHoCH/FVG appears.
- Scout probes are saved separately in memory so they do not pretend to be perfect A-grade setups.
- Keeps one open trade max, BTC15 expiry close, and no hunting while a paper trade is active.
