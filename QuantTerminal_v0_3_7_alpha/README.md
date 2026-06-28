# Quant Terminal v0.3.7 Alpha

Focus: paper journal / trade audit and exact Kalshi URL timer fallback.

## Run

```bat
run_quant_terminal.bat
```

## Added

- Paper Journal / Trade Audit tab
- Trade IDs for every paper trade
- Verified win/loss audit lines
- P/L formula shown for closed trades
- Wins are only TARGET or positive final P/L
- Losses are STOP or non-positive final P/L
- Kalshi BTC15 timer can parse the exact pasted URL ticker, e.g. `KXBTC15M-26JUN280030`
- Timer source now shows `URL_TICKER`, `KALSHI`, or `ESTIMATED`

## Long / Short

- LONG = buy / up idea. Wins when price goes up to target.
- SHORT = sell / down idea. Wins when price drops to target.

For Kalshi thinking:
- LONG roughly maps to UP / YES-style ideas.
- SHORT roughly maps to DOWN / NO-style ideas.

## Commit

```bat
git add .
git commit -m "Add paper journal audit and exact Kalshi timer"
git push
```
