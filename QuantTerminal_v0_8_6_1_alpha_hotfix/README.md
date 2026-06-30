# Quant Terminal v0.8.6.1 Alpha Hotfix

Fixes the pop-trade bug where a trade could open, flash on the chart, then instantly disappear and show “No open paper trade.”

## Fixed
- Removed stale Kalshi snapshot force-close from the UI timer.
- Paper trades now close only from their locked BTC15 expiry, target, stop, or explicit force close.
- Active trade overlay and Paper Trading state stay synced.
- Green/red trade boxes only disappear after the account actually closes the trade.
- Exit reason now shows `LOCKED_BTC15_END` when the locked 15m window ends.

## Commit
```bash
git add .
git commit -m "Fix stale Kalshi timer pop trade close"
git push
```
