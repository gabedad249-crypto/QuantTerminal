# Quant Terminal v0.3.5 Alpha

FVG-focused BTC paper trading terminal.

## New in v0.3.5

- Green/red border on **Open Auto Plan Paper Trade**:
  - Green = valid FVG setup is ready and you can open a paper trade.
  - Red = no valid setup yet.
  - Blue = paper trade is already open.
- Removed fake-entry confusion: chart shows **BUY-IN** until a real paper trade opens.
- Added optional **Auto-open paper when ready** mode. It is OFF by default.
- Added Kalshi BTC15 URL sync field.
- Default target URL set to the market format you sent:
  `https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/kxbtc15m-26jun280030`
- Kalshi Debug now shows target URL, target ticker, matched ticker, close time, source, and errors.
- Major feature: semi-auto paper trading workflow.

## Run

```bat
run_quant_terminal.bat
```

## Notes

This is still paper-only. Auto-open mode only opens simulated trades inside the app.
