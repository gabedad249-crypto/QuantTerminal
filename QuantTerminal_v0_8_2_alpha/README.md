# Quant Terminal v0.8.2 Alpha

BTC/Kalshi paper-training terminal.

## What changed in v0.8.2

- Added **Feed Accuracy / Data Health** tab.
- Shows candle source: Coinbase BTC-USD 1m OHLC.
- Shows live feed source: Coinbase WS, REST fallback, or SIM warning.
- Shows last tick age, last candle age, Kalshi timer source, odds age, and stale-data warnings.
- Added candlestick hover reader on the chart.
- Hover finished candles to see OHLC, body/range, wick sizes, and pattern read.
- Added rule-based candlestick knowledge for patterns like engulfing, doji, hammer/pin bar, shooting star, harami/inside bar, morning/evening star, tweezers, soldiers/crows, etc.
- Latest candle read is now included in AI / Thinking / Coach panels.
- Live paper payout is now visible in Paper Trading and Active Trade decision view.
- Target and stop lines now stay visible on the chart even when far away.
- Green transparent zone = target/payout side.
- Red transparent zone = stop/risk side.
- Zones meet at the buy-in/entry line.

## Candle source / accuracy

The chart reads Coinbase Exchange BTC-USD candles. Kalshi is used for BTC15 timer and contract odds context. The app still does not place real trades.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bash
git add .
git commit -m "Add data health candle reader and payout zones"
git push
```
