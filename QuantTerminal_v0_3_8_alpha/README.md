# Quant Terminal v0.3.8 Alpha

FVG confirmation research and paper-trading terminal.

## What changed

- Kalshi BTC15 timer now defaults to the category page sync:
  `https://kalshi.com/category/crypto/btc?frequency=fifteen_min`
- Exact stale market URLs are no longer trusted after they expire.
- Kalshi Debug now shows candidate count and source.
- Added Backtest / Replay tab.
- Added Memory Stats tab.
- Added Export Paper Report.
- Kept paper trade audit with true TP/SL P/L checks.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add backtest replay memory stats and category Kalshi sync"
git push
```

## Notes

If the Kalshi timer is still off, paste the category URL into the Kalshi Debug tab and click **Sync this Kalshi URL**:

```text
https://kalshi.com/category/crypto/btc?frequency=fifteen_min
```

Then check the source line:

- `KALSHI_ACTIVE` = synced from active open KXBTC15M market.
- `URL_TICKER` = exact market URL, only if still active.
- `ESTIMATED` = fallback only.
