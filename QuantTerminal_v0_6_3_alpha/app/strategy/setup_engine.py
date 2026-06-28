from dataclasses import dataclass, field
from typing import Optional
import time

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
    state: str = "BUILDING_CONTEXT"
    plan: Optional[TradePlan] = None
    checklist: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    confidence_breakdown: list[str] = field(default_factory=list)
    safety_checks: list[str] = field(default_factory=list)
    setup_signature: str = ""
    session_label: str = "Unknown"
    fvg_count: int = 0
    latest_fvg: str = "None"
    trend_15m: str = "Building"
    trend_5m: str = "Building"
    active_fvg_key: str = ""
    active_fvg_direction: str = ""
    active_fvg_status: str = ""
    confirmation: str = ""
    impulse_score: int = 0
    fvg_quality_score: int = 0


class FVGSetupEngine:
    """Disciplined FVG confirmation engine.

    v0.6.0 tightens the logic into a real state machine:
    BUILDING_CONTEXT -> WAIT_TREND -> WAIT_FVG -> WAIT_PULLBACK -> WAIT_CONFIRMATION -> WAIT_RR -> READY.

    It still uses exactly one core strategy:
    trend context -> displacement/FVG -> retrace into FVG -> engulfing/rejection confirmation -> RR check.
    """

    def __init__(self, min_rr: float = 2.0) -> None:
        self.fvg_engine = FVGEngine()
        self.min_rr = float(min_rr)
        self.min_candles = 90
        self.max_fvg_age_bars = 55
        self.min_confidence_to_trade = 72

    def evaluate(self, candles_1m: list[Candle]) -> SetupDecision:
        d = SetupDecision(ready=False)
        d.session_label = self._session_label()
        n = len(candles_1m)
        if n < self.min_candles:
            d.state = "BUILDING_CONTEXT"
            d.reasons.append(f"Need more candles: {n}/{self.min_candles} loaded")
            d.checklist.append(f"❌ Context: waiting for at least {self.min_candles} one-minute candles")
            d.safety_checks.append("✅ Safe: no trade while context is building")
            d.confidence_breakdown.append("+0 Context not ready")
            return d

        candles_5m = aggregate_candles(candles_1m, 300)
        candles_15m = aggregate_candles(candles_1m, 900)
        d.trend_5m = self._trend(candles_5m, lookback=min(6, max(2, len(candles_5m)-1)))
        d.trend_15m = self._trend(candles_15m, lookback=min(4, max(2, len(candles_15m)-1)))
        trend_side = self._trend_side(d.trend_15m, d.trend_5m)
        trend_ok = trend_side in ("LONG", "SHORT")
        d.checklist.append(("✅" if trend_ok else "❌") + f" Trend: 15m {d.trend_15m}, 5m {d.trend_5m}")
        if trend_ok:
            d.side = trend_side
            d.confidence_breakdown.append(f"+18 Trend aligned: {d.trend_15m}/{d.trend_5m}")
        else:
            d.state = "WAIT_TREND"
            d.reasons.append("15m/5m trend not aligned")
            d.confidence_breakdown.append("+0 Trend not aligned")

        fvgs = self.fvg_engine.detect(candles_1m)
        d.fvg_count = len(fvgs)
        d.latest_fvg = (fvgs[-1].direction + " " + fvgs[-1].status) if fvgs else "None"
        if not fvgs:
            d.state = "WAIT_FVG"
            d.checklist.append("❌ FVG: none found")
            d.reasons.append("No fair value gap yet")
            d.confidence = self._score_from_breakdown(d.confidence_breakdown)
            d.grade = self._grade(d.confidence)
            return d

        current = candles_1m[-1]
        avg_body = self._avg_body(candles_1m[-45:-5])
        candidates = []
        for fvg in fvgs[-18:]:
            side = "LONG" if fvg.direction == "BULLISH" else "SHORT"
            if trend_ok and side != trend_side:
                continue
            fvg_index = self._index_for_ts(candles_1m, fvg.end_ts)
            if fvg_index is None:
                continue
            age = n - fvg_index
            if age < 2 or age > self.max_fvg_age_bars:
                continue
            impulse_score = self._impulse_score(candles_1m, fvg_index, avg_body)
            fvg_quality = self._fvg_quality_score(fvg, current.close, avg_body, age)
            retrace_ok = self._price_inside_fvg(current.close, fvg)
            confirmation = self._confirmation(candles_1m, side)
            candidates.append((fvg, side, impulse_score, fvg_quality, retrace_ok, confirmation, fvg_index, age))

        if not candidates:
            d.state = "WAIT_FVG"
            d.checklist.append("❌ FVG: found, but no fresh aligned GAP")
            d.reasons.append("FVG exists but no fresh aligned setup")
            d.confidence = self._score_from_breakdown(d.confidence_breakdown)
            d.grade = self._grade(d.confidence)
            return d

        # One GAP at a time: prefer newest aligned GAP that is actually being retested.
        candidates.sort(key=lambda x: (x[4], x[2] + x[3], x[6]), reverse=True)
        fvg, side, impulse_score, fvg_quality, retrace_ok, confirmation, fvg_index, age = candidates[0]
        impulse_ok = impulse_score >= 12
        d.side = side
        d.impulse_score = impulse_score
        d.fvg_quality_score = fvg_quality
        d.confirmation = confirmation or ""
        d.active_fvg_key = self._fvg_key(fvg)
        d.active_fvg_direction = fvg.direction
        d.active_fvg_status = fvg.status
        d.latest_fvg = f"{fvg.direction} {fvg.status} #{int(fvg.end_ts)}"
        d.setup_signature = self._setup_signature(d, fvg, side, confirmation)

        d.checklist.append("✅ FVG: aligned " + fvg.direction)
        d.checklist.append(("✅" if impulse_ok else "❌") + f" Impulse: score {impulse_score}/20")
        d.checklist.append(("✅" if fvg_quality >= 10 else "❌") + f" GAP quality: score {fvg_quality}/20")
        d.checklist.append(("✅" if retrace_ok else "❌") + " Retrace: price returned into the GAP")
        d.checklist.append(("✅" if confirmation else "❌") + f" Confirmation: {confirmation or 'waiting for engulfing/rejection candle'}")
        d.safety_checks.append("✅ One-GAP lifecycle: one active plan per GAP")
        d.safety_checks.append(f"✅ GAP age: {age} bars old" if age <= self.max_fvg_age_bars else f"❌ GAP too old: {age} bars")

        if impulse_ok:
            d.confidence_breakdown.append(f"+{impulse_score} Displacement/impulse")
        else:
            d.reasons.append("FVG impulse is weak")
            d.confidence_breakdown.append(f"+{impulse_score} Weak impulse")

        if fvg_quality >= 10:
            d.confidence_breakdown.append(f"+{fvg_quality} GAP quality")
        else:
            d.reasons.append("GAP quality is weak or already messy")
            d.confidence_breakdown.append(f"+{fvg_quality} Weak GAP quality")

        if retrace_ok:
            d.confidence_breakdown.append("+15 Pullback into GAP")
        else:
            d.state = "WAIT_PULLBACK"
            d.reasons.append("Price has not pulled back into the GAP yet")
            d.confidence_breakdown.append("+0 Waiting for pullback")

        if confirmation:
            d.confidence_breakdown.append("+18 " + confirmation)
        else:
            if retrace_ok:
                d.state = "WAIT_CONFIRMATION"
            d.reasons.append("Waiting for engulfing/rejection confirmation")
            d.confidence_breakdown.append("+0 Confirmation not printed")

        if not (trend_ok and impulse_ok and retrace_ok and confirmation and fvg_quality >= 10):
            if d.state in ("BUILDING_CONTEXT", "WAIT_TREND"):
                pass
            elif not retrace_ok:
                d.state = "WAIT_PULLBACK"
            elif not confirmation:
                d.state = "WAIT_CONFIRMATION"
            else:
                d.state = "WAIT_FVG_QUALITY"
            d.confidence = min(85, self._score_from_breakdown(d.confidence_breakdown))
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
        if rr_ok:
            d.confidence_breakdown.append("+12 RR meets filter")
            if rr >= self.min_rr + 0.5:
                d.confidence_breakdown.append("+6 Extra RR cushion")
        else:
            d.state = "WAIT_RR"
            d.reasons.append("RR below minimum")
            d.confidence_breakdown.append("+0 RR below filter")
            d.confidence = min(80, self._score_from_breakdown(d.confidence_breakdown))
            d.grade = self._grade(d.confidence)
            return d

        d.state = "READY"
        d.confidence = min(96, self._score_from_breakdown(d.confidence_breakdown))
        d.grade = self._grade(d.confidence)
        d.ready = d.confidence >= self.min_confidence_to_trade
        d.plan = TradePlan(side, entry, stop, target, rr, f"FVG confirmation: {confirmation}")
        if d.ready:
            d.reasons.append("VALID FVG CONFIRMATION SETUP")
            d.safety_checks.append("✅ Safety: valid setup, no trade active, RR passed")
        else:
            d.reasons.append("Setup exists but confidence below trade threshold")
            d.safety_checks.append("❌ Safety: confidence below threshold")
        return d

    def _fvg_key(self, fvg: FVG) -> str:
        return f"{fvg.direction}:{int(fvg.end_ts)}:{round(fvg.top, 2)}:{round(fvg.bottom, 2)}"

    def _setup_signature(self, d: SetupDecision, fvg: FVG, side: str, confirmation: str | None) -> str:
        return "|".join([
            side,
            d.trend_15m,
            d.trend_5m,
            fvg.direction,
            fvg.status,
            confirmation or "NO_CONFIRM",
            d.session_label,
        ])

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

    def _impulse_score(self, candles: list[Candle], index: int, avg_body: float) -> int:
        c = candles[index]
        body = abs(c.close - c.open)
        rng = max(c.high - c.low, 0.0001)
        body_score = min(12, int((body / max(avg_body, 1.0)) * 5))
        range_score = min(6, int((rng / max(avg_body, 1.0)) * 2))
        close_bias = 2 if (abs(c.close - c.open) / rng) >= 0.55 else 0
        return max(0, min(20, body_score + range_score + close_bias))

    def _fvg_quality_score(self, fvg: FVG, price: float, avg_body: float, age: int) -> int:
        height = abs(fvg.top - fvg.bottom)
        size_score = min(8, int((height / max(avg_body, 1.0)) * 5))
        status_score = {"ACTIVE": 7, "TOUCHED": 5, "FILLED": 0}.get(fvg.status, 3)
        age_score = 5 if age <= 18 else (3 if age <= 35 else 1)
        return max(0, min(20, size_score + status_score + age_score))

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

    def _score_from_breakdown(self, rows: list[str]) -> int:
        score = 0
        for row in rows:
            row = row.strip()
            if row.startswith("+"):
                try:
                    score += int(float(row.split()[0].replace("+", "")))
                except Exception:
                    pass
        return max(0, min(100, score))

    def _grade(self, confidence: int) -> str:
        if confidence >= 90:
            return "S"
        if confidence >= 84:
            return "A+"
        if confidence >= 78:
            return "A"
        if confidence >= 70:
            return "B+"
        if confidence >= 62:
            return "B"
        if confidence >= 50:
            return "C"
        return "WAIT"

    def _session_label(self) -> str:
        # UTC session buckets; local display does not matter for strategy learning.
        hour = time.gmtime().tm_hour
        if 0 <= hour < 7:
            return "Asia"
        if 7 <= hour < 12:
            return "London"
        if 12 <= hour < 16:
            return "NY Open"
        if 16 <= hour < 20:
            return "NY Midday"
        return "After Hours"
