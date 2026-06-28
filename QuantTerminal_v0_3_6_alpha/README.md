# Quant Terminal v0.3.6 Alpha

FVG-focused BTC paper trading terminal.

## New in v0.3.6

- Kalshi BTC15 timer now prefers the **nearest open KXBTC15M market** instead of blindly trusting an old pasted contract URL.
- Timer refreshes faster so PC/phone drift should be easier to catch.
- Paper balance now tracks trade size correctly:
  - Cash goes down when a paper trade opens.
  - Reserved amount shows the active buy-in size.
  - Equity = cash + reserved + live P/L.
  - Cash is returned plus/minus P/L when TP/SL closes.
- Closed trades now say whether they closed by **TARGET** or **STOP**.
- Signal journal anti-spam: no more repeating the same auto plan every tick.
- Added side help in the order panel:
  - LONG = buy/up.
  - SHORT = sell/down.
  - The engine can paper-trade both.
- Improved Kalshi debug explanation.

## Run

```bat
run_quant_terminal.bat
```

## Notes

This is still paper-only. Auto-open mode only opens simulated trades inside the app.
