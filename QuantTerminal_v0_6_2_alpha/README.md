# Quant Terminal v0.6.2 Alpha

FVG-focused paper-training and recommendation terminal.

## What changed in v0.6.2

- Replaced typed **Target RR** with **Target payout USD**.
- You can now type cents like `0.50` for a fifty-cent stop or payout.
- **Stop loss USD** and **Target payout USD** dynamically rebuild the chart plan.
- RR is now calculated live from cash math:
  `RR = target payout / stop loss`.
- AI / Thinking panels now show the dynamic plan math based on:
  - Buy-in USD
  - Stop loss USD
  - Target payout USD
  - Planned entry / stop / target price
- Chart dragging also updates the cash stop, payout, and RR label.
- Kept the v0.6 logic engine: state machine, one GAP focus, confidence breakdown, setup clustering, and safer auto-tune.

## Important

The strategy still decides **when** and **direction**: UP/LONG or DOWN/SHORT.

Your controls decide the paper plan sizing:

- Buy-in USD = fake position size
- Stop loss USD = how much cash you are willing to lose
- Target payout USD = how much cash you want to make
- RR = payout ÷ stop loss

Example:

```text
Buy-in USD: $20.00
Stop loss USD: $0.50
Target payout USD: $1.00
RR: 2.00:1
```

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
git commit -m "Add cash payout based RR planning"
git push
```
