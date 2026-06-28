# Quant Terminal v0.6.4 Alpha

FVG-focused paper-training and recommendation terminal.

## What changed in v0.6.4

- Removed the extra **Live RR** row.
- The existing **Ratio** row now updates live while typing.
- Values like `0.50` are parsed instantly as fifty cents.
- Stop loss USD and Target payout USD now update the chart plan without waiting for Enter/focus loss.
- AI / Thinking updates from the same cash math:
  `RR = target payout USD / stop loss USD`.

Example:

```text
Buy-in USD: $20.00
Stop loss USD: $0.50
Target payout USD: $1.00
Ratio: RR 2.00:1
```

## Important

The strategy decides **when** and **direction**: UP/LONG or DOWN/SHORT.

Your controls decide sizing:

- Buy-in USD = fake position size
- Stop loss USD = cash risk
- Target payout USD = cash goal
- Ratio = payout ÷ stop loss
- Min setup RR filter = quality threshold the bot/autotune uses

## Modes

### Paper Training
The bot can auto-open paper trades only when the FVG checklist reaches READY. Completed paper outcomes are saved to memory.

### Recommend Only
The bot does not open trades. It uses what it learned from Paper Training to recommend when to buy in, where the stop is, and where the payout target is.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Fix live ratio cash input updates"
git push
```
