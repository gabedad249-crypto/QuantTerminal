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
    status: str = "ACTIVE"

class FVGEngine:
    """Simple 3-candle FVG detector. Later we upgrade scoring/mitigation."""

    def detect(self, candles: List[Candle]) -> List[FVG]:
        fvgs: List[FVG] = []
        if len(candles) < 3:
            return fvgs
        for i in range(2, len(candles)):
            c1 = candles[i - 2]
            c3 = candles[i]
            if c1.high < c3.low:
                fvgs.append(FVG("BULLISH", c1.ts, c3.ts, top=c3.low, bottom=c1.high))
            elif c1.low > c3.high:
                fvgs.append(FVG("BEARISH", c1.ts, c3.ts, top=c1.low, bottom=c3.high))
        return fvgs[-25:]
