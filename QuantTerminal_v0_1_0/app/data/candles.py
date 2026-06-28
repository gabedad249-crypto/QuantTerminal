import time
from app.strategy.fvg_engine import Candle

class CandleBuilder:
    def __init__(self, timeframe_seconds: int = 60) -> None:
        self.timeframe_seconds = timeframe_seconds
        self.candles: list[Candle] = []

    def update_price(self, price: float, volume: float = 0.0) -> list[Candle]:
        now = time.time()
        bucket = now - (now % self.timeframe_seconds)
        if not self.candles or self.candles[-1].ts != bucket:
            self.candles.append(Candle(bucket, price, price, price, price, volume))
            self.candles = self.candles[-500:]
        else:
            c = self.candles[-1]
            c.high = max(c.high, price)
            c.low = min(c.low, price)
            c.close = price
            c.volume += volume
        return self.candles

def seconds_until_next_15m() -> int:
    now = int(time.time())
    return 900 - (now % 900)
