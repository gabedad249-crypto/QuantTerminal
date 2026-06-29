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
    state: str
    setup_signature: str
    session_label: str
    trend_15m: str
    trend_5m: str
    fvg_count: int
    latest_fvg: str
    reasons: list[str]


class LearningMemory:
    """Local learning store + similarity/auto-tune helper.

    v0.6.0 adds setup clustering, guardrailed auto-tune, and richer outcome
    fingerprints so Recommend Only can learn from Paper Training without guessing.
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
        signature = (
            f"{getattr(decision,'state','')}|{getattr(decision,'ready',False)}|{getattr(decision,'side','WAIT')}|"
            f"{getattr(decision,'confidence',0)}|{getattr(decision,'latest_fvg','None')}|"
            f"{getattr(decision,'trend_15m','')}|{getattr(decision,'trend_5m','')}|{getattr(decision,'setup_signature','')}"
        )
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
            state=str(getattr(decision, "state", "UNKNOWN")),
            setup_signature=str(getattr(decision, "setup_signature", "")),
            session_label=str(getattr(decision, "session_label", "Unknown")),
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
        meta = dict(getattr(trade, "setup_meta", {}) or {})
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
            "size_usd": getattr(trade, "size_usd", 0.0),
            "duration_sec": (float(getattr(trade, "closed_at", 0) or 0) - float(getattr(trade, "opened_at", 0) or 0)) if getattr(trade, "closed_at", None) else 0,
            "cluster": self._cluster_from_trade(trade),
            "setup_meta": meta,
            "state_at_entry": meta.get("state", ""),
            "confirmation": meta.get("confirmation", ""),
            "trend_15m": meta.get("trend_15m", ""),
            "trend_5m": meta.get("trend_5m", ""),
            "fvg_key": meta.get("active_fvg_key", ""),
            "fvg_status": meta.get("active_fvg_status", ""),
            "session_label": meta.get("session_label", ""),
            "confidence": meta.get("confidence", 0),
            "grade": meta.get("grade", ""),
            "time_left_at_entry": meta.get("time_left_seconds", 0),
            "impulse_score": meta.get("impulse_score", 0),
            "fvg_quality_score": meta.get("fvg_quality_score", 0),
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
        outcomes = self._read_jsonl(self.outcomes_path)
        if not decision or not outcomes:
            return {"matches": 0, "win_rate": 0.0, "avg_pnl": 0.0, "score": 0, "label": "No memory yet"}
        side = str(getattr(decision, "side", "WAIT"))
        signature = str(getattr(decision, "setup_signature", ""))
        latest = str(getattr(decision, "latest_fvg", "")).upper()
        trend_15m = str(getattr(decision, "trend_15m", ""))
        trend_5m = str(getattr(decision, "trend_5m", ""))
        session = str(getattr(decision, "session_label", ""))
        matched = []
        for row in outcomes:
            r_side = str(row.get("side", ""))
            reason = str(row.get("reason", "")).upper()
            cluster = str(row.get("cluster", ""))
            score = 0
            if r_side == side:
                score += 3
            if signature and any(part and part in cluster for part in signature.split("|")[:4]):
                score += 2
            if trend_15m and (trend_15m.upper() in reason or trend_15m == str(row.get("trend_15m", ""))):
                score += 1
            if trend_5m and (trend_5m.upper() in reason or trend_5m == str(row.get("trend_5m", ""))):
                score += 1
            if session and (session.upper() in cluster.upper() or session == str(row.get("session_label", ""))):
                score += 1
            if str(getattr(decision, "confirmation", "")) and str(getattr(decision, "confirmation", "")) == str(row.get("confirmation", "")):
                score += 1
            if "FVG" in reason or "FVG" in latest:
                score += 1
            if score >= 4:
                matched.append(row)
        if not matched:
            return {"matches": 0, "win_rate": 0.0, "avg_pnl": 0.0, "score": 0, "label": "No similar trades yet"}
        wins = [x for x in matched if float(x.get("pnl") or 0) > 0]
        avg = sum(float(x.get("pnl") or 0) for x in matched) / len(matched)
        wr = len(wins) / len(matched) * 100
        sample_cap = min(1.0, len(matched) / 50.0)
        edge = max(0.0, min(100.0, wr + avg * 2.0))
        mem_score = int(edge * sample_cap)
        label = "Strong memory" if len(matched) >= 50 and wr >= 60 else ("Weak sample" if len(matched) < 50 else "Mixed memory")
        return {"matches": len(matched), "win_rate": wr, "avg_pnl": avg, "score": mem_score, "label": label}

    def clusters(self, limit: int = 8) -> list[dict[str, Any]]:
        outcomes = self._read_jsonl(self.outcomes_path)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            grouped.setdefault(str(row.get("cluster") or "Unknown"), []).append(row)
        rows = []
        for cluster, trades in grouped.items():
            wins = [x for x in trades if float(x.get("pnl") or 0) > 0]
            avg = sum(float(x.get("pnl") or 0) for x in trades) / len(trades)
            rows.append({
                "cluster": cluster,
                "trades": len(trades),
                "win_rate": len(wins) / len(trades) * 100 if trades else 0,
                "avg_pnl": avg,
            })
        rows.sort(key=lambda x: (x["trades"], x["win_rate"], x["avg_pnl"]), reverse=True)
        return rows[:limit]

    def session_summary(self) -> str:
        outcomes = self._read_jsonl(self.outcomes_path)
        if not outcomes:
            return "No learned outcomes yet. Paper Training mode will build session stats."
        by_hour: dict[str, list[dict[str, Any]]] = {}
        for row in outcomes:
            hour = time.strftime("%H:00 UTC", time.gmtime(float(row.get("ts") or 0)))
            by_hour.setdefault(hour, []).append(row)
        lines = ["Learned session/hour stats"]
        for hour, trades in sorted(by_hour.items())[-12:]:
            wins = [x for x in trades if float(x.get("pnl") or 0) > 0]
            avg = sum(float(x.get("pnl") or 0) for x in trades) / len(trades)
            lines.append(f"{hour}: {len(trades)} trades | WR {len(wins)/len(trades)*100:.1f}% | avg ${avg:.2f}")
        return "\n".join(lines)

    def auto_tune(self, current_min_rr: float) -> dict[str, Any]:
        outcomes = self._read_jsonl(self.outcomes_path)
        if len(outcomes) < 50:
            return {
                "ready": False,
                "recommended_min_rr": current_min_rr,
                "reason": f"Need 50+ closed paper trades before tuning. Have {len(outcomes)}.",
            }
        recent = outcomes[-100:]
        wins = [x for x in recent if float(x.get("pnl") or 0) > 0]
        win_rate = len(wins) / len(recent) * 100
        avg = sum(float(x.get("pnl") or 0) for x in recent) / len(recent)
        old_rr = float(current_min_rr)
        new_rr = old_rr
        reason = "No change. Guardrails say current RR is acceptable."
        # Guardrail: tiny steps only, no wild strategy changes.
        if win_rate < 45 or avg < 0:
            new_rr = min(3.5, old_rr + 0.10)
            reason = "Recent performance weak: raising RR filter slightly so only cleaner setups qualify."
        elif win_rate > 62 and avg > 0.5:
            new_rr = max(1.75, old_rr - 0.05)
            reason = "Recent performance strong: relaxing RR slightly to capture more valid setups."
        return {
            "ready": True,
            "recommended_min_rr": round(new_rr, 2),
            "reason": reason,
            "sample": len(recent),
            "win_rate": win_rate,
            "avg_pnl": avg,
        }

    def summary_text(self, decision: Any | None = None) -> str:
        s = self.stats()
        sim = self.similarity(decision) if decision is not None else {"matches":0,"win_rate":0,"avg_pnl":0,"score":0,"label":"No active setup"}
        state = "ON" if s["enabled"] else "OFF"
        clusters = self.clusters(limit=5)
        cluster_text = "\n".join(
            f"• {c['cluster']} | {c['trades']} trades | WR {c['win_rate']:.1f}% | avg ${c['avg_pnl']:.2f}"
            for c in clusters
        ) or "No setup clusters yet."
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
            f"Label: {sim['label']}\n\n"
            "Setup Clusters\n" + cluster_text + "\n\n" + self.session_summary()
        )

    def _cluster_from_trade(self, trade: Any) -> str:
        side = str(getattr(trade, "side", "")) or "UNKNOWN"
        reason = str(getattr(trade, "reason", ""))
        # Reason is usually: FVG setup | trend15/trend5 | fvg | confidence ...
        meta = dict(getattr(trade, "setup_meta", {}) or {})
        if meta:
            return f"{side} | {meta.get('trend_15m','?')}/{meta.get('trend_5m','?')} | {meta.get('confirmation','confirm?')} | {meta.get('session_label','session?')}"
        parts = [p.strip() for p in reason.split("|")]
        trend = parts[1] if len(parts) > 1 else "trend?"
        fvg = parts[2] if len(parts) > 2 else "FVG"
        return f"{side} | {trend} | {fvg}"

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
