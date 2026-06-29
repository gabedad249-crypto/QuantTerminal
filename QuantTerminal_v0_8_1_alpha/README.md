# Quant Terminal v0.8.1 Alpha

Hotfix for live price/chart display:
- BTC-USD live label now shows source (Coinbase WS/REST/SIM).
- Chart candle data updates every tick so the last candle and live number match.
- Candle y-axis no longer stretches to far cash stop/target levels, preventing flat-looking candles.
- Far stop/target labels are clipped to the chart edge instead of flattening the whole graph.

Run:
```bat
python -m app.main
```

Commit:
```bash
git add .
git commit -m "Fix live price display and flat chart scaling"
git push
```
