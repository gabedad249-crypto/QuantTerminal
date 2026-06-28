from dataclasses import dataclass, field
from typing import Optional

from app.strategy.fvg_engine import Candle, FVG, FVGEngine
from app.data.candles import aggregate_candles

@dataclass
class TradePlan:
    side: str
    entry: float
    stop: float
    target: float
    rr: float
    reason: str

@dataclass
class SetupDecision:
    ready: bool
    side: str = "WAIT"
    confidence: int = 0
    grade: str = "WAIT"
    plan: Optional[TradePlan] = None
    checklist: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    fvg_count: int = 0
    latest_fvg: str = "None"
    trend_15m: str = "Building"
    trend_5m: str = "Building"
    active_fvg_key: str = ""
    active_fvg_direction: str = ""
    active_fvg_status: str = ""

class FVGSetupEngine:
    """Disciplined FVG confirmation engine.

    It only recommends a buy-in after the full method is present:
    15m/5m trend context -> impulse/FVG -> retrace into FVG -> engulfing or rejection confirmation -> RR >= minimum.
    """
    def __init__(self, min_rr: float = 2.0) -> None:
        self.fvg_engine = FVGEngine()
        self.min_rr = min_rr

    def evaluate(self, candles_1m: list[Candle]) -> SetupDecision:
        d = SetupDecision(ready=False)
        n = len(candles_1m)
        if n < 60:
            d.reasons.append(f"Need more candles: {n}/60 loaded")
            d.checklist.append("❌ Context: waiting for at least 60 one-minute candles")
            return d

        candles_5m = aggregate_candles(candles_1m, 300)
        candles_15m = aggregate_candles(candles_1m, 900)
        d.trend_5m = self._trend(candles_5m, lookback=min(6, max(2, len(candles_5m)-1)))
        d.trend_15m = self._trend(candles_15m, lookback=min(4, max(2, len(candles_15m)-1)))
        trend_side = self._trend_side(d.trend_15m, d.trend_5m)
        trend_ok = trend_side in ("LONG", "SHORT")
        d.checklist.append(("✅" if trend_ok else "❌") + f" Trend: 15m {d.trend_15m}, 5m {d.trend_5m}")
        if not trend_ok:
            d.reasons.append("15m/5m trend not aligned")

        fvgs = self.fvg_engine.detect(candles_1m)
        d.fvg_count = len(fvgs)
        d.latest_fvg = (fvgs[-1].direction + " " + fvgs[-1].status) if fvgs else "None"
        if not fvgs:
            d.checklist.append("❌ FVG: none found")
            d.reasons.append("No fair value gap yet")
            return d

        current = candles_1m[-1]
        avg_body = self._avg_body(candles_1m[-35:-5])
        candidates = []
        for fvg in fvgs[-12:]:
            side = "LONG" if fvg.direction == "BULLISH" else "SHORT"
            if trend_ok and side != trend_side:
                continue
            fvg_index = self._index_for_ts(candles_1m, fvg.end_ts)
            if fvg_index is None or n - fvg_index < 2:
                continue
            impulse_ok = self._impulse_ok(candles_1m, fvg_index, avg_body)
            retrace_ok = self._price_inside_fvg(current.close, fvg)
            confirmation = self._confirmation(candles_1m, side)
            candidates.append((fvg, side, impulse_ok, retrace_ok, confirmation, fvg_index))

        if not candidates:
            d.checklist.append("❌ FVG: found, but not aligned with 15m/5m trend")
            d.reasons.append("FVG exists but no aligned setup")
            return d

        # Prefer newest aligned FVG that is being retested.
        candidates.sort(key=lambda x: (x[3], x[5]), reverse=True)
        fvg, side, impulse_ok, retrace_ok, confirmation, fvg_index = candidates[0]
        d.side = side
        d.active_fvg_key = self._fvg_key(fvg)
        d.active_fvg_direction = fvg.direction
        d.active_fvg_status = fvg.status
        d.latest_fvg = f"{fvg.direction} {fvg.status} #{int(fvg.end_ts)}"
        d.checklist.append("✅ FVG: aligned " + fvg.direction)
        d.checklist.append(("✅" if impulse_ok else "❌") + " Impulse: displacement candle strong enough")
        d.checklist.append(("✅" if retrace_ok else "❌") + " Retrace: price returned into the FVG")
        d.checklist.append(("✅" if confirmation else "❌") + f" Confirmation: {confirmation or 'waiting for engulfing/rejection candle'}")

        if not impulse_ok:
            d.reasons.append("FVG impulse is weak")
        if not retrace_ok:
            d.reasons.append("Price has not pulled back into the FVG yet")
        if not confirmation:
            d.reasons.append("Waiting for engulfing/rejection confirmation")

        if not (trend_ok and impulse_ok and retrace_ok and confirmation):
            d.confidence = self._partial_confidence(trend_ok, impulse_ok, retrace_ok, bool(confirmation))
            d.grade = self._grade(d.confidence)
            return d

        entry = current.close
        buffer = max(entry * 0.00018, 4.0)
        recent = candles_1m[-12:]
        if side == "LONG":
            stop = min(fvg.bottom - buffer, min(c.low for c in recent) - buffer)
            risk = max(entry - stop, buffer)
            target = entry + risk * self.min_rr
        else:
            stop = max(fvg.top + buffer, max(c.high for c in recent) + buffer)
            risk = max(stop - entry, buffer)
            target = entry - risk * self.min_rr
        rr = abs(target - entry) / max(abs(entry - stop), 0.0001)
        rr_ok = rr >= self.min_rr
        d.checklist.append(("✅" if rr_ok else "❌") + f" Risk/Reward: {rr:.2f}:1")
        if not rr_ok:
            d.reasons.append("RR below minimum")
            d.confidence = 65
            d.grade = self._grade(d.confidence)
            return d

        confidence = 55
        confidence += 12 if d.trend_15m in ("Bullish", "Bearish") else 0
        confidence += 10 if d.trend_5m in ("Bullish", "Bearish") else 0
        confidence += 12 if impulse_ok else 0
        confidence += 10 if retrace_ok else 0
        confidence += 10 if "Engulfing" in str(confirmation) else 6
        confidence += 6 if rr >= 2.5 else 0
        confidence = min(confidence, 96)

        d.ready = True
        d.confidence = confidence
        d.grade = self._grade(confidence)
        d.plan = TradePlan(side, entry, stop, target, rr, f"FVG confirmation: {confirmation}")
        d.reasons.append("VALID FVG CONFIRMATION SETUP")
        return d

    def _fvg_key(self, fvg: FVG) -> str:
        return f"{fvg.direction}:{int(fvg.end_ts)}:{round(fvg.top, 2)}:{round(fvg.bottom, 2)}"

    def _trend(self, candles: list[Candle], lookback: int = 4) -> str:
        if len(candles) < lookback + 1:
            return "Building"
        now = candles[-1].close
        then = candles[-1 - lookback].close
        move = (now - then) / then if then else 0
        if move > 0.0008:
            return "Bullish"
        if move < -0.0008:
            return "Bearish"
        return "Sideways"

    def _trend_side(self, trend_15m: str, trend_5m: str) -> str:
        if trend_15m == "Bullish" and trend_5m in ("Bullish", "Sideways"):
            return "LONG"
        if trend_15m == "Bearish" and trend_5m in ("Bearish", "Sideways"):
            return "SHORT"
        if trend_15m == "Building" and trend_5m == "Bullish":
            return "LONG"
        if trend_15m == "Building" and trend_5m == "Bearish":
            return "SHORT"
        return "WAIT"

    def _index_for_ts(self, candles: list[Candle], ts: float) -> int | None:
        for i, c in enumerate(candles):
            if int(c.ts) == int(ts):
                return i
        return None

    def _avg_body(self, candles: list[Candle]) -> float:
        if not candles:
            return 1.0
        return max(sum(abs(c.close - c.open) for c in candles) / len(candles), 1.0)

    def _impulse_ok(self, candles: list[Candle], index: int, avg_body: float) -> bool:
        c = candles[index]
        body = abs(c.close - c.open)
        return body >= avg_body * 1.15 or (c.high - c.low) >= avg_body * 2.0

    def _price_inside_fvg(self, price: float, fvg: FVG) -> bool:
        return min(fvg.bottom, fvg.top) <= price <= max(fvg.bottom, fvg.top)

    def _confirmation(self, candles: list[Candle], side: str) -> str | None:
        if len(candles) < 3:
            return None
        prev = candles[-2]
        cur = candles[-1]
        prev_body_hi = max(prev.open, prev.close)
        prev_body_lo = min(prev.open, prev.close)
        cur_body_hi = max(cur.open, cur.close)
        cur_body_lo = min(cur.open, cur.close)
        body = abs(cur.close - cur.open)
        rng = max(cur.high - cur.low, 0.0001)
        upper = cur.high - cur_body_hi
        lower = cur_body_lo - cur.low

        if side == "LONG":
            engulf = cur.close > cur.open and cur_body_hi >= prev_body_hi and cur_body_lo <= prev_body_lo
            reject = cur.close > cur.open and lower >= body * 1.25 and cur.close > (cur.low + rng * 0.62)
            if engulf:
                return "Bullish Engulfing"
            if reject:
                return "Bullish Rejection"
        else:
            engulf = cur.close < cur.open and cur_body_hi >= prev_body_hi and cur_body_lo <= prev_body_lo
            reject = cur.close < cur.open and upper >= body * 1.25 and cur.close < (cur.low + rng * 0.38)
            if engulf:
                return "Bearish Engulfing"
            if reject:
                return "Bearish Rejection"
        return None

    def _partial_confidence(self, *bits: bool) -> int:
        return 20 + sum(15 for b in bits if b)

    def _grade(self, confidence: int) -> str:
        if confidence >= 88:
            return "A+"
        if confidence >= 80:
            return "A"
        if confidence >= 72:
            return "B+"
        if confidence >= 64:
            return "B"
        if confidence >= 50:
            return "C"
        return "WAIT"
