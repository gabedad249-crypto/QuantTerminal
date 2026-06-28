# Quant Terminal v0.3.9 Alpha

FVG-focused BTC paper-trading terminal.

## What's new in v0.3.9

- Better Kalshi BTC15 sync:
  - uses Kalshi/server HTTP time instead of only your PC clock
  - tries to parse the active `KXBTC15M` ticker from the Kalshi BTC 15m category page
  - then falls back to the public market API
  - then falls back to a server-time quarter-hour estimate
- Similarity scoring:
  - compares the current FVG setup against learned paper trade outcomes
  - shows matches, similar win rate, average P/L, and memory score
- Safe Auto-Tune:
  - requires 20+ closed paper trades
  - adjusts minimum RR slowly based on paper-trade results
  - blocks tuning when sample size is too small
- Trade reasons now store FVG context for better future memory.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add similarity scoring auto tune and better Kalshi sync"
git push
```

## Notes

Kalshi timer sources:

- `KALSHI_CATEGORY` = active ticker parsed from Kalshi BTC 15m category page
- `KALSHI_ACTIVE` = nearest open KXBTC15M from public market API
- `KALSHI_EXACT` = exact pasted market URL still active
- `SERVER_ESTIMATE` = fallback using server-time quarter-hour estimate

If your phone and PC still disagree, open **Kalshi Debug** and send the source, matched ticker, close time, server clock offset, and last error.
