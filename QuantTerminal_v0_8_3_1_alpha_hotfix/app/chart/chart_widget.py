
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QWheelEvent
import time
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from app.strategy.fvg_engine import Candle, FVG, FVGEngine
from app.strategy.candlestick_patterns import detect_candlestick_patterns


class ChartWidget(QGraphicsView):
    """v0.2.0 chart rewrite.

    This replaces the old raw QWidget painter with a QGraphicsView scene. It is
    still not TradingView-level yet, but it fixes the biggest prototype issues:
    real wheel zoom, drag-pan, no full-window flashing, cleaner candle sizing,
    shorter FVG boxes, HH/LL markers, and a more stable trade planner overlay.
    """

    planChanged = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setMinimumSize(760, 440)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QBrush(QColor("#0b0f14")))

        self.candles: list[Candle] = []
        self.fvgs: list[FVG] = []
        self.engine = FVGEngine()
        self.visible_bars = 80
        self.offset = 0
        self.last_mouse_x: float | None = None
        self.drag_line: str | None = None
        self.hover_scene: QPointF | None = None
        self.dragging_chart = False

        self.trade_plan = {
            "side": "LONG",
            "entry": None,
            "stop": None,
            "target": None,
            "rr": 2.0,
            "active": False,
            "mode": "plan",  # plan = suggested buy-in, trade = actual open paper trade
        }

        # Clean-chart defaults. The strategy can still use every FVG internally,
        # but the screen only draws the most relevant recent gaps so it doesn't
        # turn into a wall of BULL/BEAR labels.
        self.max_gap_boxes = 5
        self.show_filled_gaps = False
        self.show_gap_labels = True
        self.show_swing_labels = False
        self.focus_gap_key: str = ""
        self.clean_mode: bool = True

        self._plot = QRectF(60, 12, 900, 360)
        self._last_mouse_redraw = 0.0
        self._hi = 1.0
        self._lo = 0.0
        self.live_price: float | None = None
        self.live_pnl: float = 0.0
        self.live_trade_status: str = ""
        self.cash_size_usd: float = 0.0
        self.cash_risk_usd: float = 0.0
        self.cash_payout_usd: float = 0.0

    # ---------- public API used by MainWindow ----------
    def set_candles(self, candles: list[Candle]) -> None:
        self.candles = candles[-800:]
        self.fvgs = self.engine.detect(self.candles)
        self._redraw()

    def set_focus_gap_key(self, key: str) -> None:
        if self.focus_gap_key != (key or ""):
            self.focus_gap_key = key or ""
            self._redraw()

    def _fvg_key(self, fvg: FVG) -> str:
        return f"{fvg.direction}:{int(fvg.end_ts)}:{round(fvg.top, 2)}:{round(fvg.bottom, 2)}"

    def set_cash_metrics(self, size_usd: float = 0.0, risk_usd: float = 0.0, payout_usd: float = 0.0) -> None:
        self.cash_size_usd = float(size_usd or 0.0)
        self.cash_risk_usd = float(risk_usd or 0.0)
        self.cash_payout_usd = float(payout_usd or 0.0)
        self._redraw()

    def set_live_price(self, price: float, pnl: float = 0.0, status: str = "") -> None:
        self.live_price = float(price)
        self.live_pnl = float(pnl or 0.0)
        self.live_trade_status = status or ""
        # Current price/P&L changes need fast redraw, but not a chart reset.
        self._redraw()

    def create_default_plan(self, price: float, side: str | None = None, rr: float | None = None, emit: bool = True) -> None:
        side = side or str(self.trade_plan.get("side") or "LONG")
        rr = rr if rr is not None else float(self.trade_plan.get("rr") or 2.0)
        risk = max(price * 0.001, 10.0)
        if side == "LONG":
            stop = price - risk
            target = price + risk * rr
        else:
            stop = price + risk
            target = price - risk * rr
        self.set_plan(side, price, stop, target, emit=emit, active=True)

    def set_plan(self, side: str, entry: float, stop: float, target: float, emit: bool = True, active: bool = True, mode: str = "plan") -> None:
        self.trade_plan = {
            "side": side,
            "entry": float(entry),
            "stop": float(stop),
            "target": float(target),
            "rr": self._calc_rr(side, float(entry), float(stop), float(target)),
            "active": active,
            "mode": mode,
        }
        if emit:
            self.planChanged.emit(dict(self.trade_plan))
        self._redraw()

    def clear_plan(self, emit: bool = True) -> None:
        self.trade_plan = {
            "side": str(self.trade_plan.get("side") or "LONG"),
            "entry": None,
            "stop": None,
            "target": None,
            "rr": float(self.trade_plan.get("rr") or 2.0),
            "active": False,
            "mode": "plan",
        }
        if emit:
            self.planChanged.emit(dict(self.trade_plan))
        self._redraw()

    def zoom_in(self) -> None:
        self.visible_bars = max(18, int(self.visible_bars * 0.82))
        self._clamp_offset()
        self._redraw()

    def zoom_out(self) -> None:
        self.visible_bars = min(260, int(self.visible_bars * 1.22))
        self._clamp_offset()
        self._redraw()

    def reset_view(self) -> None:
        self.visible_bars = 80
        self.offset = 0
        self._redraw()

    # ---------- math/mapping ----------
    def _visible(self):
        if not self.candles:
            return [], 0, 0
        n = max(5, min(len(self.candles), self.visible_bars))
        end = len(self.candles) - self.offset
        end = max(n, min(len(self.candles), end))
        start = max(0, end - n)
        return self.candles[start:end], start, end

    def _clamp_offset(self) -> None:
        if not self.candles:
            self.offset = 0
            return
        max_offset = max(0, len(self.candles) - min(len(self.candles), self.visible_bars))
        self.offset = max(0, min(max_offset, self.offset))

    def _calc_rr(self, side: str, entry: float, stop: float, target: float) -> float:
        if side == "LONG":
            risk = max(entry - stop, 0.0001)
            reward = target - entry
        else:
            risk = max(stop - entry, 0.0001)
            reward = entry - target
        return max(0.0, reward / risk)

    def _price_range(self, candles: list[Candle]) -> tuple[float, float]:
        hi = max(c.high for c in candles)
        lo = min(c.low for c in candles)
        # Keep the candle view readable. Earlier builds included far-away
        # cash-derived stop/target levels in the y-axis range; a $20 buy-in with
        # a $1 target can translate into thousands of BTC-price dollars, making
        # the candle bodies look flat. The chart now scales primarily to candles
        # and only includes plan lines when they are near the visible market.
        candle_range = max(hi - lo, 1.0)
        if self.trade_plan.get("active"):
            center = (hi + lo) / 2.0
            allowed_span = candle_range * 2.5
            for key in ("entry", "stop", "target"):
                val = self.trade_plan.get(key)
                if isinstance(val, (int, float)):
                    v = float(val)
                    if abs(v - center) <= allowed_span:
                        hi = max(hi, v)
                        lo = min(lo, v)
        if hi == lo:
            hi += 1
            lo -= 1
        pad = max((hi - lo) * 0.12, 1.0)
        return hi + pad, lo - pad

    def _x(self, local_index: int, count: int) -> float:
        return self._plot.left() + (local_index + 0.5) * (self._plot.width() / max(1, count))

    def _y(self, price: float) -> float:
        return self._plot.top() + (self._hi - price) / max(0.0001, (self._hi - self._lo)) * self._plot.height()

    def _price_from_scene_y(self, y: float) -> float:
        y = max(self._plot.top(), min(self._plot.bottom(), y))
        return self._hi - ((y - self._plot.top()) / max(1, self._plot.height())) * (self._hi - self._lo)

    def _hit_plan_line(self, scene_y: float) -> str | None:
        for key in ("target", "entry", "stop"):
            val = self.trade_plan.get(key)
            if isinstance(val, (int, float)) and abs(self._y(float(val)) - scene_y) <= 8:
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
        return swings[-18:]

    # ---------- drawing ----------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._redraw()

    def _redraw(self) -> None:
        # One scene clear per app tick is still not final, but QGraphicsView avoids
        # the old full-widget flicker and makes zoom/pan usable.
        self.scene.clear()
        w = max(640, self.viewport().width())
        h = max(360, self.viewport().height())
        self.scene.setSceneRect(0, 0, w, h)
        self._plot = QRectF(62, 16, w - 118, h - 58)

        self._draw_background(w, h)
        candles, global_start, _ = self._visible()
        if not candles:
            self._text(w / 2 - 120, h / 2, "Waiting for live BTC candles...", "#8f9bad", 14)
            return

        self._hi, self._lo = self._price_range(candles)
        self._draw_axes(candles)
        self._draw_fvgs(candles, global_start)
        self._draw_candles(candles)
        self._draw_high_low(candles)
        self._draw_swings(candles)
        self._draw_trade_plan()
        self._draw_live_price()
        self._draw_crosshair()
        # Do not call fitInView/resetTransform here. Zoom is handled by visible_bars;
        # forcing the view every redraw made the chart feel like it snapped back.
        self.setSceneRect(0, 0, w, h)

    def _draw_background(self, w: int, h: int) -> None:
        self.scene.addRect(0, 0, w, h, QPen(Qt.NoPen), QBrush(QColor("#0b0f14")))
        grid_pen = QPen(QColor("#1a2330"), 1)
        for i in range(1, 6):
            y = self._plot.top() + self._plot.height() * i / 6
            self.scene.addLine(self._plot.left(), y, self._plot.right(), y, grid_pen)
        for i in range(1, 8):
            x = self._plot.left() + self._plot.width() * i / 8
            self.scene.addLine(x, self._plot.top(), x, self._plot.bottom(), grid_pen)

    def _draw_axes(self, candles: list[Candle]) -> None:
        axis_pen = QPen(QColor("#243244"), 1)
        self.scene.addRect(self._plot, axis_pen, QBrush(Qt.NoBrush))
        for i in range(6):
            price = self._lo + (self._hi - self._lo) * i / 5
            y = self._y(price)
            self._text(self._plot.right() + 8, y - 8, f"{price:,.0f}", "#7d8999", 9)

    def _draw_candles(self, candles: list[Candle]) -> None:
        count = len(candles)
        step = self._plot.width() / max(1, count)
        body_w = max(3, min(14, step * 0.58))
        for i, c in enumerate(candles):
            x = self._x(i, count)
            up = c.close >= c.open
            color = QColor("#22c55e" if up else "#ef4444")
            pen = QPen(color, 1)
            self.scene.addLine(x, self._y(c.high), x, self._y(c.low), pen)
            y1 = self._y(max(c.open, c.close))
            y2 = self._y(min(c.open, c.close))
            rect_h = max(1.5, y2 - y1)
            self.scene.addRect(x - body_w / 2, y1, body_w, rect_h, pen, QBrush(color))

    def _draw_fvgs(self, candles: list[Candle], global_start: int) -> None:
        count = len(candles)
        step = self._plot.width() / max(1, count)
        visible_start = candles[0].ts
        visible_end = candles[-1].ts
        drawable = []
        for fvg in self.fvgs:
            if not self.show_filled_gaps and fvg.status == "FILLED":
                continue
            # Show only gaps whose creation/active zone intersects the visible candles.
            if fvg.end_ts < visible_start or fvg.start_ts > visible_end:
                continue
            drawable.append(fvg)
        # v0.5.0: focus one GAP at a time. If the strategy has selected a
        # focus FVG, only that GAP is emphasized. Otherwise show only a few
        # recent active/touched gaps so the chart stays readable.
        if self.focus_gap_key:
            focused = [f for f in drawable if self._fvg_key(f) == self.focus_gap_key]
            drawable = focused or drawable[-1:]
        else:
            active_first = [f for f in drawable if f.status != "FILLED"]
            drawable = (active_first or drawable)[-min(self.max_gap_boxes, 3):]

        for fvg in drawable:
            indexes = [i for i, c in enumerate(candles) if fvg.start_ts <= c.ts <= fvg.end_ts]
            if not indexes:
                continue
            start_i = max(0, indexes[0])
            end_i = min(count - 1, start_i + 6)
            x1 = self._x(start_i, count) - step * 0.40
            x2 = self._x(end_i, count) + step * 0.40
            y_top = self._y(fvg.top)
            y_bot = self._y(fvg.bottom)

            is_focus = self.focus_gap_key and self._fvg_key(fvg) == self.focus_gap_key
            fill = QColor("#6b7280")
            fill.setAlpha(18 if fvg.status == "FILLED" else (56 if is_focus else 30))
            border = QColor("#e5e7eb" if is_focus else "#94a3b8")
            if fvg.status == "TOUCHED":
                border = QColor("#f59e0b")
            border.setAlpha(150)
            pen = QPen(border, 2 if is_focus else 1, Qt.DashLine if fvg.status == "FILLED" else Qt.SolidLine)
            self.scene.addRect(QRectF(x1, min(y_top, y_bot), x2 - x1, max(3, abs(y_bot - y_top))), pen, QBrush(fill))

            if self.show_gap_labels:
                # Keep the chart clean: show GAP only, not giant bullish/bearish spam.
                status = ("FOCUS GAP" if is_focus and fvg.status != "FILLED" else ("GAP" if fvg.status != "FILLED" else "FILLED"))
                self._text(x1 + 4, min(y_top, y_bot) + 2, status, "#cbd5e1", 7)

    def _draw_high_low(self, candles: list[Candle]) -> None:
        high_c = max(candles, key=lambda c: c.high)
        low_c = min(candles, key=lambda c: c.low)
        for price, label, color in [(high_c.high, "High", "#f59e0b"), (low_c.low, "Low", "#60a5fa")]:
            y = self._y(price)
            pen = QPen(QColor(color), 1, Qt.DashLine)
            self.scene.addLine(self._plot.left(), y, self._plot.right(), y, pen)
            self._text(self._plot.left() + 8, y - 14, f"{label} {price:,.0f}", color, 8)

    def _draw_swings(self, candles: list[Candle]) -> None:
        if not self.show_swing_labels:
            return
        count = len(candles)
        # Cleaner default: only the most recent major swing points.
        for i, price, kind in self._find_swings(candles)[-8:]:
            x = self._x(i, count)
            y = self._y(price)
            label = "H" if kind == "H" else "L"
            color = "#facc15" if kind == "H" else "#93c5fd"
            self._text(x - 6, y - (18 if kind == "H" else -6), label, color, 8)

    def _draw_trade_plan(self) -> None:
        entry = self.trade_plan.get("entry")
        stop = self.trade_plan.get("stop")
        target = self.trade_plan.get("target")
        if not self.trade_plan.get("active") or not all(isinstance(v, (int, float)) for v in (entry, stop, target)):
            return
        side = str(self.trade_plan.get("side", "LONG"))
        mode = str(self.trade_plan.get("mode") or "plan")
        entry = float(entry); stop = float(stop); target = float(target)

        y_entry_raw = self._y(entry)
        y_stop_raw = self._y(stop)
        y_target_raw = self._y(target)
        y_entry = max(self._plot.top() + 2, min(self._plot.bottom() - 2, y_entry_raw))
        y_stop = max(self._plot.top() + 2, min(self._plot.bottom() - 2, y_stop_raw))
        y_target = max(self._plot.top() + 2, min(self._plot.bottom() - 2, y_target_raw))

        # Transparent risk/reward zones meet at the buy-in line, but are visually
        # capped. A $20 paper buy-in with a $1 payout can translate to a huge BTC
        # price distance; drawing that full distance makes the chart unreadable.
        # The actual stop/target price lines still show the real pass/fail levels.
        green = QColor("#22c55e"); green.setAlpha(22)
        red = QColor("#ef4444"); red.setAlpha(22)

        def capped_zone_y(raw_y: float, entry_y: float) -> float:
            max_zone = max(24.0, self._plot.height() * 0.22)
            delta = max(-max_zone, min(max_zone, raw_y - entry_y))
            return max(self._plot.top() + 2, min(self._plot.bottom() - 2, entry_y + delta))

        zy_target = capped_zone_y(y_target_raw, y_entry)
        zy_stop = capped_zone_y(y_stop_raw, y_entry)
        self.scene.addRect(QRectF(self._plot.left(), min(y_entry, zy_target), self._plot.width(), max(2, abs(zy_target - y_entry))), QPen(Qt.NoPen), QBrush(green))
        self.scene.addRect(QRectF(self._plot.left(), min(y_entry, zy_stop), self._plot.width(), max(2, abs(zy_stop - y_entry))), QPen(Qt.NoPen), QBrush(red))

        def line(key: str, raw_y: float, y: float, price: float, color: str, label: str, cash: str = "") -> None:
            visible = self._plot.top() <= raw_y <= self._plot.bottom()
            pen = QPen(QColor(color), 2.4 if key == self.drag_line else 1.6, Qt.SolidLine if visible else Qt.DashLine)
            self.scene.addLine(self._plot.left(), y, self._plot.right(), y, pen)
            arrow = "" if visible else (" ↑" if raw_y < self._plot.top() else " ↓")
            label_text = f"{label}{arrow} {price:,.2f}"
            if cash:
                label_text += f"  {cash}"
            width = min(220, 16 + len(label_text) * 7)
            self.scene.addRect(self._plot.right() - width - 4, y - 12, width, 24, QPen(QColor(color), 1), QBrush(QColor("#111827")))
            self._text(self._plot.right() - width + 2, y - 9, label_text, color, 8)

        entry_label = "ENTRY" if mode == "trade" else "BUY-IN"
        payout_cash = f"+${self.cash_payout_usd:,.2f}" if self.cash_payout_usd else ""
        risk_cash = f"-${self.cash_risk_usd:,.2f}" if self.cash_risk_usd else ""
        line("target", y_target_raw, y_target, target, "#22c55e", "TARGET", payout_cash)
        line("entry", y_entry_raw, y_entry, entry, "#e5e7eb", entry_label, f"${self.cash_size_usd:,.2f}" if self.cash_size_usd else "")
        line("stop", y_stop_raw, y_stop, stop, "#ef4444", "STOP", risk_cash)

        rr = float(self.trade_plan.get("rr") or 0)
        title = "OPEN PAPER TRADE" if mode == "trade" else "AUTO PLAN"
        self._text(self._plot.left() + 10, self._plot.top() + 10, f"{side} {title} • Ratio {rr:.2f}:1 • green=target red=stop", "#d1d5db", 10)



    def _draw_live_price(self) -> None:
        if not isinstance(self.live_price, (int, float)):
            return
        price = float(self.live_price)
        if price < self._lo or price > self._hi:
            return
        y = self._y(price)
        pen = QPen(QColor("#f8fafc"), 1, Qt.DotLine)
        self.scene.addLine(self._plot.left(), y, self._plot.right(), y, pen)
        label = f"LIVE {price:,.2f}"
        if self.live_trade_status:
            label += f"  {self.live_trade_status} P/L ${self.live_pnl:,.2f}"
        self.scene.addRect(self._plot.left() + 8, y - 12, min(360, 12 + len(label) * 7), 24, QPen(QColor("#64748b"), 1), QBrush(QColor("#111827")))
        self._text(self._plot.left() + 14, y - 9, label, "#e5e7eb", 8)


    def _hover_candle_info(self) -> tuple[Candle | None, int]:
        if not self.hover_scene:
            return None, -1
        candles, global_start, _ = self._visible()
        if not candles or not self._plot.contains(self.hover_scene.x(), self.hover_scene.y()):
            return None, -1
        step = self._plot.width() / max(1, len(candles))
        body_w = max(3, min(14, step * 0.58))
        mx = self.hover_scene.x()
        my = self.hover_scene.y()
        idx = int((mx - self._plot.left()) / max(1, step))
        idx = max(0, min(len(candles) - 1, idx))
        c = candles[idx]
        # Hover card only appears when the mouse is actually on the candle wick or
        # body, not just anywhere inside that candle's time slot. This keeps the
        # chart from popping a card while you are just moving around the panel.
        x = self._x(idx, len(candles))
        y_high = self._y(c.high)
        y_low = self._y(c.low)
        y_body_top = self._y(max(c.open, c.close))
        y_body_bot = self._y(min(c.open, c.close))
        on_body = (abs(mx - x) <= body_w / 2 + 2) and (y_body_top - 2 <= my <= y_body_bot + 2)
        on_wick = (abs(mx - x) <= 4) and (min(y_high, y_low) - 2 <= my <= max(y_high, y_low) + 2)
        if not (on_body or on_wick):
            return None, -1
        # Prefer finished candles. The last visible candle is usually the live
        # forming candle; still allow it only when the mouse is exactly on it.
        return c, global_start + idx

    def _draw_candle_hover_card(self, x: float, y: float) -> None:
        candle, global_idx = self._hover_candle_info()
        if not candle:
            return
        # Use all candles up to the hovered candle so finished candles are read
        # based on their own context, not only the current live candle.
        history = self.candles[:global_idx + 1]
        patterns = detect_candlestick_patterns(history[-8:])
        direction = "UP/GREEN" if candle.close >= candle.open else "DOWN/RED"
        body = abs(candle.close - candle.open)
        rng = max(candle.high - candle.low, 0.000001)
        upper = candle.high - max(candle.open, candle.close)
        lower = min(candle.open, candle.close) - candle.low
        lines = [
            f"Candle #{global_idx + 1}  {direction}",
            f"O {candle.open:,.2f}  H {candle.high:,.2f}",
            f"L {candle.low:,.2f}  C {candle.close:,.2f}",
            f"Body {body:,.2f}  Range {rng:,.2f}",
            f"Upper wick {upper:,.2f}  Lower wick {lower:,.2f}",
        ]
        if patterns:
            lines.append("Pattern read:")
            for p in patterns[:3]:
                lines.append(f"• {p.name} [{p.bias}] {p.strength}/100")
        text_w = 300
        text_h = 18 * len(lines) + 14
        card_x = x + 14
        card_y = y + 14
        if card_x + text_w > self._plot.right():
            card_x = x - text_w - 14
        if card_y + text_h > self._plot.bottom():
            card_y = y - text_h - 14
        card_x = max(self._plot.left() + 4, card_x)
        card_y = max(self._plot.top() + 4, card_y)
        self.scene.addRect(card_x, card_y, text_w, text_h, QPen(QColor("#334155"), 1), QBrush(QColor("#0f172a")))
        for i, line in enumerate(lines):
            color = "#f8fafc" if i == 0 else ("#cbd5e1" if not line.startswith("•") else "#93c5fd")
            self._text(card_x + 10, card_y + 6 + i * 18, line, color, 8)

    def _draw_crosshair(self) -> None:
        if not self.hover_scene:
            return
        x = self.hover_scene.x()
        y = self.hover_scene.y()
        if not self._plot.contains(x, y):
            return
        pen = QPen(QColor("#64748b"), 1, Qt.DashLine)
        self.scene.addLine(x, self._plot.top(), x, self._plot.bottom(), pen)
        self.scene.addLine(self._plot.left(), y, self._plot.right(), y, pen)
        price = self._price_from_scene_y(y)
        self.scene.addRect(self._plot.right() - 88, y - 10, 84, 20, QPen(QColor("#64748b"), 1), QBrush(QColor("#0f172a")))
        self._text(self._plot.right() - 82, y - 7, f"{price:,.2f}", "#cbd5e1", 8)
        self._draw_candle_hover_card(x, y)

    def _text(self, x: float, y: float, text: str, color: str, size: int = 10) -> None:
        item = self.scene.addText(text, QFont("Segoe UI", size))
        item.setDefaultTextColor(QColor(color))
        item.setPos(x, y)

    # ---------- events ----------
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def mousePressEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.LeftButton:
            hit = self._hit_plan_line(scene_pos.y()) if self.candles else None
            if hit:
                self.drag_line = hit
                event.accept()
                return
            self.dragging_chart = True
            self.last_mouse_x = event.position().x()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        self.hover_scene = scene_pos
        if self.drag_line:
            price = self._price_from_scene_y(scene_pos.y())
            plan = dict(self.trade_plan)
            plan[self.drag_line] = price
            side = str(plan.get("side", "LONG"))
            entry = float(plan.get("entry") or price)
            stop = float(plan.get("stop") or price)
            target = float(plan.get("target") or price)
            if side == "LONG":
                if stop >= entry:
                    stop = entry - max(entry * 0.0005, 5)
                if target <= entry:
                    target = entry + max(entry - stop, 5) * 2
            else:
                if stop <= entry:
                    stop = entry + max(entry * 0.0005, 5)
                if target >= entry:
                    target = entry - max(stop - entry, 5) * 2
            self.set_plan(side, entry, stop, target, mode=str(self.trade_plan.get("mode") or "plan"))
            event.accept()
            return
        if self.dragging_chart and self.last_mouse_x is not None and self.candles:
            dx = event.position().x() - self.last_mouse_x
            threshold = max(3, self._plot.width() / max(1, self.visible_bars))
            bars = int(dx / threshold)
            if bars:
                self.offset += bars
                self._clamp_offset()
                self.last_mouse_x = event.position().x()
                self._redraw()
            event.accept()
            return
        # Crosshair-only redraw: throttle so mouse movement does not make the whole
        # chart feel like it is rebuilding.
        now = time.time()
        if now - self._last_mouse_redraw >= 0.06:
            self._last_mouse_redraw = now
            self._redraw()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_line = None
        self.dragging_chart = False
        self.last_mouse_x = None
        super().mouseReleaseEvent(event)
