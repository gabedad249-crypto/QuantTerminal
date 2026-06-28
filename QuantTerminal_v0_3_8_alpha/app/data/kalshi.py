"""Kalshi public-market helper for BTC15 timing.

v0.3.8 focuses on the category page the user actually watches:
https://kalshi.com/category/crypto/btc?frequency=fifteen_min

The app now treats that category URL as "track the currently active KXBTC15M
market" instead of trying to parse a stale exact ticker. Exact market URLs are
still supported, but only if the embedded ticker is still inside the current
active 15-minute window.
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

_MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
CATEGORY_URL = "https://kalshi.com/category/crypto/btc?frequency=fifteen_min"


@dataclass
class KalshiMarketClock:
    ticker: str = ""
    title: str = ""
    close_time: Optional[datetime] = None
    source: str = "ESTIMATED"
    last_error: str = ""
    updated_at: float = 0.0
    candidate_count: int = 0

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

    def __init__(self, target_url: str | None = None) -> None:
        self.target_url = target_url or CATEGORY_URL
        self.target_ticker = self._extract_ticker(self.target_url)
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
                candidate_count=self.clock.candidate_count,
            )

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> None:
        try:
            now_dt = datetime.now(timezone.utc)
            market = None
            exact = self._get_exact_market(self.target_ticker) if self.target_ticker else None
            url_close = self._parse_ticker_close_time(self.target_ticker)

            # Use exact URL only if it is still the current/next active BTC15.
            # Stale exact links were the reason PC timer could show 0 while phone
            # category page showed the active market with minutes left.
            if exact and self._is_current_btc15_market(exact):
                market = exact
            elif url_close and 0 < int((url_close - now_dt).total_seconds()) <= 16 * 60:
                with self._lock:
                    self.clock = KalshiMarketClock(
                        ticker=self.target_ticker,
                        title="BTC15 exact URL ticker",
                        close_time=url_close,
                        source="URL_TICKER",
                        last_error="Exact market URL is still active",
                        updated_at=time.time(),
                        candidate_count=1,
                    )
                return
            else:
                market = self._find_active_btc15_market()

            if not market:
                self._set_error("No open KXBTC15M market found; using quarter-hour estimate")
                return

            close_time = self._parse_time(market.get("close_time") or market.get("latest_expiration_time"))
            title = market.get("title") or market.get("subtitle") or market.get("yes_sub_title") or "BTC15"
            with self._lock:
                self.clock = KalshiMarketClock(
                    ticker=str(market.get("ticker", "")),
                    title=str(title),
                    close_time=close_time,
                    source="KALSHI_ACTIVE" if close_time else "ESTIMATED",
                    last_error="Tracking nearest open KXBTC15M from category-style sync" if close_time else "Market had no close_time",
                    updated_at=time.time(),
                    candidate_count=int(market.get("_candidate_count", 0) or 0),
                )
        except Exception as exc:
            self._set_error(str(exc)[:180])
        finally:
            self._refreshing = False

    def _set_error(self, message: str) -> None:
        with self._lock:
            self.clock.source = "ESTIMATED"
            self.clock.last_error = message
            self.clock.updated_at = time.time()

    def _extract_ticker(self, value: str | None) -> str:
        if not value:
            return ""
        raw = str(value).strip().split("?")[0].rstrip("/")
        last = raw.split("/")[-1]
        return last.upper() if last.upper().startswith("KXBTC15M-") else ""

    def _parse_ticker_close_time(self, ticker: str | None) -> Optional[datetime]:
        if not ticker or not ticker.upper().startswith("KXBTC15M-"):
            return None
        code = ticker.upper().split("KXBTC15M-", 1)[1]
        try:
            yy = int(code[0:2]); mon = _MONTHS.get(code[2:5]); dd = int(code[5:7])
            hh = int(code[7:9]); mm = int(code[9:11])
            if not mon:
                return None
            return datetime(2000 + yy, mon, dd, hh, mm, tzinfo=timezone.utc)
        except Exception:
            return None

    def set_target_url(self, value: str) -> None:
        with self._lock:
            self.target_url = value.strip() or CATEGORY_URL
            self.target_ticker = self._extract_ticker(self.target_url)
            self.clock.last_error = "Target changed; refreshing active BTC15 market..."
        self.refresh_async()

    def _is_current_btc15_market(self, market: dict) -> bool:
        close_dt = self._parse_time(market.get("close_time") or market.get("latest_expiration_time"))
        status = str(market.get("status", "")).lower()
        now_dt = datetime.now(timezone.utc)
        if not close_dt or close_dt <= now_dt:
            return False
        seconds = int((close_dt - now_dt).total_seconds())
        hay = " ".join(str(market.get(k, "")) for k in ("ticker","series_ticker","event_ticker","title","subtitle")).upper()
        return seconds <= 16 * 60 and status in ("", "open", "active") and "KXBTC15M" in hay

    def _get_exact_market(self, ticker: str) -> Optional[dict]:
        if not ticker:
            return None
        try:
            url = f"{self.BASE}/markets/{ticker}"
            req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.8"})
            with urlopen(req, timeout=7) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            market = data.get("market") or data
            if isinstance(market, dict) and market.get("ticker"):
                return market
        except Exception as exc:
            with self._lock:
                self.clock.last_error = f"Exact ticker lookup failed: {str(exc)[:100]}"
        return None

    def _parse_time(self, value: str | None) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{self.BASE}{path}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.8"})
        with urlopen(req, timeout=7) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _find_active_btc15_market(self) -> Optional[dict]:
        now = int(time.time())
        searches = [
            {"status": "open", "series_ticker": "KXBTC15M", "limit": 1000},
            {"status": "open", "event_ticker": "KXBTC15M", "limit": 1000},
            {"status": "open", "limit": 1000, "min_close_ts": now - 30, "max_close_ts": now + 1200},
            {"status": "open", "limit": 1000},
        ]
        unique: dict[str, dict] = {}
        for params in searches:
            try:
                data = self._get_json("/markets", params)
                for m in data.get("markets", []) or []:
                    ticker = str(m.get("ticker", ""))
                    if ticker:
                        unique[ticker] = m
            except Exception:
                continue

        now_dt = datetime.now(timezone.utc)
        candidates: list[tuple[int, datetime, dict]] = []
        for m in unique.values():
            hay = " ".join(str(m.get(k, "")) for k in (
                "ticker", "event_ticker", "series_ticker", "title", "subtitle", "yes_sub_title", "no_sub_title"
            )).upper()
            if "KXBTC15M" not in hay:
                continue
            close_dt = self._parse_time(m.get("close_time") or m.get("latest_expiration_time"))
            if not close_dt or close_dt <= now_dt:
                continue
            seconds = int((close_dt - now_dt).total_seconds())
            # The category page generally displays the current open market closing
            # soonest, not a later one. Do not prefer a higher-scored later market.
            score = 1000 - max(0, seconds)
            if 0 < seconds <= 16 * 60:
                score += 10000
            candidates.append((score, close_dt, m))

        if not candidates:
            return None
        candidates.sort(key=lambda x: (-x[0], x[1]))
        chosen = candidates[0][2]
        chosen["_candidate_count"] = len(candidates)
        return chosen
