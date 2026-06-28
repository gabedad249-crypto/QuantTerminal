from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class LearningSnapshot:
    ts: float
    price: float
    decision: str
    side: str
    confidence: int
    grade: str
    trend_15m: str
    trend_5m: str
    fvg_count: int
    latest_fvg: str
    reasons: list[str]


class LearningMemory:
    """Small local learning store for setup observations and paper-trade outcomes.

    This is intentionally simple in v0.3.1: it records what the strategy saw, what
    it recommended, and what paper trades did. Later versions can turn this into
    SQLite + historical similarity search.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshots_path = self.root / "learning_snapshots.jsonl"
        self.outcomes_path = self.root / "paper_trade_outcomes.jsonl"
        self.enabled = True
        self._last_snapshot_time = 0.0
        self._last_signature: str | None = None

    def record_snapshot(self, price: float, decision: Any, throttle_seconds: float = 20.0) -> bool:
        if not self.enabled or decision is None:
            return False
        now = time.time()
        signature = f"{getattr(decision,'ready',False)}|{getattr(decision,'side','WAIT')}|{getattr(decision,'confidence',0)}|{getattr(decision,'latest_fvg','None')}|{getattr(decision,'trend_15m','')}|{getattr(decision,'trend_5m','')}"
        if signature == self._last_signature and now - self._last_snapshot_time < throttle_seconds:
            return False
        self._last_signature = signature
        self._last_snapshot_time = now
        snap = LearningSnapshot(
            ts=now,
            price=float(price),
            decision="READY" if getattr(decision, "ready", False) else "WAIT",
            side=str(getattr(decision, "side", "WAIT")),
            confidence=int(getattr(decision, "confidence", 0)),
            grade=str(getattr(decision, "grade", "WAIT")),
            trend_15m=str(getattr(decision, "trend_15m", "Building")),
            trend_5m=str(getattr(decision, "trend_5m", "Building")),
            fvg_count=int(getattr(decision, "fvg_count", 0)),
            latest_fvg=str(getattr(decision, "latest_fvg", "None")),
            reasons=list(getattr(decision, "reasons", [])[-6:]),
        )
        with self.snapshots_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(snap)) + "\n")
        return True

    def record_trade_outcome(self, trade: Any) -> None:
        if not self.enabled:
            return
        row = {
            "ts": time.time(),
            "side": getattr(trade, "side", ""),
            "entry": getattr(trade, "entry", None),
            "stop": getattr(trade, "stop", None),
            "target": getattr(trade, "target", None),
            "exit_price": getattr(trade, "exit_price", None),
            "pnl": getattr(trade, "pnl", 0.0),
            "status": getattr(trade, "status", ""),
            "reason": getattr(trade, "reason", ""),
        }
        with self.outcomes_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def stats(self) -> dict[str, Any]:
        snapshots = self._count_lines(self.snapshots_path)
        outcomes = self._read_jsonl(self.outcomes_path)
        wins = [x for x in outcomes if float(x.get("pnl") or 0) > 0]
        losses = [x for x in outcomes if float(x.get("pnl") or 0) <= 0]
        return {
            "enabled": self.enabled,
            "snapshots": snapshots,
            "outcomes": len(outcomes),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(outcomes) * 100.0) if outcomes else 0.0,
            "avg_pnl": (sum(float(x.get("pnl") or 0) for x in outcomes) / len(outcomes)) if outcomes else 0.0,
        }

    def summary_text(self) -> str:
        s = self.stats()
        state = "ON" if s["enabled"] else "OFF"
        return (
            f"Learning Mode: {state}\n"
            f"Setup snapshots: {s['snapshots']}\n"
            f"Paper outcomes learned: {s['outcomes']}\n"
            f"Wins/Losses: {s['wins']}/{s['losses']}\n"
            f"Win rate: {s['win_rate']:.1f}%\n"
            f"Avg P/L: ${s['avg_pnl']:.2f}\n\n"
            "v0.3.1 learning stores observations only. Later builds will use this memory for similarity scoring and auto-tuning."
        )

    def _count_lines(self, path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
        return rows
