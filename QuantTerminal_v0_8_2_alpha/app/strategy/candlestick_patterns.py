from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.strategy.fvg_engine import Candle


@dataclass
class CandlePattern:
    name: str
    bias: str  # BULLISH / BEARISH / NEUTRAL
    strength: int  # 0-100 simple quality score
    note: str


def _body(c: Candle) -> float:
    return abs(float(c.close) - float(c.open))


def _rng(c: Candle) -> float:
    return max(float(c.high) - float(c.low), 0.000001)


def _upper(c: Candle) -> float:
    return float(c.high) - max(float(c.open), float(c.close))


def _lower(c: Candle) -> float:
    return min(float(c.open), float(c.close)) - float(c.low)


def _bull(c: Candle) -> bool:
    return float(c.close) > float(c.open)


def _bear(c: Candle) -> bool:
    return float(c.close) < float(c.open)


def _small_body(c: Candle, threshold: float = 0.28) -> bool:
    return _body(c) <= _rng(c) * threshold


def _long_body(c: Candle, candles: list[Candle], lookback: int = 20) -> bool:
    if len(candles) < 3:
        return _body(c) >= _rng(c) * 0.55
    recent = candles[-lookback-1:-1] if len(candles) > 1 else []
    avg = sum(_body(x) for x in recent) / max(1, len(recent))
    return _body(c) >= max(avg * 1.25, _rng(c) * 0.50)


def _trend_hint(candles: list[Candle], lookback: int = 6) -> str:
    if len(candles) < 3:
        return "SIDEWAYS"
    look = candles[-lookback:]
    if look[-1].close > look[0].close and max(x.high for x in look[-3:]) >= max(x.high for x in look[:-2]):
        return "UP"
    if look[-1].close < look[0].close and min(x.low for x in look[-3:]) <= min(x.low for x in look[:-2]):
        return "DOWN"
    return "SIDEWAYS"


def _append_unique(rows: list[CandlePattern], p: CandlePattern) -> None:
    if all(x.name != p.name for x in rows):
        rows.append(p)


