# Quant Terminal v0.1.3 Alpha

TradingView-style planning build.

## Run

```bat
run_quant_terminal.bat
```

## Added
- Draggable TradingView-style position planner on the chart
- Drag **ENTRY**, **STOP**, and **TARGET** lines directly on the chart
- Entry/stop/target price boxes sync with the chart
- RR ratio updates automatically
- **Suggest Buy-In From Chart** button
- **Open Planned Paper Trade** button
- Improved zoom model using visible bars instead of fake scale
- Compact FVG boxes and range high/low markers remain

## Important
The chart is still the early custom Qt canvas. The next major chart milestone should replace it with a stronger real chart engine, but this build starts the actual trade-planning workflow.
