from dataclasses import dataclass, field
from typing import List, Optional
import time


@dataclass
class PaperTrade:
    side: str
    entry: float
    stop: float
    target: float
    size_usd: float
    reason: str
    open_price: float
    status: str = "OPEN"
    exit_price: Optional[float] = None
    pnl: float = 0.0
    exit_reason: str = ""
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    expires_at: Optional[float] = None
    trade_id: int = 0
    setup_meta: dict = field(default_factory=dict)
    mfe: float = 0.0  # max favorable excursion in paper USD
    mae: float = 0.0  # max adverse excursion in paper USD
    manager_notes: list[str] = field(default_factory=list)

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward_per_unit(self) -> float:
        return abs(self.target - self.entry)

    @property
    def rr(self) -> float:
        return self.reward_per_unit / self.risk_per_unit if self.risk_per_unit else 0.0

    def audit_line(self) -> str:
        status = self.status
        exit_price = self.exit_price if self.exit_price is not None else 0.0
        outcome = self.exit_reason or "OPEN"
        return (
            f"#{self.trade_id:04d} {status} {self.side} | entry {self.entry:,.2f} | "
            f"stop {self.stop:,.2f} | target {self.target:,.2f} | RR {self.rr:.2f}:1 | "
            f"exit {exit_price:,.2f} via {outcome} | P/L ${self.pnl:,.2f} | "
            f"MFE ${self.mfe:,.2f} / MAE ${self.mae:,.2f}"
        )

    def direction_label(self) -> str:
        if self.side == "LONG":
            return "LONG / BUY / UP"
        return "SHORT / SELL / DOWN"


