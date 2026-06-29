# Quant Terminal v0.8.0 Alpha

Edge + realism update.

## What changed

- Keeps the **5m bias -> 1m Sweep -> CHoCH -> Displacement -> 1m FVG** model.
- Adds Kalshi odds context to the bot output:
  - YES bid/ask
  - NO bid/ask
  - last price
  - spread quality
  - estimated side entry cents
- Adds learned **edge filters** from Paper Training.
- Adds bad setup blacklist logic after enough outcomes.
- Adds best setup family tracking.
- Adds daily/session report.
- Adds richer paper labels:
  - MFE / MAE
  - Kalshi ticker
  - contract price snapshot
  - contract spread
  - trigger quality
  - CHoCH / sweep / displacement flags
- Adds better active-trade manager notes:
  - expiry warning
  - danger near stop
  - near payout
  - breakeven idea note
- Adds stronger walk-forward replay backtest:
  - one trade max
  - stop / target / BTC15 boundary exits
  - win rate
  - profit factor
  - max drawdown
  - stats by side and grade

## Important

This is still paper training / research. It reads Coinbase BTC-USD candles for chart logic and Kalshi public market info for BTC15 timing/odds context. It does not place real trades.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bat
git add .
git commit -m "Add edge filters kalshi odds context and stronger replay"
git push
```
