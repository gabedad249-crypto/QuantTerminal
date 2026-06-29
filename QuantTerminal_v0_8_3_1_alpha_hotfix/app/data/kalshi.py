"""Kalshi public-market helper for BTC15 timing.

v0.3.9 fixes the biggest timer issue: the app no longer trusts the PC clock
alone. It pulls Kalshi/server time from HTTP Date headers, searches the category
page for the live KXBTC15M ticker, then falls back to the public markets API,
then finally to a server-time 15-minute estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import threading
import time
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
CATEGORY_URL = "https://kalshi.com/category/crypto/btc?frequency=fifteen_min"
TICKER_RE = re.compile(r"KXBTC15M-[0-9]{2}[A-Z]{3}[0-9]{6}")


@dataclass
class KalshiMarketClock:
    ticker: str = ""
    title: str = ""
    close_time: Optional[datetime] = None
    source: str = "ESTIMATED"
    last_error: str = ""
    updated_at: float = 0.0
    candidate_count: int = 0
    server_offset_seconds: float = 0.0
    yes_bid: int | None = None
    yes_ask: int | None = None
    no_bid: int | None = None
    no_ask: int | None = None
    last_price: int | None = None
    volume: int | None = None
    liquidity: int | None = None

    def price_line(self) -> str:
        def fmt(v):
            return "--" if v is None else f"{int(v)}¢"
        spread = self.spread_cents()
        spread_txt = "--" if spread is None else f"{spread}¢"
        return (
            f"YES {fmt(self.yes_bid)}/{fmt(self.yes_ask)} | "
            f"NO {fmt(self.no_bid)}/{fmt(self.no_ask)} | "
            f"last {fmt(self.last_price)} | spread {spread_txt}"
        )

    def spread_cents(self) -> int | None:
        spreads = []
        if self.yes_bid is not None and self.yes_ask is not None:
            spreads.append(max(0, int(self.yes_ask) - int(self.yes_bid)))
        if self.no_bid is not None and self.no_ask is not None:
            spreads.append(max(0, int(self.no_ask) - int(self.no_bid)))
        return min(spreads) if spreads else None

    def side_entry_cents(self, side: str) -> int | None:
        side = str(side).upper()
        if side == "LONG":
            return self.yes_ask if self.yes_ask is not None else self.last_price
        if side == "SHORT":
            return self.no_ask if self.no_ask is not None else (100 - self.last_price if self.last_price is not None else None)
        return None

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(time.time() + float(self.server_offset_seconds or 0.0), tz=timezone.utc)

    def seconds_left(self) -> int:
        now_dt = self.now_utc()
        if self.close_time:
            return max(0, int((self.close_time - now_dt).total_seconds()))
        now = int(now_dt.timestamp())
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
        self._last_candidates: list[str] = []

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
                server_offset_seconds=self.clock.server_offset_seconds,
                yes_bid=self.clock.yes_bid,
                yes_ask=self.clock.yes_ask,
                no_bid=self.clock.no_bid,
                no_ask=self.clock.no_ask,
                last_price=self.clock.last_price,
                volume=self.clock.volume,
                liquidity=self.clock.liquidity,
            )

    def refresh_async(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def set_target_url(self, value: str) -> None:
        with self._lock:
            self.target_url = value.strip() or CATEGORY_URL
            self.target_ticker = self._extract_ticker(self.target_url)
            self.clock.last_error = "Target changed; refreshing Kalshi BTC15..."
        self.refresh_async()

    def _refresh(self) -> None:
        try:
            server_offset = self._server_time_offset()
            server_now = datetime.fromtimestamp(time.time() + server_offset, tz=timezone.utc)

            exact = self._get_exact_market(self.target_ticker) if self.target_ticker else None
            if exact and self._is_current_btc15_market(exact, server_now):
                self._set_market(exact, "KALSHI_EXACT", server_offset, "Exact pasted ticker is active")
                return

            # Category page often contains the exact live ticker the phone is showing.
            cat_ticker = self._find_category_page_ticker(server_now)
            if cat_ticker:
                exact2 = self._get_exact_market(cat_ticker)
                if exact2:
                    self._set_market(exact2, "KALSHI_CATEGORY", server_offset, "Ticker parsed from Kalshi BTC 15m category page")
                    return
                close_dt = self._parse_ticker_close_time(cat_ticker)
                if close_dt:
                    self._set_clock(KalshiMarketClock(
                        ticker=cat_ticker,
                        title="BTC15 category ticker",
                        close_time=close_dt,
                        source="CATEGORY_TICKER",
                        last_error="Parsed active ticker from category page but exact API lookup failed",
                        updated_at=time.time(),
                        candidate_count=len(self._last_candidates),
                        server_offset_seconds=server_offset,
                    ))
                    return

            market = self._find_active_btc15_market(server_now)
            if market:
                self._set_market(market, "KALSHI_ACTIVE", server_offset, "Nearest open KXBTC15M from public markets API")
                return

            # Final fallback: server-time estimate, not local PC clock estimate.
            close_ts = ((int(server_now.timestamp()) // 900) + 1) * 900
            self._set_clock(KalshiMarketClock(
                ticker="KXBTC15M_ESTIMATE",
                title="BTC 15m server-time estimate",
                close_time=datetime.fromtimestamp(close_ts, tz=timezone.utc),
                source="SERVER_ESTIMATE",
                last_error="Could not find exact Kalshi market; using Kalshi/server-time quarter-hour estimate",
                updated_at=time.time(),
                candidate_count=0,
                server_offset_seconds=server_offset,
            ))
        except Exception as exc:
            self._set_error(str(exc)[:220])
        finally:
            self._refreshing = False

    def _set_clock(self, clock: KalshiMarketClock) -> None:
        with self._lock:
            self.clock = clock

    def _set_market(self, market: dict, source: str, server_offset: float, note: str) -> None:
        close_time = self._parse_time(market.get("close_time") or market.get("latest_expiration_time")) or self._parse_ticker_close_time(str(market.get("ticker", "")))
        title = market.get("title") or market.get("subtitle") or market.get("yes_sub_title") or "BTC15"
        self._set_clock(KalshiMarketClock(
            ticker=str(market.get("ticker", "")),
            title=str(title),
            close_time=close_time,
            source=source if close_time else "SERVER_ESTIMATE",
            last_error=note if close_time else "Market had no close_time; using fallback",
            updated_at=time.time(),
            candidate_count=int(market.get("_candidate_count", 0) or len(self._last_candidates)),
            server_offset_seconds=server_offset,
            yes_bid=self._int_or_none(market.get("yes_bid")),
            yes_ask=self._int_or_none(market.get("yes_ask")),
            no_bid=self._int_or_none(market.get("no_bid")),
            no_ask=self._int_or_none(market.get("no_ask")),
            last_price=self._int_or_none(market.get("last_price")),
            volume=self._int_or_none(market.get("volume")),
            liquidity=self._int_or_none(market.get("liquidity")),
        ))

    def _set_error(self, message: str) -> None:
        with self._lock:
            self.clock.source = "ESTIMATED"
            self.clock.last_error = message
            self.clock.updated_at = time.time()

    def _server_time_offset(self) -> float:
        # The Date header avoids bad Windows clock drift / timezone weirdness.
        for url in (f"{self.BASE}/markets?limit=1", "https://kalshi.com/category/crypto/btc?frequency=fifteen_min"):
            try:
                req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.9"})
                with urlopen(req, timeout=5) as resp:
                    date_header = resp.headers.get("Date")
                    if date_header:
                        server_dt = parsedate_to_datetime(date_header).astimezone(timezone.utc)
                        return server_dt.timestamp() - time.time()
            except Exception:
                continue
        return 0.0

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

    def _is_current_btc15_market(self, market: dict, now_dt: datetime) -> bool:
        close_dt = self._parse_time(market.get("close_time") or market.get("latest_expiration_time")) or self._parse_ticker_close_time(str(market.get("ticker", "")))
        status = str(market.get("status", "")).lower()
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
            req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.9"})
            with urlopen(req, timeout=7) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            market = data.get("market") or data
            if isinstance(market, dict) and market.get("ticker"):
                return market
        except Exception:
            pass
        return None

    def _int_or_none(self, value) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(round(float(value)))
        except Exception:
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
        req = Request(url, headers={"User-Agent": "QuantTerminal/0.3.9"})
        with urlopen(req, timeout=7) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _find_category_page_ticker(self, server_now: datetime) -> Optional[str]:
        try:
            req = Request(CATEGORY_URL, headers={"User-Agent": "QuantTerminal/0.3.9"})
            with urlopen(req, timeout=7) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            tickers = sorted(set(TICKER_RE.findall(html)))
            self._last_candidates = tickers[-20:]
            future: list[tuple[int, str]] = []
            for t in tickers:
                close_dt = self._parse_ticker_close_time(t)
                if not close_dt:
                    continue
                secs = int((close_dt - server_now).total_seconds())
                if 0 < secs <= 16 * 60:
                    future.append((secs, t))
            if future:
                future.sort(key=lambda x: x[0])
                return future[0][1]
        except Exception:
            return None
        return None

    def _find_active_btc15_market(self, server_now: datetime) -> Optional[dict]:
        now = int(server_now.timestamp())
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

        candidates: list[tuple[int, datetime, dict]] = []
        self._last_candidates = []
        for m in unique.values():
            hay = " ".join(str(m.get(k, "")) for k in (
                "ticker", "event_ticker", "series_ticker", "title", "subtitle", "yes_sub_title", "no_sub_title"
            )).upper()
            if "KXBTC15M" not in hay:
                continue
            close_dt = self._parse_time(m.get("close_time") or m.get("latest_expiration_time")) or self._parse_ticker_close_time(str(m.get("ticker", "")))
            if not close_dt or close_dt <= server_now:
                continue
            seconds = int((close_dt - server_now).total_seconds())
            self._last_candidates.append(f"{m.get('ticker')} {seconds}s")
            score = 10000 - seconds if 0 < seconds <= 16 * 60 else -seconds
            candidates.append((score, close_dt, m))

        if not candidates:
            return None
        candidates.sort(key=lambda x: (-x[0], x[1]))
        chosen = candidates[0][2]
        chosen["_candidate_count"] = len(candidates)
        return chosen
