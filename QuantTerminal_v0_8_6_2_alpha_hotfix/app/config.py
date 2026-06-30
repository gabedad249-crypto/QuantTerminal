import json
from pathlib import Path
from app.utils.paths import ROOT

DEFAULT_SETTINGS = {
    "symbol": "BTC-USD",
    "exchange": "Coinbase",
    "starting_balance": 100000.0,
    "theme": "quant_dark",
    "strategy": {
        "name": "FVG_CONFIRMATION",
        "min_rr": 2.0,
        "min_confidence": 70,
        "paper_trade_enabled": True
    }
}

class Settings:
    def __init__(self) -> None:
        self.path = ROOT / "config" / "settings.json"
        self.data = DEFAULT_SETTINGS.copy()

    def load(self) -> dict:
        if not self.path.exists():
            self.save()
            return self.data
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = DEFAULT_SETTINGS.copy()
            self.save()
        return self.data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
