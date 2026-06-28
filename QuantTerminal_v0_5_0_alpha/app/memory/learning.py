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
    """Local learning store + v0.3.9 similarity/auto-tune helper."""

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
            "exit_reason": getattr(trade, "exit_reason", ""),
            "rr": getattr(trade, "rr", 0.0),
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

    def similarity(self, decision: Any) -> dict[str, Any]:
        """Score current setup against learned paper outcomes.

        v0.3.9 is intentionally conservative: it mostly compares side + FVG family
        because older trades did not store every feature yet. Future builds will
        add richer candle fingerprints.
        """
        outcomes = self._read_jsonl(self.outcomes_path)
        if not decision or not outcomes:
            return {"matches": 0, "win_rate": 0.0, "avg_pnl": 0.0, "score": 0, "label": "No memory yet"}
        side = str(getattr(decision, "side", "WAIT"))
        latest = str(getattr(decision, "latest_fvg", "")).upper()
        matched = []
        for row in outcomes:
            r_side = str(row.get("side", ""))
            reason = str(row.get("reason", "")).upper()
            score = 0
            if r_side == side:
                score += 2
            if "FVG" in reason or "FVG" in latest:
                score += 1
            if score >= 2:
                matched.append(row)
        if not matched:
            return {"matches": 0, "win_rate": 0.0, "avg_pnl": 0.0, "score": 0, "label": "No similar trades yet"}
        wins = [x for x in matched if float(x.get("pnl") or 0) > 0]
        avg = sum(float(x.get("pnl") or 0) for x in matched) / len(matched)
        wr = len(wins) / len(matched) * 100
        # Confidence-style memory score, capped until sample is larger.
        sample_cap = min(1.0, len(matched) / 30.0)
        edge = max(0.0, min(100.0, wr + avg * 2.0))
        mem_score = int(edge * sample_cap)
        label = "Strong memory" if len(matched) >= 30 and wr >= 60 else ("Weak sample" if len(matched) < 30 else "Mixed memory")
        return {"matches": len(matched), "win_rate": wr, "avg_pnl": avg, "score": mem_score, "label": label}

    def auto_tune(self, current_min_rr: float) -> dict[str, Any]:
        outcomes = self._read_jsonl(self.outcomes_path)
        if len(outcomes) < 20:
            return {
                "ready": False,
                "recommended_min_rr": current_min_rr,
                "reason": f"Need 20+ closed paper trades before tuning. Have {len(outcomes)}.",
            }
        wins = [x for x in outcomes if float(x.get("pnl") or 0) > 0]
        win_rate = len(wins) / len(outcomes) * 100
        avg = sum(float(x.get("pnl") or 0) for x in outcomes) / len(outcomes)
        new_rr = float(current_min_rr)
        reason = "No change."
        if win_rate < 45 or avg < 0:
            new_rr = min(3.5, current_min_rr + 0.25)
            reason = "Performance weak: raising RR filter so only cleaner setups qualify."
        elif win_rate > 62 and avg > 0.5:
            new_rr = max(1.75, current_min_rr - 0.10)
            reason = "Performance strong: slightly relaxing RR to capture more good setups."
        return {
            "ready": True,
            "recommended_min_rr": round(new_rr, 2),
            "reason": reason,
            "sample": len(outcomes),
            "win_rate": win_rate,
            "avg_pnl": avg,
        }

    def summary_text(self, decision: Any | None = None) -> str:
        s = self.stats()
        sim = self.similarity(decision) if decision is not None else {"matches":0,"win_rate":0,"avg_pnl":0,"score":0,"label":"No active setup"}
        state = "ON" if s["enabled"] else "OFF"
        return (
            f"Learning Mode: {state}\n"
            f"Setup snapshots: {s['snapshots']}\n"
            f"Paper outcomes learned: {s['outcomes']}\n"
            f"Wins/Losses: {s['wins']}/{s['losses']}\n"
            f"Win rate: {s['win_rate']:.1f}%\n"
            f"Avg P/L: ${s['avg_pnl']:.2f}\n\n"
            "Similarity Scoring\n"
            f"Matches: {sim['matches']}\n"
            f"Similar win rate: {sim['win_rate']:.1f}%\n"
            f"Similar avg P/L: ${sim['avg_pnl']:.2f}\n"
            f"Memory score: {sim['score']}/100\n"
            f"Label: {sim['label']}\n"
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
