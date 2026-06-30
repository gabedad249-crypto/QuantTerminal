import json
import random
import threading
import time
from typing import Callable
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from app.strategy.fvg_engine import Candle

try:
    import websocket  # type: ignore
except Exception:  # pragma: no cover
    websocket = None

class CoinbaseFeed:
    def __init__(self, on_price: Callable[[float], None], symbol: str = "BTC-USD") -> None:
        self.on_price = on_price
        self.symbol = symbol
        self._running = False
        self._thread: threading.Thread | None = None
        self.last_price: float | None = None
        self.last_source = "INIT"
        self.last_tick_at = 0.0
        self.last_error = ""

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def fetch_historical_candles(self, granularity: int = 60, limit: int = 240) -> list[Candle]:
        """Fetch recent Coinbase candles. Coinbase returns newest-to-oldest arrays.
        This gives the strategy enough lookback to actually think before suggesting a buy-in.
        """
        now = int(time.time())
        start = now - granularity * limit
        params = urlencode({"granularity": granularity, "start": start, "end": now})
        url = f"https://api.exchange.coinbase.com/products/{self.symbol}/candles?{params}"
        req = Request(url, headers={"User-Agent": "QuantTerminal/0.3"})
        with urlopen(req, timeout=10) as r:
            raw = json.loads(r.read().decode("utf-8"))
        candles: list[Candle] = []
        for row in raw:
            # [time, low, high, open, close, volume]
            ts, low, high, open_, close, vol = row
            candles.append(Candle(float(ts), float(open_), float(high), float(low), float(close), float(vol)))
        candles.sort(key=lambda c: c.ts)
        if candles:
            self.last_price = candles[-1].close
        return candles[-limit:]

    def start_price(self) -> float | None:
        try:
            with urlopen(f"https://api.exchange.coinbase.com/products/{self.symbol}/ticker", timeout=5) as r:
                price = float(json.loads(r.read().decode("utf-8"))["price"])
                self.last_price = price
                self.last_tick_at = time.time()
                self.last_source = "REST_TICKER"
                return price
        except Exception:
            return self.last_price

    def _run(self) -> None:
        if websocket:
            try:
                self._run_ws()
                return
            except Exception:
                pass
        self._run_rest_fallback()

    def _run_ws(self) -> None:
        def on_open(ws):
            ws.send(json.dumps({
                "type": "subscribe",
                "product_ids": [self.symbol],
                "channels": ["ticker"]
            }))

        def on_message(ws, message):
            if not self._running:
                ws.close()
                return
            data = json.loads(message)
            if "price" in data:
                price = float(data["price"])
                self.last_price = price
                self.last_tick_at = time.time()
                self.last_error = ""
                self.last_source = "WS"
                self.on_price(price)

        while self._running:
            ws = websocket.WebSocketApp("wss://ws-feed.exchange.coinbase.com", on_open=on_open, on_message=on_message)
            ws.run_forever(ping_interval=20, ping_timeout=10)
            time.sleep(2)

    def _run_rest_fallback(self) -> None:
        while self._running:
            try:
                with urlopen(f"https://api.exchange.coinbase.com/products/{self.symbol}/ticker", timeout=5) as r:
                    price = float(json.loads(r.read().decode("utf-8"))["price"])
                    self.last_source = "REST"
            except Exception as exc:
                # Last-resort fake tick only so UI stays alive offline. It is labeled as SIM.
                price = (self.last_price or 100000.0) + random.uniform(-80, 80)
                self.last_error = str(exc)
                self.last_source = "SIM"
            self.last_price = price
            self.last_tick_at = time.time()
            self.on_price(price)
            time.sleep(1)
