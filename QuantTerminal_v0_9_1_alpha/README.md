# Quant Terminal v0.9.1 Alpha

Paper-training BTC15 chart reader.

## What changed in v0.9.1

- Fixed the real reason AUTO PLAN READY could spam without opening paper trades.
- Auto-entry now uses a stable setup key instead of live entry/stop/target prices.
- The read-confirmation counter no longer resets every tick.
- Auto-open signature is written only after a paper trade actually opens.
- More Trades now waits 1 closed candle, then opens if safe.
- Scalp Heavy / Max Training can open immediately after READY.
- More Trades cap increased to 3 trades per BTC15 window.
- Scalp Heavy cap increased to 8 trades per BTC15 window.
- Cooldowns are shorter for scalp/data collection.
- Keeps one open trade max and avoids new reads while active.

## TradingView note

TradingView paper trading cannot be controlled directly by this local app without a proper broker/API bridge. For now, Quant Terminal uses Coinbase BTC-USD candles for chart reading and Kalshi BTC15 context for the timer/market. A future version can add TradingView-style alerts/export so you can manually mirror signals into TradingView paper trading.

## Recommended test

Mode: Paper Training
Training Speed: More Trades first
Buy-in: $20
Stop loss: $15 if you want to risk $15, or $0.50 for small testing
Target payout: $45 for 3R on $15 risk, or $1.00 for small testing
Auto paper: ON

If More Trades is still too quiet, switch to Scalp Heavy.

## Commit

git add .
git commit -m "Fix auto entry wait reset and improve BTC15 paper fills"
git push
