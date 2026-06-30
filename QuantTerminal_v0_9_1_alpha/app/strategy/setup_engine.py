from dataclasses import dataclass, field
from typing import Optional
import time

from app.strategy.fvg_engine import Candle, FVG, FVGEngine
from app.data.candles import aggregate_candles
from app.strategy.candlestick_patterns import detect_candlestick_patterns, strongest_bias


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
    focused_gap: str = ""
    invalidation_reason: str = ""
    next_action: str = "Scanning"
    time_left_seconds: int = 0
    entry_model: str = "FVG"
    higher_tf_bias: str = "WAIT"
    trigger_quality: str = "Waiting"
    training_probe: bool = False
    sweep_detected: bool = False
    choch_detected: bool = False
    displacement_detected: bool = False
    trigger_sequence: str = "Waiting"
    training_speed: str = "Balanced"
    candlestick_patterns: list[str] = field(default_factory=list)
    candlestick_bias: str = "NEUTRAL"
    candlestick_signal: str = "No pattern"
    ema_bias: str = "WAIT"
    ema_state: str = "Unknown"


class FVGSetupEngine:
    """Disciplined FVG confirmation engine.

    v0.7.3 adds the proper Sweep -> CHoCH -> Displacement -> 1m FVG entry model plus a training-probe mode so it actually produces paper trades:
    SCANNING -> FOUND_GAP -> WAIT_PULLBACK -> WAIT_CONFIRMATION -> READY_CHECK -> READY -> IN_TRADE -> LEARNING.

    It still uses exactly one core strategy:
    trend context -> displacement/FVG -> retrace into FVG -> engulfing/rejection confirmation -> RR check.
    """

    def __init__(self, min_rr: float = 2.0) -> None:
        self.fvg_engine = FVGEngine()
        self.min_rr = float(min_rr)
        # v0.7.0 was too strict and could sit all day without training data.
        # These are still guarded, but loose enough to let the paper bot learn.
        self.min_candles = 35
        self.max_fvg_age_bars = 55
        self.min_confidence_to_trade = 50
        self.focus_gap_key: str = ""
        self.focus_side: str = ""
        self.used_gap_keys: set[str] = set()
        self.seconds_left: int | None = None
        self.min_seconds_left = 25
        self.training_probe_enabled = True
        self.training_speed = "More Trades"
        self._last_scout_bucket = -1

    def configure_context(self, used_gap_keys: set[str] | None = None, seconds_left: int | None = None, training_speed: str | None = None) -> None:
        """UI/runtime context for safety rules.

        The strategy stays pure chart-first, but the app can tell it which GAPs
        already produced a paper trade and how much BTC15 time remains.
        """
        if used_gap_keys is not None:
            self.used_gap_keys = set(used_gap_keys)
        self.seconds_left = seconds_left
        if training_speed:
            self.training_speed = str(training_speed)
        self._apply_training_speed()


    def _apply_training_speed(self) -> None:
        """Tune strictness for data collection without changing the core model."""
        mode = str(getattr(self, "training_speed", "More Trades"))
        if mode.startswith("Strict"):
            self.min_candles = 45
            self.max_fvg_age_bars = 55
            self.min_confidence_to_trade = 58
            self.min_seconds_left = 45
        elif mode.startswith("Scalp"):
            # Heavy BTC15 paper scalping: more frequent lower-grade probes, still labeled clearly.
            self.min_candles = 20
            self.max_fvg_age_bars = 120
            self.min_confidence_to_trade = 32
            self.min_seconds_left = 12
        elif mode.startswith("Max"):
            self.min_candles = 25
            self.max_fvg_age_bars = 90
            self.min_confidence_to_trade = 38
            self.min_seconds_left = 15
        else:
            self.min_candles = 30
            self.max_fvg_age_bars = 75
            self.min_confidence_to_trade = 44
            self.min_seconds_left = 25

    def _is_max_training(self) -> bool:
        return str(getattr(self, "training_speed", "")).startswith("Max")

    def _is_scalp_heavy(self) -> bool:
        return str(getattr(self, "training_speed", "")).startswith("Scalp")

    def _is_more_trades(self) -> bool:
        return str(getattr(self, "training_speed", "")).startswith(("More", "Max", "Scalp"))

    def evaluate(self, candles_1m: list[Candle]) -> SetupDecision:
        d = SetupDecision(ready=False)
        d.state = "SCANNING"
        d.session_label = self._session_label()
        d.training_speed = str(getattr(self, "training_speed", "More Trades"))
        if self.seconds_left is not None:
            d.time_left_seconds = int(self.seconds_left)
        n = len(candles_1m)
        if n < self.min_candles:
            d.state = "SCANNING"
            d.reasons.append(f"Need more candles: {n}/{self.min_candles} loaded")
            d.checklist.append(f"❌ Context: waiting for at least {self.min_candles} one-minute candles")
            d.safety_checks.append("✅ Safe: no trade while context is building")
            d.confidence_breakdown.append("+0 Context not ready")
            return d

        candles_5m = aggregate_candles(candles_1m, 300)
        candles_15m = aggregate_candles(candles_1m, 900)
        d.trend_5m = self._trend(candles_5m, lookback=min(6, max(2, len(candles_5m)-1)))
        d.trend_15m = self._trend(candles_15m, lookback=min(4, max(2, len(candles_15m)-1)))
        htf_fvgs = self.fvg_engine.detect(candles_5m) if len(candles_5m) >= 3 else []
        htf_side = self._latest_bias_from_fvgs(htf_fvgs)
        d.higher_tf_bias = htf_side
        trend_side = self._trend_side(d.trend_15m, d.trend_5m)
        if trend_side not in ("LONG", "SHORT") and htf_side in ("LONG", "SHORT"):
            trend_side = htf_side
        if trend_side not in ("LONG", "SHORT"):
            trend_side = self._micro_momentum_side(candles_1m)
        ema_side, ema_state = self._ema_continuation_bias(candles_1m)
        d.ema_bias = ema_side
        d.ema_state = ema_state
        if trend_side not in ("LONG", "SHORT") and ema_side in ("LONG", "SHORT"):
            trend_side = ema_side
        trend_ok = trend_side in ("LONG", "SHORT")
        d.entry_model = "5m bias -> Sweep/CHoCH -> 1m FVG execution"
        d.checklist.append(("✅" if trend_ok else "❌") + f" Bias: 15m {d.trend_15m}, 5m {d.trend_5m}, 5m GAP bias {htf_side}, EMA {ema_state}")
        if trend_ok:
            d.side = trend_side
            if htf_side in ("LONG", "SHORT"):
                d.confidence_breakdown.append(f"+20 5m bias -> 1m execution bias: {htf_side}")
            else:
                d.confidence_breakdown.append(f"+14 Trend/momentum bias: {trend_side}")
            if ema_side == trend_side:
                d.confidence_breakdown.append("+6 EMA continuation alignment")
        else:
            d.state = "SCANNING"
            d.reasons.append("No clean 5m/1m directional bias yet")
            d.confidence_breakdown.append("+0 Bias not ready")

        fvgs = self.fvg_engine.detect(candles_1m)
        d.fvg_count = len(fvgs)
        d.latest_fvg = (fvgs[-1].direction + " " + fvgs[-1].status) if fvgs else "None"
        if not fvgs:
            d.state = "FOUND_GAP"
            d.checklist.append("❌ FVG: none found")
            d.reasons.append("No fair value gap yet")
            # Data-builder mode can take rare micro-momentum scout probes so the bot collects outcomes.
            scout = self._build_scout_probe(d, candles_1m, trend_side, "No 1m FVG yet; micro-momentum scout probe")
            if scout:
                return scout
            d.confidence = self._score_from_breakdown(d.confidence_breakdown)
            d.grade = self._grade(d.confidence)
            return d

        current = candles_1m[-1]
        latest_patterns = detect_candlestick_patterns(candles_1m[-5:])
        d.candlestick_patterns = [f"{p.name} ({p.bias}, {p.strength})" for p in latest_patterns]
        d.candlestick_bias, d.candlestick_signal, _pattern_strength = strongest_bias(candles_1m[-5:])
        if latest_patterns:
            d.checklist.append("🕯 Candle read: " + ", ".join(d.candlestick_patterns[:3]))
            if d.candlestick_bias == "BULLISH":
                d.confidence_breakdown.append("+4 Bullish candle pattern: " + d.candlestick_signal)
            elif d.candlestick_bias == "BEARISH":
                d.confidence_breakdown.append("+4 Bearish candle pattern: " + d.candlestick_signal)
        avg_body = self._avg_body(candles_1m[-45:-5])
        if self.seconds_left is not None and self.seconds_left < self.min_seconds_left:
            d.safety_checks.append(f"❌ BTC15 time: only {self.seconds_left}s left, need {self.min_seconds_left}s+")
        else:
            d.safety_checks.append("✅ BTC15 time: enough time left for setup")
        candidates = []
        invalidated_focus = ""
        for fvg in fvgs[-24:]:
            side = "LONG" if fvg.direction == "BULLISH" else "SHORT"
            key = self._fvg_key(fvg)
            # Video-inspired reinforcement: avoid weak counter-trend reversal
            # attempts against the 8/20 EMA continuation unless Max Training is
            # intentionally collecting data or a full CHoCH model later appears.
            if ema_side in ("LONG", "SHORT") and side != ema_side and not self._is_max_training():
                if key == self.focus_gap_key:
                    invalidated_focus = "EMA continuation bias flipped against focused GAP"
                continue
            # Direction lock / one-GAP focus: while a focus GAP is valid, ignore every other GAP.
            if self.focus_gap_key and key != self.focus_gap_key:
                continue
            if key in self.used_gap_keys:
                continue
            # Direction lock: use 5m bias first, then trend/micro momentum.
            # This is the TradersNotes style: mark bias on 5m, execute on 1m.
            if trend_ok and side != trend_side:
                if key == self.focus_gap_key:
                    invalidated_focus = "direction bias flipped against focused GAP"
                continue
            fvg_index = self._index_for_ts(candles_1m, fvg.end_ts)
            if fvg_index is None:
                continue
            age = n - fvg_index
            invalid_reason = self._invalid_reason(fvg, current.close, avg_body, age)
            if invalid_reason:
                if key == self.focus_gap_key:
                    invalidated_focus = invalid_reason
                continue
            impulse_score = self._impulse_score(candles_1m, fvg_index, avg_body)
            fvg_quality = self._fvg_quality_score(fvg, current.close, avg_body, age)
            retrace_ok = self._price_inside_fvg(current.close, fvg, avg_body)
            sweep = self._liquidity_sweep(candles_1m, side)
            choch = self._choch(candles_1m, side)
            displacement = self._displacement(candles_1m, side, avg_body)
            confirmation = self._confirmation(candles_1m, side)
            if not confirmation and sweep and choch and displacement:
                confirmation = ("Bullish" if side == "LONG" else "Bearish") + " Sweep → CHoCH → Displacement"
            if not confirmation:
                confirmation = self._soft_confirmation(candles_1m, side, fvg, avg_body)
            candidates.append((fvg, side, impulse_score, fvg_quality, retrace_ok, confirmation, fvg_index, age, sweep, choch, displacement))

        if not candidates:
            d.state = "SCANNING" if not self.focus_gap_key else "FOUND_GAP"
            d.checklist.append("❌ FVG: found, but no fresh aligned GAP")
            if invalidated_focus:
                d.invalidation_reason = invalidated_focus
                d.reasons.append("Focused GAP invalidated: " + invalidated_focus)
                d.safety_checks.append("❌ Invalidation: " + invalidated_focus)
                self.focus_gap_key = ""
                self.focus_side = ""
            else:
                d.reasons.append("FVG exists but no fresh aligned setup")
            scout = self._build_scout_probe(d, candles_1m, trend_side, "Aligned GAP blocked; taking labeled micro scout for training")
            if scout:
                return scout
            d.confidence = self._score_from_breakdown(d.confidence_breakdown)
            d.grade = self._grade(d.confidence)
            return d

        # One GAP at a time: hold the focused GAP until invalidated/filled/expired.
        if self.focus_gap_key:
            focused = [x for x in candidates if self._fvg_key(x[0]) == self.focus_gap_key]
            selected = focused[0] if focused else None
        else:
            candidates.sort(key=lambda x: (x[4], x[2] + x[3], x[6]), reverse=True)
            selected = candidates[0]
        if selected is None:
            d.state = "SCANNING"
            d.reasons.append("Focused GAP no longer valid")
            self.focus_gap_key = ""
            self.focus_side = ""
            return d
        fvg, side, impulse_score, fvg_quality, retrace_ok, confirmation, fvg_index, age, sweep, choch, displacement = selected
        self.focus_gap_key = self._fvg_key(fvg)
        self.focus_side = side
        impulse_ok = impulse_score >= 5
        d.side = side
        d.impulse_score = impulse_score
        d.fvg_quality_score = fvg_quality
        d.confirmation = confirmation or ""
        d.sweep_detected = bool(sweep)
        d.choch_detected = bool(choch)
        d.displacement_detected = bool(displacement)
        d.trigger_sequence = self._trigger_sequence(side, sweep, choch, displacement, confirmation)
        d.active_fvg_key = self._fvg_key(fvg)
        d.focused_gap = d.active_fvg_key
        d.active_fvg_direction = fvg.direction
        d.active_fvg_status = fvg.status
        d.latest_fvg = f"{fvg.direction} {fvg.status} #{int(fvg.end_ts)}"
        d.setup_signature = self._setup_signature(d, fvg, side, confirmation)

        d.checklist.append("✅ FVG: aligned " + fvg.direction)
        d.checklist.append(("✅" if impulse_ok else "❌") + f" Impulse: score {impulse_score}/20")
        d.checklist.append(("✅" if fvg_quality >= 4 else "❌") + f" GAP quality: score {fvg_quality}/20")
        d.checklist.append(("✅" if retrace_ok else "❌") + " Retrace: price returned into/near the GAP")
        d.checklist.append(("✅" if sweep else "❌") + " Sweep: price took nearby liquidity")
        d.checklist.append(("✅" if choch else "❌") + " CHoCH: market structure shifted back with bias")
        d.checklist.append(("✅" if displacement else "❌") + " Displacement: strong candle away from sweep")
        d.checklist.append(("✅" if confirmation else "❌") + f" Trigger: {confirmation or 'waiting for Sweep → CHoCH / displacement'}")
        d.safety_checks.append("✅ One-GAP lifecycle: one active plan per GAP")
        d.safety_checks.append(f"✅ GAP age: {age} bars old" if age <= self.max_fvg_age_bars else f"❌ GAP too old: {age} bars")

        if impulse_ok:
            d.confidence_breakdown.append(f"+{impulse_score} Displacement/impulse")
        else:
            d.reasons.append("FVG impulse is weak")
            d.confidence_breakdown.append(f"+{impulse_score} Weak impulse")

        if fvg_quality >= 4:
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

        if sweep:
            d.confidence_breakdown.append("+8 Liquidity sweep")
        if choch:
            d.confidence_breakdown.append("+12 CHoCH structure shift")
        if displacement:
            d.confidence_breakdown.append("+8 Displacement candle")
        if confirmation:
            d.trigger_quality = "A-grade Sweep→CHoCH" if (sweep and choch and displacement) else ("Strong" if "Engulfing" in confirmation or "Rejection" in confirmation else "Good")
            d.confidence_breakdown.append("+14 " + confirmation)
        else:
            if retrace_ok:
                d.state = "WAIT_CONFIRMATION"
            d.reasons.append("Waiting for Sweep → CHoCH → displacement/FVG confirmation")
            d.confidence_breakdown.append("+0 Confirmation not printed")

        time_ok = self.seconds_left is None or self.seconds_left >= self.min_seconds_left
        if not time_ok:
            d.reasons.append("BTC15 is too close to expiry for a new setup")
            d.confidence_breakdown.append("+0 BTC15 time safety failed")

        # Relaxed but disciplined training gate. The bot needs data, so it can take
        # B-grade paper probes when the 5m/1m direction is aligned and price retests
        # the GAP. Those probes are labeled for memory instead of pretending they are A+ setups.
        trend_gate = trend_ok or d.trend_15m in ("Building", "Sideways") or d.trend_5m in ("Bullish", "Bearish")
        choch_model_ok = bool(sweep and choch and displacement)
        strong_setup = bool(trend_gate and impulse_ok and retrace_ok and confirmation and choch_model_ok and fvg_quality >= 4 and time_ok)
        probe_setup = bool(
            self.training_probe_enabled
            and trend_gate
            and time_ok
            and (retrace_ok or self._is_max_training())
            and impulse_score >= (3 if self._is_more_trades() else 4)
            and fvg_quality >= (2 if self._is_more_trades() else 3)
            and (confirmation or choch_model_ok or self._directional_close(candles_1m, side) or self._micro_followthrough(candles_1m, side))
        )
        if probe_setup and not strong_setup:
            d.training_probe = True
            d.trigger_quality = "Training Probe"
            d.confidence_breakdown.append("+8 Training probe allowed for paper data")
            d.reasons.append("PAPER TRAINING PROBE: not perfect, but valid enough to collect outcome data")

        if not (strong_setup or probe_setup):
            if not time_ok:
                d.state = "SCANNING"
            elif not trend_gate:
                d.state = "SCANNING"
            elif not retrace_ok:
                d.state = "WAIT_PULLBACK"
            elif not (confirmation or choch_model_ok or self._directional_close(candles_1m, side)):
                d.state = "WAIT_CHOCH"
            else:
                d.state = "FOUND_GAP"
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
            d.state = "READY_CHECK"
            d.reasons.append("RR below minimum")
            d.confidence_breakdown.append("+0 RR below filter")
            d.confidence = min(80, self._score_from_breakdown(d.confidence_breakdown))
            d.grade = self._grade(d.confidence)
            return d

        d.state = "READY"
        d.confidence = min(96, self._score_from_breakdown(d.confidence_breakdown))
        d.grade = self._grade(d.confidence)
        d.ready = d.confidence >= self.min_confidence_to_trade
        d.plan = TradePlan(side, entry, stop, target, rr, f"{d.entry_model}: {d.trigger_sequence}")
        if d.ready:
            d.reasons.append("VALID FVG CONFIRMATION SETUP" if not d.training_probe else "VALID PAPER TRAINING PROBE")
            d.safety_checks.append("✅ Safety: valid setup, no trade active, RR passed")
            d.next_action = "Open paper training trade"
        else:
            d.reasons.append("Setup exists but confidence below trade threshold")
            d.safety_checks.append("❌ Safety: confidence below threshold")
            d.next_action = "Keep watching"
        return d


    def _build_scout_probe(self, d: SetupDecision, candles: list[Candle], side: str, reason: str) -> SetupDecision | None:
        """Optional data-builder trade when the strict FVG model is too quiet.

        This is intentionally labeled SCOUT_PROBE, not an A-grade setup. It only
        runs in More Trades / Max Training Data so paper memory gets enough samples.
        """
        if side not in ("LONG", "SHORT") or not self._is_more_trades():
            return None
        if self.seconds_left is not None and self.seconds_left < self.min_seconds_left:
            return None
        if len(candles) < max(8, self.min_candles):
            return None
        cur = candles[-1]
        bucket_size = 45 if self._is_scalp_heavy() else (90 if self._is_max_training() else 180)
        bucket = int(cur.ts // bucket_size)
        if bucket == getattr(self, "_last_scout_bucket", -1):
            return None
        if not (self._directional_close(candles, side) or self._micro_followthrough(candles, side)):
            return None
        self._last_scout_bucket = bucket
        entry = cur.close
        recent = candles[-8:]
        buffer = max(entry * 0.00012, 3.0)
        if side == "LONG":
            stop = min(c.low for c in recent) - buffer
            risk = max(entry - stop, buffer)
            target = entry + risk * self.min_rr
        else:
            stop = max(c.high for c in recent) + buffer
            risk = max(stop - entry, buffer)
            target = entry - risk * self.min_rr
        rr = abs(target - entry) / max(abs(entry - stop), 0.0001)
        d.ready = True
        d.side = side
        d.state = "READY"
        d.grade = "C" if (self._is_max_training() or self._is_scalp_heavy()) else "B"
        d.confidence = 40 if self._is_scalp_heavy() else (42 if self._is_max_training() else 50)
        d.training_probe = True
        d.entry_model = "Scalp/Data Scout: 5m bias + 1m momentum" if self._is_scalp_heavy() else "Data Builder Scout: 5m bias + 1m momentum"
        d.trigger_quality = "Scout Probe"
        d.trigger_sequence = "Micro momentum scout"
        d.latest_fvg = "SCOUT_PROBE (no focused GAP)"
        d.active_fvg_key = f"SCOUT:{bucket}:{side}"
        d.focused_gap = d.active_fvg_key
        d.setup_signature = f"SCOUT|{side}|{d.trend_15m}|{d.trend_5m}|{d.session_label}"
        d.checklist.append("✅ Data Builder: labeled scout probe enabled")
        d.checklist.append("✅ Directional close / micro follow-through")
        d.checklist.append(f"✅ Risk/Reward: {rr:.2f}:1")
        d.safety_checks.append("✅ Scout/scalp probe is paper-training only and labeled in memory")
        d.reasons.append(reason)
        d.reasons.append("This exists to collect training data; it is not treated as a perfect CHoCH/FVG entry.")
        d.confidence_breakdown.append("+18 Directional micro momentum")
        d.confidence_breakdown.append("+10 Data builder probe")
        d.plan = TradePlan(side, entry, stop, target, rr, d.entry_model)
        d.next_action = "Open paper training scout"
        return d


    def _ema(self, values: list[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2.0 / (period + 1.0)
        ema = float(values[0])
        for v in values[1:]:
            ema = float(v) * k + ema * (1.0 - k)
        return ema

    def _ema_continuation_bias(self, candles: list[Candle]) -> tuple[str, str]:
        """8/20 EMA continuation filter.

        This mirrors the video lesson: stop blindly catching reversals; prefer
        continuation entries where pullbacks respect the moving-average flow.
        It is a filter, not a standalone trade signal.
        """
        if len(candles) < 24:
            return "WAIT", "building"
        closes = [float(c.close) for c in candles[-35:]]
        ema8 = self._ema(closes[-18:], 8)
        ema20 = self._ema(closes, 20)
        prev8 = self._ema(closes[-23:-1], 8) if len(closes) >= 23 else ema8
        last = closes[-1]
        slope_up = ema8 >= prev8
        if last >= ema8 >= ema20 and slope_up:
            return "LONG", "8EMA over 20EMA continuation up"
        if last <= ema8 <= ema20 and not slope_up:
            return "SHORT", "8EMA under 20EMA continuation down"
        return "WAIT", "mixed / no continuation edge"

    def _micro_followthrough(self, candles: list[Candle], side: str) -> bool:
        if len(candles) < 4:
            return False
        a, b, c = candles[-3], candles[-2], candles[-1]
        if side == "LONG":
            return b.close > b.open and c.close > c.open and c.close > max(a.close, b.close)
        return b.close < b.open and c.close < c.open and c.close < min(a.close, b.close)

    def _fvg_key(self, fvg: FVG) -> str:
        return f"{fvg.direction}:{int(fvg.end_ts)}:{round(fvg.top, 2)}:{round(fvg.bottom, 2)}"


    def _latest_bias_from_fvgs(self, fvgs: list[FVG]) -> str:
        fresh = [f for f in fvgs[-6:] if str(getattr(f, "status", "")).upper() != "FILLED"]
        if not fresh:
            return "WAIT"
        last = fresh[-1]
        return "LONG" if last.direction == "BULLISH" else "SHORT"

    def _micro_momentum_side(self, candles: list[Candle]) -> str:
        if len(candles) < 6:
            return "WAIT"
        first = candles[-6].close
        last = candles[-1].close
        move = (last - first) / first if first else 0.0
        if move > 0.00035:
            return "LONG"
        if move < -0.00035:
            return "SHORT"
        return "WAIT"

    def _directional_close(self, candles: list[Candle], side: str) -> bool:
        if len(candles) < 2:
            return False
        cur = candles[-1]
        prev = candles[-2]
        if side == "LONG":
            return cur.close > cur.open and cur.close > prev.close
        return cur.close < cur.open and cur.close < prev.close

    def _swing_levels(self, candles: list[Candle], lookback: int = 10) -> tuple[float, float]:
        sample = candles[-lookback-1:-1] if len(candles) > lookback else candles[:-1]
        if not sample:
            c = candles[-1]
            return c.high, c.low
        return max(c.high for c in sample), min(c.low for c in sample)

    def _liquidity_sweep(self, candles: list[Candle], side: str) -> bool:
        """Sweep means price took a nearby high/low first; it is NOT CHoCH by itself."""
        if len(candles) < 8:
            return False
        cur = candles[-1]
        prev_high, prev_low = self._swing_levels(candles, lookback=8)
        body_hi = max(cur.open, cur.close)
        body_lo = min(cur.open, cur.close)
        rng = max(cur.high - cur.low, 0.0001)
        if side == "LONG":
            # swept below a recent low and rejected back upward
            return cur.low < prev_low and cur.close > body_lo + rng * 0.45
        # swept above a recent high and rejected back downward
        return cur.high > prev_high and cur.close < body_hi - rng * 0.45

    def _choch(self, candles: list[Candle], side: str) -> bool:
        """CHoCH = Change of Character: break back through recent micro structure in the trade direction."""
        if len(candles) < 10:
            return False
        cur = candles[-1]
        # Use bars before the current trigger candle so the current close can break structure.
        structure = candles[-9:-1]
        if side == "LONG":
            recent_lower_high = max(c.high for c in structure[-5:])
            return cur.close > recent_lower_high
        recent_higher_low = min(c.low for c in structure[-5:])
        return cur.close < recent_higher_low

    def _displacement(self, candles: list[Candle], side: str, avg_body: float) -> bool:
        if len(candles) < 2:
            return False
        cur = candles[-1]
        body = abs(cur.close - cur.open)
        rng = max(cur.high - cur.low, 0.0001)
        strong_body = body >= max(avg_body * 0.75, rng * 0.42)
        if side == "LONG":
            return strong_body and cur.close > cur.open and cur.close >= cur.low + rng * 0.62
        return strong_body and cur.close < cur.open and cur.close <= cur.low + rng * 0.38

    def _trigger_sequence(self, side: str, sweep: bool, choch: bool, displacement: bool, confirmation: str | None) -> str:
        parts = []
        if sweep:
            parts.append("Sweep")
        if choch:
            parts.append("CHoCH")
        if displacement:
            parts.append("Displacement")
        if confirmation:
            parts.append(confirmation)
        if not parts:
            return "Waiting for Sweep → CHoCH"
        return " → ".join(parts)

    def _setup_signature(self, d: SetupDecision, fvg: FVG, side: str, confirmation: str | None) -> str:
        return "|".join([
            side,
            d.trend_15m,
            d.trend_5m,
            fvg.direction,
            fvg.status,
            confirmation or "NO_CONFIRM",
            getattr(d, "trigger_sequence", "NO_SEQUENCE"),
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

    def _invalid_reason(self, fvg: FVG, price: float, avg_body: float, age: int) -> str:
        if age < 2:
            return "GAP too new; waiting for retest"
        if age > self.max_fvg_age_bars:
            return f"GAP expired after {age} bars"
        if age > 32 and str(getattr(fvg, "status", "")).upper() == "ACTIVE":
            return "focused GAP stale without retest"
        if str(getattr(fvg, "status", "")).upper() == "FILLED":
            return "GAP fully filled before confirmation"
        lo = min(fvg.bottom, fvg.top)
        hi = max(fvg.bottom, fvg.top)
        gap_height = max(hi - lo, 0.01)
        far = max(gap_height * 4.0, avg_body * 6.0, price * 0.0015)
        if price > hi + far or price < lo - far:
            return "price moved too far away from focused GAP"
        return ""

    def _price_inside_fvg(self, price: float, fvg: FVG, avg_body: float = 1.0) -> bool:
        # Accept a near retest too. Exact-in-gap only was too strict for fast BTC candles.
        lo = min(fvg.bottom, fvg.top)
        hi = max(fvg.bottom, fvg.top)
        gap_height = max(hi - lo, 0.01)
        tolerance = max(avg_body * 0.8, gap_height * 0.35, price * 0.00008)
        return (lo - tolerance) <= price <= (hi + tolerance)

    def _confirmation(self, candles: list[Candle], side: str) -> str | None:
        if len(candles) < 3:
            return None
        patterns = detect_candlestick_patterns(candles[-5:])
        wanted = "BULLISH" if side == "LONG" else "BEARISH"
        # Prefer textbook candle names when they align with the trade direction.
        for p in patterns:
            if p.bias == wanted and p.strength >= 62:
                return p.name

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

    def _soft_confirmation(self, candles: list[Candle], side: str, fvg: FVG, avg_body: float) -> str | None:
        """Less perfect but useful confirmation for paper training.

        The bot still needs pullback + direction candle, but it no longer waits only
        for textbook engulfing. This creates training trades so memory can improve.
        """
        if len(candles) < 2:
            return None
        cur = candles[-1]
        body = abs(cur.close - cur.open)
        rng = max(cur.high - cur.low, 0.0001)
        body_ok = body >= max(avg_body * 0.55, rng * 0.35)
        mid = (min(fvg.bottom, fvg.top) + max(fvg.bottom, fvg.top)) / 2.0
        bias, name, strength = strongest_bias(candles[-5:])
        if side == "LONG":
            if bias == "BULLISH" and strength >= 48 and cur.close >= mid:
                return f"Bullish Candle Confirm: {name}"
            if cur.close > cur.open and body_ok and cur.close >= mid:
                return "Bullish Momentum Confirm"
        else:
            if bias == "BEARISH" and strength >= 48 and cur.close <= mid:
                return f"Bearish Candle Confirm: {name}"
            if cur.close < cur.open and body_ok and cur.close <= mid:
                return "Bearish Momentum Confirm"
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
