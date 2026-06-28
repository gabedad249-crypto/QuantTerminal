from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget
from app.strategy.fvg_engine import Candle, FVG, FVGEngine


class ChartWidget(QWidget):
    """Early custom chart with a TradingView-style position planner overlay.

    v0.1.3 still uses a Qt canvas. It is not the final chart engine, but it now
    supports an editable entry/stop/target plan and a saner zoom model.
    """

    planChanged = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 420)
        self.candles: list[Candle] = []
        self.fvgs: list[FVG] = []
        self.visible_bars = 90  # lower = zoomed in, higher = zoomed out
        self.offset = 0
        self.engine = FVGEngine()
        self.last_mouse = None
        self.drag_line: str | None = None
        self.hover_price: float | None = None
        self.trade_plan = {
            "side": "LONG",
            "entry": None,
            "stop": None,
            "target": None,
            "rr": 2.0,
        }
        self.setMouseTracking(True)
        self.setAutoFillBackground(False)

    def set_candles(self, candles: list[Candle]) -> None:
        self.candles = candles[-600:]
        self.fvgs = self.engine.detect(self.candles)
        if self.candles and self.trade_plan["entry"] is None:
            self.create_default_plan(self.candles[-1].close, emit=False)
        self.update()

    def create_default_plan(self, price: float, side: str | None = None, rr: float | None = None, emit: bool = True) -> None:
        side = side or self.trade_plan.get("side", "LONG")
        rr = rr if rr is not None else float(self.trade_plan.get("rr", 2.0) or 2.0)
        risk = max(price * 0.001, 10.0)  # default 0.10% or $10
        if side == "LONG":
            stop = price - risk
            target = price + risk * rr
        else:
            stop = price + risk
            target = price - risk * rr
        self.set_plan(side, price, stop, target, emit=emit)

    def set_plan(self, side: str, entry: float, stop: float, target: float, emit: bool = True) -> None:
        self.trade_plan = {
            "side": side,
            "entry": float(entry),
            "stop": float(stop),
            "target": float(target),
            "rr": self._calc_rr(side, float(entry), float(stop), float(target)),
        }
        if emit:
            self.planChanged.emit(dict(self.trade_plan))
        self.update()

    def _calc_rr(self, side: str, entry: float, stop: float, target: float) -> float:
        if side == "LONG":
            risk = max(entry - stop, 0.0001)
            reward = target - entry
        else:
            risk = max(stop - entry, 0.0001)
            reward = entry - target
        return max(0.0, reward / risk)

    def zoom_in(self) -> None:
        self.visible_bars = max(12, int(self.visible_bars * 0.78))
        self.update()

    def zoom_out(self) -> None:
        self.visible_bars = min(240, int(self.visible_bars * 1.28))
        self.update()

    def reset_view(self) -> None:
        self.visible_bars = 90
        self.offset = 0
        self.update()

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event):
        pos = event.position()
        self.last_mouse = pos
        self.drag_line = self._hit_test_plan_line(pos.y())
        if self.drag_line:
            event.accept()
            return

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.drag_line:
            price = self._price_from_y(pos.y())
            if price is not None:
                plan = dict(self.trade_plan)
                plan[self.drag_line] = price
                side = str(plan.get("side", "LONG"))
                entry = float(plan.get("entry") or price)
                stop = float(plan.get("stop") or price)
                target = float(plan.get("target") or price)
                # Keep target on the correct side if the user drags too far.
                if side == "LONG":
                    if stop >= entry:
                        stop = entry - max(entry * 0.0005, 5.0)
                    if target <= entry:
                        target = entry + max(entry - stop, 5.0) * 2
                else:
                    if stop <= entry:
                        stop = entry + max(entry * 0.0005, 5.0)
                    if target >= entry:
                        target = entry - max(stop - entry, 5.0) * 2
                self.set_plan(side, entry, stop, target)
            event.accept()
            return

        if self.last_mouse and event.buttons() & Qt.LeftButton:
            dx = pos.x() - self.last_mouse.x()
            # pan by candles; drag right to look backward
            self.offset -= int(dx / max(4, self._bar_step()))
            if self.candles:
                max_offset = max(0, len(self.candles) - min(len(self.candles), self.visible_bars))
                self.offset = max(0, min(max_offset, self.offset))
            self.last_mouse = pos
            self.update()
        else:
            self.hover_price = self._price_from_y(pos.y())
            self.update()

    def mouseReleaseEvent(self, event):
        self.last_mouse = None
        self.drag_line = None

    def _visible(self):
        if not self.candles:
            return [], 0, 0
        visible_count = max(5, min(len(self.candles), self.visible_bars))
        end = len(self.candles) - self.offset
        end = max(visible_count, min(len(self.candles), end))
        start = max(0, end - visible_count)
        return self.candles[start:end], start, end

    def _bar_step(self) -> float:
        candles, _, _ = self._visible()
        return self.width() / max(1, len(candles))

    def _price_range(self, candles: list[Candle]):
        hi = max(c.high for c in candles)
        lo = min(c.low for c in candles)
        # include trade plan so lines are always visible
        for key in ("entry", "stop", "target"):
            val = self.trade_plan.get(key)
            if isinstance(val, (int, float)):
                hi = max(hi, float(val))
                lo = min(lo, float(val))
        if hi == lo:
            hi += 1; lo -= 1
        pad = max((hi - lo) * 0.16, 2.0)
        return hi + pad, lo - pad

    def _ymap_for(self, hi: float, lo: float, chart_h: int):
        def ymap(price: float) -> float:
            return 10 + (hi - price) / (hi - lo) * (chart_h - 20)
        return ymap

    def _current_ymap(self):
        candles, _, _ = self._visible()
        if not candles:
            return None
        chart_h = max(1, self.height() - 28)
        hi, lo = self._price_range(candles)
        return self._ymap_for(hi, lo, chart_h), hi, lo, chart_h

    def _price_from_y(self, y: float) -> float | None:
        m = self._current_ymap()
        if not m:
            return None
        _, hi, lo, chart_h = m
        y = max(10, min(chart_h - 10, y))
        return hi - ((y - 10) / max(1, chart_h - 20)) * (hi - lo)

    def _hit_test_plan_line(self, mouse_y: float) -> str | None:
        m = self._current_ymap()
        if not m:
            return None
        ymap, _, _, _ = m
        for key in ("target", "entry", "stop"):
            val = self.trade_plan.get(key)
            if isinstance(val, (int, float)) and abs(ymap(float(val)) - mouse_y) <= 9:
                return key
        return None

    def _find_swings(self, candles: list[Candle], strength: int = 2):
        swings = []
        if len(candles) < strength * 2 + 1:
            return swings
        for i in range(strength, len(candles) - strength):
            c = candles[i]
            left = candles[i-strength:i]
            right = candles[i+1:i+strength+1]
            if all(c.high > x.high for x in left + right):
                swings.append((i, c.high, "H"))
            if all(c.low < x.low for x in left + right):
                swings.append((i, c.low, "L"))
        return swings[-12:]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        p.fillRect(rect, QColor("#0d1117"))
        w = max(1, rect.width())
        h = max(1, rect.height() - 28)

        # grid
        p.setPen(QPen(QColor("#1d2633"), 1))
        for y in range(38, rect.height(), 42):
            p.drawLine(0, y, w, y)
        for x in range(80, w, 120):
            p.drawLine(x, 0, x, h)

        candles, global_start, global_end = self._visible()
        if not candles:
            p.setPen(QColor("#8f9bad"))
            p.setFont(QFont("Segoe UI", 14))
            p.drawText(rect, Qt.AlignCenter, "Waiting for live BTC candles...")
            return

        hi, lo = self._price_range(candles)
        ymap = self._ymap_for(hi, lo, h)
        step = w / max(1, len(candles))
        candle_w = max(2, min(11, step * 0.52))

        def xmap(i: int) -> float:
            return i * step + step * 0.5

        # visible high/low markers
        high_c = max(candles, key=lambda c: c.high)
        low_c = min(candles, key=lambda c: c.low)
        for price, label, color in [(high_c.high, "Range High", "#f8c14a"), (low_c.low, "Range Low", "#60a5fa")]:
            y = int(ymap(price))
            p.setPen(QPen(QColor(color), 1, Qt.DashLine))
            p.drawLine(0, y, w, y)
            p.setPen(QColor(color))
            p.drawText(8, y - 4, f"{label} {price:,.2f}")

        # FVG boxes, compact and anchored
        for fvg in self.fvgs[-20:]:
            local_idx = None
            for i, c in enumerate(candles):
                if c.ts >= fvg.start_ts:
                    local_idx = i
                    break
            if local_idx is None:
                continue
            x1 = max(0, local_idx * step)
            x2 = min(w, x1 + step * min(12, len(candles) - local_idx))
            y1, y2 = ymap(fvg.top), ymap(fvg.bottom)
            color = QColor(31, 184, 113, 34) if fvg.direction == "BULLISH" else QColor(239, 68, 68, 34)
            border = QColor("#1fb871") if fvg.direction == "BULLISH" else QColor("#ef4444")
            p.fillRect(int(x1), int(min(y1,y2)), int(max(3, x2-x1)), int(max(3, abs(y2-y1))), color)
            p.setPen(QPen(border, 1))
            p.drawRect(int(x1), int(min(y1,y2)), int(max(3, x2-x1)), int(max(3, abs(y2-y1))))

        # position planner risk/reward box behind candles
        self._draw_trade_plan_box(p, w, h, ymap)

        # candles
        for i, c in enumerate(candles):
            x = xmap(i)
            up = c.close >= c.open
            col = QColor("#26a269") if up else QColor("#d84a5f")
            p.setPen(QPen(col, 1))
            p.drawLine(QPointF(x, ymap(c.high)), QPointF(x, ymap(c.low)))
            body_top = ymap(max(c.open,c.close))
            body_bot = ymap(min(c.open,c.close))
            p.fillRect(int(x-candle_w/2), int(body_top), int(candle_w), max(2, int(body_bot-body_top)), QBrush(col))

        # swing labels
        p.setFont(QFont("Segoe UI", 8))
        for i, price, typ in self._find_swings(candles):
            x = int(xmap(i)); y = int(ymap(price))
            if typ == "H":
                p.setPen(QColor("#f8c14a")); p.drawText(x - 8, y - 8, "H")
            else:
                p.setPen(QColor("#60a5fa")); p.drawText(x - 8, y + 15, "L")

        # hover/crosshair price
        if self.hover_price:
            y = int(ymap(self.hover_price))
            p.setPen(QPen(QColor("#445166"), 1, Qt.DotLine))
            p.drawLine(0, y, w, y)

        # live price line
        last = candles[-1]
        y = ymap(last.close)
        p.setPen(QPen(QColor("#9cc9ff"), 1))
        p.drawLine(0, int(y), w, int(y))
        p.fillRect(w-112, int(y)-10, 110, 20, QColor("#172033"))
        p.setPen(QColor("#d7dde8"))
        p.drawText(w-106, int(y)+5, f"{last.close:,.2f}")

        p.setPen(QColor("#d7dde8"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(8, 18, f"BTC-USD Coinbase | bars {len(candles)}/{len(self.candles)} | FVGs {len(self.fvgs)} | Visible {self.visible_bars}")

    def _draw_trade_plan_box(self, p: QPainter, w: int, h: int, ymap) -> None:
        plan = self.trade_plan
        if not all(isinstance(plan.get(k), (int, float)) for k in ("entry", "stop", "target")):
            return
        side = str(plan.get("side", "LONG"))
        entry = float(plan["entry"]); stop = float(plan["stop"]); target = float(plan["target"])
        ye, ys, yt = ymap(entry), ymap(stop), ymap(target)
        x1 = int(w * 0.18); x2 = int(w * 0.88)
        # reward and risk zones
        reward_col = QColor(31, 184, 113, 35) if side == "LONG" else QColor(239, 68, 68, 35)
        risk_col = QColor(239, 68, 68, 35) if side == "LONG" else QColor(31, 184, 113, 35)
        p.fillRect(x1, int(min(yt, ye)), x2-x1, int(max(4, abs(ye-yt))), reward_col)
        p.fillRect(x1, int(min(ys, ye)), x2-x1, int(max(4, abs(ye-ys))), risk_col)
        # lines
        for key, y, color, label in [
            ("target", yt, "#1fb871", "TARGET"),
            ("entry", ye, "#d7dde8", "ENTRY"),
            ("stop", ys, "#ef4444", "STOP"),
        ]:
            p.setPen(QPen(QColor(color), 2 if self.drag_line == key else 1))
            p.drawLine(x1, int(y), x2, int(y))
            p.fillRect(x2 - 148, int(y) - 11, 145, 22, QColor("#111827"))
            p.setPen(QColor(color))
            p.drawText(x2 - 142, int(y) + 5, f"{label} {self.trade_plan[key]:,.2f}")
        rr = self._calc_rr(side, entry, stop, target)
        p.setPen(QColor("#f3f6fb"))
        p.setFont(QFont("Segoe UI", 9, QFont.Bold))
        p.drawText(x1 + 8, int(min(yt, ys, ye)) - 8, f"{side} PLAN  RR {rr:.2f}:1  | drag entry/stop/target lines")
