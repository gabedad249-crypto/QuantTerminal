# Quant Terminal v0.3.4 Alpha

## What changed

- Removed fake ENTRY behavior when there is no open paper trade.
- Removed manual Suggest button behavior from the workflow.
- Added Auto Signal Engine: the chart only shows a BUY-IN / STOP / TARGET plan after the FVG checklist is valid.
- Auto clears the plan when the setup is no longer valid and no paper trade is open.
- Added Signal Journal tab for auto plans, opened trades, and closed trade outcomes.
- Added Kalshi Debug tab with ticker, source, close time, time left, and lookup errors.
- Chart plan labels now say BUY-IN for suggested plans and ENTRY only for actual open paper trades.

## Run

```bat
run_quant_terminal.bat
```

## Commit

```bash
git add .
git commit -m "Add auto signal engine and Kalshi debug"
git push
```