def detect_candlestick_patterns(candles: Iterable[Candle]) -> list[CandlePattern]:
    """Rule-based candlestick reader for hover cards and strategy labels.

    This uses common OHLC relationships: body size, upper/lower wick, engulfing
    bodies, inside bars, stars, and three-candle continuation patterns. It is a
    detector/coach, not a guarantee that price will reverse.
    """
    candles = list(candles)
    rows: list[CandlePattern] = []
    if not candles:
        return rows
    c = candles[-1]
    rng = _rng(c)
    body = _body(c)
    upper = _upper(c)
    lower = _lower(c)
    trend = _trend_hint(candles)

    # One-candle anatomy patterns.
    if body <= rng * 0.08:
        if lower >= rng * 0.55 and upper <= rng * 0.18:
            _append_unique(rows, CandlePattern("Dragonfly Doji", "BULLISH", 76, "Tiny body with long lower wick; buyers rejected lower prices."))
        elif upper >= rng * 0.55 and lower <= rng * 0.18:
            _append_unique(rows, CandlePattern("Gravestone Doji", "BEARISH", 76, "Tiny body with long upper wick; sellers rejected higher prices."))
        elif upper >= rng * 0.30 and lower >= rng * 0.30:
            _append_unique(rows, CandlePattern("Long-Legged Doji", "NEUTRAL", 55, "Indecision candle with wicks on both sides."))
        else:
            _append_unique(rows, CandlePattern("Doji", "NEUTRAL", 50, "Open and close are nearly equal; momentum paused."))
    elif _small_body(c, 0.32) and upper >= body * 1.2 and lower >= body * 1.2:
        _append_unique(rows, CandlePattern("Spinning Top", "NEUTRAL", 45, "Small real body with both wicks; buyers and sellers are balanced."))

    lower_reject = lower >= max(body * 1.8, rng * 0.45) and upper <= max(body * 0.75, rng * 0.25)
    upper_reject = upper >= max(body * 1.8, rng * 0.45) and lower <= max(body * 0.75, rng * 0.25)
    if lower_reject:
        if trend == "DOWN" or _bull(c):
            _append_unique(rows, CandlePattern("Hammer / Bullish Pin Bar", "BULLISH", 78, "Long lower wick shows downside rejection."))
        else:
            _append_unique(rows, CandlePattern("Hanging Man", "BEARISH", 58, "Long lower wick after strength can warn of weakening buyers."))
    if upper_reject:
        if trend == "UP" or _bear(c):
            _append_unique(rows, CandlePattern("Shooting Star / Bearish Pin Bar", "BEARISH", 78, "Long upper wick shows upside rejection."))
        else:
            _append_unique(rows, CandlePattern("Inverted Hammer", "BULLISH", 58, "Upper wick after weakness can hint at buyers testing higher."))

    # Two-candle patterns.
    if len(candles) >= 2:
        p = candles[-2]
        p_hi = max(p.open, p.close); p_lo = min(p.open, p.close)
        c_hi = max(c.open, c.close); c_lo = min(c.open, c.close)
        # Body engulfing, not full candle engulfing.
        if _bear(p) and _bull(c) and c_hi >= p_hi and c_lo <= p_lo and body >= max(_body(p) * 0.85, rng * 0.35):
            _append_unique(rows, CandlePattern("Bullish Engulfing", "BULLISH", 88, "Green body engulfs prior red body; buyers took control."))
        if _bull(p) and _bear(c) and c_hi >= p_hi and c_lo <= p_lo and body >= max(_body(p) * 0.85, rng * 0.35):
            _append_unique(rows, CandlePattern("Bearish Engulfing", "BEARISH", 88, "Red body engulfs prior green body; sellers took control."))
        if c_hi <= p_hi and c_lo >= p_lo and body <= max(_body(p) * 0.60, _rng(p) * 0.35):
            _append_unique(rows, CandlePattern("Inside Bar / Harami", "NEUTRAL", 60, "Current body is contained inside prior body; compression/decision point."))
        # Tweezer-ish highs/lows with tight tolerance.
        tol = max((_rng(p) + rng) * 0.035, max(c.close, p.close) * 0.00005)
        if abs(c.high - p.high) <= tol and trend == "UP":
            _append_unique(rows, CandlePattern("Tweezer Top", "BEARISH", 62, "Two nearby highs show possible resistance."))
        if abs(c.low - p.low) <= tol and trend == "DOWN":
            _append_unique(rows, CandlePattern("Tweezer Bottom", "BULLISH", 62, "Two nearby lows show possible support."))
        # Piercing / dark cloud using midpoint of previous candle body.
        p_mid = (p.open + p.close) / 2.0
        if _bear(p) and _bull(c) and c.open < p.low and c.close > p_mid:
            _append_unique(rows, CandlePattern("Piercing Line", "BULLISH", 70, "Bullish candle opens below prior low and closes back through midpoint."))
        if _bull(p) and _bear(c) and c.open > p.high and c.close < p_mid:
            _append_unique(rows, CandlePattern("Dark Cloud Cover", "BEARISH", 70, "Bearish candle opens above prior high and closes back under midpoint."))

    # Three-candle patterns.
    if len(candles) >= 3:
        a, b, c3 = candles[-3], candles[-2], candles[-1]
        a_mid = (a.open + a.close) / 2.0
        if _bear(a) and _small_body(b, 0.35) and _bull(c3) and c3.close > a_mid:
            _append_unique(rows, CandlePattern("Morning Star", "BULLISH", 84, "Three-candle bullish reversal: selloff, pause, strong bullish close."))
        if _bull(a) and _small_body(b, 0.35) and _bear(c3) and c3.close < a_mid:
            _append_unique(rows, CandlePattern("Evening Star", "BEARISH", 84, "Three-candle bearish reversal: rally, pause, strong bearish close."))
        if all(_bull(x) for x in (a, b, c3)) and c3.close > b.close > a.close and all(_long_body(x, candles) for x in (a, b, c3)):
            _append_unique(rows, CandlePattern("Three White Soldiers", "BULLISH", 78, "Three strong bullish candles stepping higher."))
        if all(_bear(x) for x in (a, b, c3)) and c3.close < b.close < a.close and all(_long_body(x, candles) for x in (a, b, c3)):
            _append_unique(rows, CandlePattern("Three Black Crows", "BEARISH", 78, "Three strong bearish candles stepping lower."))

    # Plain candle read if nothing bigger was found.
    if not rows:
        if _bull(c) and body >= rng * 0.45:
            rows.append(CandlePattern("Bullish Momentum Candle", "BULLISH", 48, "Close is above open with meaningful body."))
        elif _bear(c) and body >= rng * 0.45:
            rows.append(CandlePattern("Bearish Momentum Candle", "BEARISH", 48, "Close is below open with meaningful body."))
        else:
            rows.append(CandlePattern("Small / Neutral Candle", "NEUTRAL", 35, "No major pattern; candle is mostly noise by itself."))

    rows.sort(key=lambda x: x.strength, reverse=True)
    return rows[:4]


def pattern_summary(candles: Iterable[Candle]) -> str:
    pats = detect_candlestick_patterns(candles)
    return ", ".join(f"{p.name} ({p.bias})" for p in pats) if pats else "No pattern"


def strongest_bias(candles: Iterable[Candle]) -> tuple[str, str, int]:
    pats = detect_candlestick_patterns(candles)
    for p in pats:
        if p.bias in ("BULLISH", "BEARISH"):
            return p.bias, p.name, p.strength
    if pats:
        return pats[0].bias, pats[0].name, pats[0].strength
    return "NEUTRAL", "No pattern", 0
