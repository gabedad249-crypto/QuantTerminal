# Quant Terminal v0.8.6.2 Alpha Hotfix

Hard trade lifecycle fix. This version stops the open-then-disappear bug by locking each paper trade to the current BTC15 bucket expiry and blocking TP/SL closes for the first 20 seconds after entry while live P/L still updates.

## Run
```bat
python -m app.main
```

## Commit
```bat
git add .
git commit -m "Hard lock paper trade lifecycle"
git push
```
