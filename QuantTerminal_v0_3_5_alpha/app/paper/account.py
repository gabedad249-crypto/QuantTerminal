from dataclasses import dataclass, field
from typing import List, Optional

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

@dataclass
class PaperAccount:
    balance: float = 100000.0
    closed_pnl: float = 0.0
    trades: List[PaperTrade] = field(default_factory=list)

    @property
    def open_trade(self) -> Optional[PaperTrade]:
        return next((t for t in self.trades if t.status == "OPEN"), None)

    def open_position(self, side: str, entry: float, stop: float, target: float, size_usd: float, reason: str) -> PaperTrade:
        if self.open_trade:
            raise RuntimeError("Paper trade already open")
        trade = PaperTrade(side=side, entry=entry, stop=stop, target=target, size_usd=size_usd, reason=reason, open_price=entry)
        self.trades.append(trade)
        return trade

    def update(self, price: float) -> None:
        trade = self.open_trade
        if not trade:
            return
        if trade.side == "LONG":
            unrealized = (price - trade.entry) / trade.entry * trade.size_usd
            hit_stop = price <= trade.stop
            hit_target = price >= trade.target
        else:
            unrealized = (trade.entry - price) / trade.entry * trade.size_usd
            hit_stop = price >= trade.stop
            hit_target = price <= trade.target
        trade.pnl = unrealized
        if hit_stop or hit_target:
            trade.status = "CLOSED"
            trade.exit_price = price
            self.closed_pnl += trade.pnl
            self.balance += trade.pnl

    def stats(self) -> dict:
        closed = [t for t in self.trades if t.status == "CLOSED"]
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        return {
            "balance": self.balance,
            "closed_pnl": self.closed_pnl,
            "open_pnl": self.open_trade.pnl if self.open_trade else 0.0,
            "trades": len(closed),
            "win_rate": (len(wins) / len(closed) * 100) if closed else 0.0,
            "profit_factor": (sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses))) if losses else 0.0,
        }
