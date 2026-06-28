# Quant Terminal v0.6.3 Alpha

FVG-focused paper-training and recommendation terminal.

## What changed in v0.6.3

- Fixed the RR display not showing clearly.
- Added an always-visible **Live RR** line beside the paper controls.
- RR now updates even before a valid setup exists.
- AI / Thinking panels show **Configured Cash RR** at all times.
- Kept cash-based planning:
  `RR = target payout USD / stop loss USD`.

Example:

```text
Buy-in USD: $20.00
Stop loss USD: $0.50
Target payout USD: $1.00
RR: 2.00:1
```

## Important

The strategy decides **when** and **direction**: UP/LONG or DOWN/SHORT.

Your controls decide sizing:

- Buy-in USD = fake position size
- Stop loss USD = cash risk
- Target payout USD = cash goal
- Live RR = payout ÷ stop loss
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
git commit -m "Fix always visible cash RR display"
git push
```
