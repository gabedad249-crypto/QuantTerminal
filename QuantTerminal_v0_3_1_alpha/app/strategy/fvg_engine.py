from dataclasses import dataclass
from typing import List

@dataclass
class Candle:
    ts: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

@dataclass
class FVG:
    direction: str  # BULLISH or BEARISH
    start_ts: float
    end_ts: float
    top: float
    bottom: float
    status: str = "ACTIVE"  # ACTIVE / TOUCHED / FILLED

    @property
    def label(self) -> str:
        if self.status == "FILLED":
            return "GAP FILLED"
        if self.status == "TOUCHED":
            return "GAP TOUCHED"
        return "GAP"

class FVGEngine:
    """3-candle Fair Value Gap detector with basic mitigation status."""

    def detect(self, candles: List[Candle]) -> List[FVG]:
        fvgs: List[FVG] = []
        if len(candles) < 3:
            return fvgs
        for i in range(2, len(candles)):
            c1 = candles[i - 2]
            c3 = candles[i]
            if c1.high < c3.low:
                fvg = FVG("BULLISH", c1.ts, c3.ts, top=c3.low, bottom=c1.high)
                self._update_status(fvg, candles[i + 1:])
                fvgs.append(fvg)
            elif c1.low > c3.high:
                fvg = FVG("BEARISH", c1.ts, c3.ts, top=c1.low, bottom=c3.high)
                self._update_status(fvg, candles[i + 1:])
                fvgs.append(fvg)
        return fvgs[-40:]

    def _update_status(self, fvg: FVG, future: List[Candle]) -> None:
        if not future:
            return
        hi = max(fvg.top, fvg.bottom)
        lo = min(fvg.top, fvg.bottom)
        for c in future:
            touched = c.low <= hi and c.high >= lo
            if not touched:
                continue
            fvg.status = "TOUCHED"
            # Full mitigation is when price trades through the far side of the gap.
            if fvg.direction == "BULLISH" and c.low <= lo:
                fvg.status = "FILLED"
                return
            if fvg.direction == "BEARISH" and c.high >= hi:
                fvg.status = "FILLED"
                return