@dataclass
class PaperAccount:
    starting_balance: float = 100000.0
    balance: float = 100000.0
    closed_pnl: float = 0.0
    reserved: float = 0.0
    trades: List[PaperTrade] = field(default_factory=list)
    next_trade_id: int = 1

    def __init__(self, starting_balance: float = 100000.0) -> None:
        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)
        self.closed_pnl = 0.0
        self.reserved = 0.0
        self.trades = []
        self.next_trade_id = 1

    @property
    def open_trade(self) -> Optional[PaperTrade]:
        return next((t for t in self.trades if t.status == "OPEN"), None)

    @property
    def buying_power(self) -> float:
        return max(0.0, self.balance)

    @property
    def equity(self) -> float:
        t = self.open_trade
        return self.balance + self.reserved + (t.pnl if t else 0.0)

    def open_position(self, side: str, entry: float, stop: float, target: float, size_usd: float, reason: str, expires_at: Optional[float] = None, setup_meta: Optional[dict] = None) -> PaperTrade:
        side = side.upper().strip()
        if side not in ("LONG", "SHORT"):
            raise ValueError("side must be LONG or SHORT")
        if self.open_trade:
            raise RuntimeError("Paper trade already open")
        size_usd = float(size_usd)
        if size_usd <= 0:
            raise ValueError("paper size must be greater than 0")
        if size_usd > self.balance:
            raise RuntimeError(f"Not enough paper buying power. Need ${size_usd:,.2f}, have ${self.balance:,.2f}")

        trade = PaperTrade(
            side=side,
            entry=float(entry),
            stop=float(stop),
            target=float(target),
            size_usd=size_usd,
            reason=reason,
            open_price=float(entry),
            expires_at=expires_at,
            trade_id=self.next_trade_id,
            setup_meta=dict(setup_meta or {}),
        )
        self.next_trade_id += 1
        self.balance -= size_usd
        self.reserved += size_usd
        self.trades.append(trade)
        return trade

    def _cash_scaled_pnl(self, trade: PaperTrade, price: float) -> float:
        """Return live paper P/L in the user's configured small-dollar terms.

        Older builds used raw spot-style P/L: BTC percent move * buy-in size.
        That made a $20 DOWN play show only pennies while price was moving in
        the right direction. For this paper-training terminal, stop/target are
        the pass/fail chart levels, while cash_stop_loss/cash_payout define the
        simulated payout curve. At target the trade shows +cash_payout; at stop
        it shows -cash_stop_loss, with live P/L moving continuously between them.
        """
        target_cash = float(trade.setup_meta.get("cash_payout", 0.0) or 0.0)
        risk_cash = float(trade.setup_meta.get("cash_stop_loss", 0.0) or 0.0)
        if target_cash <= 0 and risk_cash <= 0:
            # Fallback for old saved trades that do not have cash labels yet.
            if trade.side == "LONG":
                return (price - trade.entry) / max(trade.entry, 0.01) * trade.size_usd
            return (trade.entry - price) / max(trade.entry, 0.01) * trade.size_usd
        target_cash = target_cash if target_cash > 0 else trade.size_usd
        risk_cash = risk_cash if risk_cash > 0 else trade.size_usd

        if trade.side == "LONG":
            if price >= trade.entry:
                progress = (price - trade.entry) / max(trade.target - trade.entry, 0.0001)
                return max(0.0, progress) * target_cash
            progress = (trade.entry - price) / max(trade.entry - trade.stop, 0.0001)
            return -max(0.0, progress) * risk_cash
        else:
            if price <= trade.entry:
                progress = (trade.entry - price) / max(trade.entry - trade.target, 0.0001)
                return max(0.0, progress) * target_cash
            progress = (price - trade.entry) / max(trade.stop - trade.entry, 0.0001)
            return -max(0.0, progress) * risk_cash

    def update(self, price: float, force_close: bool = False, force_reason: str = "") -> None:
        trade = self.open_trade
        if not trade:
            return
        price = float(price)
        now = time.time()
        if trade.side == "LONG":
            raw_hit_stop = price <= trade.stop
            raw_hit_target = price >= trade.target
        else:
            raw_hit_stop = price >= trade.stop
            raw_hit_target = price <= trade.target
        time_expired = bool(trade.expires_at and now >= float(trade.expires_at))

        # Anti-flicker lifecycle guard: a newly opened paper trade gets a short
        # management lock so stale tick/rounding noise cannot open and close it
        # on the same second. BTC15 expiry can still close immediately.
        min_hold = float(trade.setup_meta.get("min_hold_seconds", 0.0) or 0.0)
        tp_sl_live = (now - float(trade.opened_at)) >= max(0.0, min_hold)
        hit_stop = bool(raw_hit_stop and tp_sl_live)
        hit_target = bool(raw_hit_target and tp_sl_live)

        unrealized = self._cash_scaled_pnl(trade, price)
        trade.pnl = unrealized
        trade.mfe = max(float(getattr(trade, "mfe", 0.0)), float(unrealized))
        trade.mae = min(float(getattr(trade, "mae", 0.0)), float(unrealized))
        if force_close or time_expired or hit_stop or hit_target:
            trade.status = "CLOSED"
            trade.exit_price = price
            if force_close:
                trade.exit_reason = force_reason or "FORCE_CLOSE"
            elif time_expired:
                trade.exit_reason = "KALSHI_15M_END"
            else:
                trade.exit_reason = "TARGET" if hit_target else "STOP"
            trade.closed_at = time.time()
            trade.pnl = self._cash_scaled_pnl(trade, price)
            # Clamp exact target/stop closes to the configured cash values. If the
            # tick jumps beyond the line, keep the paper result comparable.
            if trade.exit_reason == "TARGET":
                trade.pnl = float(trade.setup_meta.get("cash_payout", trade.pnl) or trade.pnl)
            elif trade.exit_reason == "STOP":
                trade.pnl = -float(trade.setup_meta.get("cash_stop_loss", abs(trade.pnl)) or abs(trade.pnl))
            trade.mfe = max(float(getattr(trade, "mfe", 0.0)), float(trade.pnl))
            trade.mae = min(float(getattr(trade, "mae", 0.0)), float(trade.pnl))
            self.closed_pnl += trade.pnl
            self.reserved = max(0.0, self.reserved - trade.size_usd)
            self.balance += trade.size_usd + trade.pnl

    def stats(self) -> dict:
        closed = [t for t in self.trades if t.status == "CLOSED"]
        wins = [t for t in closed if t.exit_reason == "TARGET" or t.pnl > 0]
        losses = [t for t in closed if t.exit_reason == "STOP" or t.pnl <= 0]
        gross_wins = sum(t.pnl for t in wins if t.pnl > 0)
        gross_losses = abs(sum(t.pnl for t in losses if t.pnl < 0))
        return {
            "balance": self.balance,
            "reserved": self.reserved,
            "buying_power": self.buying_power,
            "equity": self.equity,
            "closed_pnl": self.closed_pnl,
            "open_pnl": self.open_trade.pnl if self.open_trade else 0.0,
            "trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
            "profit_factor": (gross_wins / gross_losses) if gross_losses else (gross_wins if gross_wins else 0.0),
        }
