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

_MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}


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

    def __init__(self, target_url: str | None = None) -> None:
        self.target_url = target_url or "https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/kxbtc15m-26jun280030"
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
            )

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self) -> None:
        try:
            # Important: the Kalshi URL you paste can be a specific contract that
            # has already rolled, while the phone app may be showing the current
            # active 15-minute contract. Prefer the currently open KXBTC15M
            # contract closing soonest. Exact target ticker is used only if it is
            # still open and inside the active BTC15 window.
            market = None
            exact = self._get_exact_market(self.target_ticker) if self.target_ticker else None
            url_close = self._parse_ticker_close_time(self.target_ticker)

            # If the pasted Kalshi URL has an embedded active ticker, trust that
            # first. This fixes the common phone-vs-PC mismatch where Kalshi UI
            # is on one exact market but the public market search returns a stale
            # or different open contract.
            if url_close and url_close > datetime.now(timezone.utc):
                with self._lock:
                    self.clock = KalshiMarketClock(
                        ticker=self.target_ticker,
                        title="BTC15 from pasted Kalshi URL",
                        close_time=url_close,
                        source="URL_TICKER",
                        last_error="Using close time parsed directly from pasted Kalshi URL ticker",
                        updated_at=time.time(),
                    )
                return

            if exact and self._is_current_btc15_market(exact):
                market = exact
            if not market:
                market = self._find_active_btc15_market()
            if not market and exact:
                market = exact
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


    def _extract_ticker(self, value: str | None) -> str:
        if not value:
            return ""
        raw = str(value).strip().split("?")[0].rstrip("/")
        last = raw.split("/")[-1]
        # Kalshi URLs look like .../kxbtc15m-26jun280030. API tickers are uppercase.
        return last.upper() if last.upper().startswith("KXBTC15M-") else ""

    def _parse_ticker_close_time(self, ticker: str | None) -> Optional[datetime]:
        """Parse KXBTC15M-26JUN280030 -> 2026-06-28 00:30 UTC.

        Kalshi BTC15 URLs include the expiration timestamp in the ticker.
        Parsing it locally gives the terminal the same countdown as the exact
        market page even when the public search endpoint returns a different
        active market.
        """
        if not ticker or not ticker.upper().startswith("KXBTC15M-"):
            return None
        code = ticker.upper().split("KXBTC15M-", 1)[1]
        # YYMMMDDHHMM, e.g. 26JUN280030
        try:
            yy = int(code[0:2])
            mon = _MONTHS.get(code[2:5])
            dd = int(code[5:7])
            hh = int(code[7:9])
            mm = int(code[9:11])
            if not mon:
                return None
            return datetime(2000 + yy, mon, dd, hh, mm, tzinfo=timezone.utc)
        except Exception:
            return None

    def set_target_url(self, value: str) -> None:
        with self._lock:
            self.target_url = value.strip()
            self.target_ticker = self._extract_ticker(self.target_url)
            self.clock.last_error = "Target market changed; refreshing..."
        self.refresh_async()

    def _is_current_btc15_market(self, market: dict) -> bool:
        close_dt = self._parse_time(market.get("close_time") or market.get("latest_expiration_time"))
        status = str(market.get("status", "")).lower()
        now_dt = datetime.now(timezone.utc)
        if not close_dt or close_dt <= now_dt:
            return False
        seconds = int((close_dt - now_dt).total_seconds())
        # Active BTC15 market should close within roughly the next 15 minutes.
        return seconds <= 16 * 60 and status in ("", "open", "active")

    def _get_exact_market(self, ticker: str) -> Optional[dict]:
        if not ticker:
            return None
        try:
            url = f"{self.BASE}/markets/{ticker}"
            req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.6"})
            with urlopen(req, timeout=7) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            market = data.get("market") or data
            if isinstance(market, dict) and market.get("ticker"):
                return market
        except Exception as exc:
            with self._lock:
                self.clock.last_error = f"Exact ticker {ticker} lookup failed: {str(exc)[:100]}"
        return None

    def _parse_time(self, value: str | None) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{self.BASE}{path}?{urlencode(params)}"
        req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.3"})
        with urlopen(req, timeout=7) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _find_active_btc15_market(self) -> Optional[dict]:
        # Prefer the actual 15-minute Bitcoin series when available. Public docs
        # recommend using series/event/market fields instead of parsing tickers.
        now = int(time.time())
        searches = [
            {"status": "open", "series_ticker": "KXBTC15M", "limit": 500},
            {"status": "open", "event_ticker": "KXBTC15M", "limit": 500},
            {"status": "open", "limit": 1000, "min_close_ts": now - 60, "max_close_ts": now + 1800},
        ]
        all_markets: list[dict] = []
        for params in searches:
            try:
                data = self._get_json("/markets", params)
                all_markets.extend(data.get("markets", []) or [])
            except Exception:
                continue

        # De-dupe by ticker.
        unique: dict[str, dict] = {}
        for m in all_markets:
            unique[str(m.get("ticker", id(m)))] = m

        scored: list[tuple[int, datetime, dict]] = []
        now_dt = datetime.now(timezone.utc)
        for m in unique.values():
            hay = " ".join(str(m.get(k, "")) for k in (
                "ticker", "event_ticker", "series_ticker", "title", "subtitle", "yes_sub_title", "no_sub_title"
            )).upper()
            close_dt = self._parse_time(m.get("close_time") or m.get("latest_expiration_time"))
            if not close_dt or close_dt <= now_dt:
                continue
            score = 0
            if str(m.get("series_ticker", "")).upper() == "KXBTC15M":
                score += 20
            if "KXBTC15M" in hay:
                score += 15
            if "BTC" in hay or "BITCOIN" in hay:
                score += 6
            if "15" in hay or "FIFTEEN" in hay:
                score += 4
            if "CRYPTO" in hay:
                score += 1
            # Prefer the market closing soonest after now, because that is the
            # active window the Kalshi UI usually shows.
            seconds = max(0, int((close_dt - now_dt).total_seconds()))
            if seconds <= 16 * 60:
                score += 20
            elif seconds <= 30 * 60:
                score += 3
            if score >= 10:
                scored.append((score, close_dt, m))
        if not scored:
            return None
        # The phone app normally shows the nearest open BTC15 contract. If two
        # candidates score similarly, choose the soonest close_time.
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][2]
