import time
from app.strategy.fvg_engine import Candle

class CandleBuilder:
    def __init__(self, timeframe_seconds: int = 60) -> None:
        self.timeframe_seconds = timeframe_seconds
        self.candles: list[Candle] = []

    def seed(self, candles: list[Candle]) -> None:
        """Load historical candles once so the terminal has context immediately."""
        merged = {int(c.ts): c for c in self.candles}
        for c in candles:
            merged[int(c.ts)] = c
        self.candles = [merged[k] for k in sorted(merged)][-800:]

    def update_price(self, price: float, volume: float = 0.0) -> list[Candle]:
        now = time.time()
        bucket = now - (now % self.timeframe_seconds)
        if not self.candles or int(self.candles[-1].ts) != int(bucket):
            self.candles.append(Candle(bucket, price, price, price, price, volume))
            self.candles = self.candles[-800:]
        else:
            c = self.candles[-1]
            c.high = max(c.high, price)
            c.low = min(c.low, price)
            c.close = price
            c.volume += volume
        return self.candles

def aggregate_candles(candles: list[Candle], timeframe_seconds: int) -> list[Candle]:
    """Aggregate 1m candles into 5m/15m candles for trend/structure context."""
    buckets: dict[int, Candle] = {}
    for c in candles:
        bucket = int(c.ts) - (int(c.ts) % timeframe_seconds)
        if bucket not in buckets:
            buckets[bucket] = Candle(bucket, c.open, c.high, c.low, c.close, c.volume)
        else:
            b = buckets[bucket]
            b.high = max(b.high, c.high)
            b.low = min(b.low, c.low)
            b.close = c.close
            b.volume += c.volume
    return [buckets[k] for k in sorted(buckets)]

def seconds_until_next_15m() -> int:
    now = int(time.time())
    return 900 - (now % 900)
