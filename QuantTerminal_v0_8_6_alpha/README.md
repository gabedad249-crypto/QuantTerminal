# Quant Terminal v0.8.5 Alpha

BTC15 research + paper-training terminal.

## v0.8.5 fixes

- Fixed instant open/close bug caused by stale plans or stale BTC15 expiry.
- Paper entries now use the latest live BTC-USD tick at open, not an old plan price.
- Blocks stale LONG/SHORT plans if the live price is already beyond stop/target.
- Enforces one paper trade per BTC15 window so each 15m market gets a fresh read.
- Keeps active trade chart overlay synced every tick.
- Clears the OPEN trade overlay immediately after TP/SL/BTC15 close.
- Pending plans are dashed and labeled `PENDING PLAN — NOT OPEN`.
- Green/red R/R boxes only appear for actual open paper trades.
- Compact R/R zones are smaller and stable.
- FVG boxes draw shorter so they do not stretch across the chart.
- Added EMA continuation filter from the video concept: stop blindly trading reversals; prefer continuation flow unless Max Training Data is intentionally collecting probes.

## How to run

```bat
install.bat
run_quant_terminal.bat
```

## Commit

```bash
git add .
git commit -m "Fix trade lifecycle overlays and add EMA continuation filter"
git push
```


## v0.8.6 Alpha

Trade lifecycle hardening release.

- Fixed open → instant close caused by stale Kalshi snapshot force-close.
- Paper trades now close from their own locked BTC15 expiry timestamp.
- Added a 3 second TP/SL management lock to prevent same-second flicker closes.
- Open trade overlay now stays synced to the account state.
- Green/red R/R zones are more visible and more compact.
- FVG focus boxes draw shorter so they do not stretch across the chart.

Recommended commit:

```bash
git add .
git commit -m "Fix paper trade lifecycle and stable risk reward overlay"
git push
```
