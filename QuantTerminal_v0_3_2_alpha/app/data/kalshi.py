"""Kalshi public-market helper for BTC15 timing.

This module keeps the app's 15-minute timer tied to the active Kalshi
BTC 15-minute market close_time when the public endpoint can be reached.
If Kalshi is unavailable or the ticker search changes, it falls back to the
normal UTC quarter-hour clock and clearly labels the timer as estimated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import threading
import time
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass
class KalshiMarketClock:
    ticker: str = ""
    title: str = ""
    close_time: Optional[datetime] = None
    source: str = "ESTIMATED"
    last_error: str = ""
    updated_at: float = 0.0

    def seconds_left(self) -> int:
        if self.close_time:
            now = datetime.now(timezone.utc)
            return max(0, int((self.close_time - now).total_seconds()))
        now = int(time.time())
        return 900 - (now % 900)

    def label(self) -> str:
        secs = self.seconds_left()
        return f"{secs//60:02d}:{secs%60:02d}"


class KalshiBTC15Timer:
    BASE = "https://external-api.kalshi.com/trade-api/v2"

    def __init__(self) -> None:
        self.clock = KalshiMarketClock()
        self._lock = threading.Lock()
        self._refreshing = False

    def snapshot(self) -> KalshiMarketClock:
        with self._lock:
            return KalshiMarketClock(
                ticker=self.clock.ticker,
                title=self.clock.title,
                close_time=self.clock.close_time,
                source=self.clock.source,
                last_error=self.clock.last_error,
                updated_at=self.clock.updated_at,
            )

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> None:
        try:
            market = self._find_active_btc15_market()
            if not market:
                self._set_error("No open BTC15 market found; using quarter-hour estimate")
                return
            close_time = self._parse_time(market.get("close_time") or market.get("latest_expiration_time"))
            title = market.get("title") or market.get("subtitle") or market.get("yes_sub_title") or "BTC15"
            with self._lock:
                self.clock = KalshiMarketClock(
                    ticker=str(market.get("ticker", "")),
                    title=str(title),
                    close_time=close_time,
                    source="KALSHI" if close_time else "ESTIMATED",
                    last_error="" if close_time else "Market had no close_time",
                    updated_at=time.time(),
                )
        except Exception as exc:
            self._set_error(str(exc)[:160])
        finally:
            self._refreshing = False

    def _set_error(self, message: str) -> None:
        with self._lock:
            self.clock.source = "ESTIMATED"
            self.clock.last_error = message
            self.clock.updated_at = time.time()

    def _parse_time(self, value: str | None) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{self.BASE}{path}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.2"})
        with urlopen(req, timeout=7) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _find_active_btc15_market(self) -> Optional[dict]:
        # Kalshi tickers/series can change, so don't hardcode only one ticker.
        # Search open markets and rank the ones that look like BTC 15-minute crypto markets.
        now = int(time.time())
        data = self._get_json("/markets", {
            "status": "open",
            "limit": 1000,
            "min_close_ts": now - 60,
            "max_close_ts": now + 3600,
        })
        markets = data.get("markets", []) or []
        scored: list[tuple[int, dict]] = []
        for m in markets:
            hay = " ".join(str(m.get(k, "")) for k in (
                "ticker", "event_ticker", "series_ticker", "title", "subtitle", "yes_sub_title", "no_sub_title"
            )).upper()
            score = 0
            if "BTC" in hay or "BITCOIN" in hay:
                score += 5
            if "15" in hay or "FIFTEEN" in hay:
                score += 2
            if "CRYPTO" in hay:
                score += 1
            if "KXBTC" in hay:
                score += 4
            close_dt = self._parse_time(m.get("close_time"))
            if close_dt and close_dt > datetime.now(timezone.utc):
                score += 2
            if score >= 6:
                scored.append((score, m))
        if not scored:
            return None
        scored.sort(key=lambda x: (x[0], x[1].get("close_time", "")), reverse=True)
        # Prefer the nearest close after now, not some later market.
        candidates = [m for _, m in scored]
        candidates.sort(key=lambda m: self._parse_time(m.get("close_time")) or datetime.max.replace(tzinfo=timezone.utc))
        return candidates[0]
