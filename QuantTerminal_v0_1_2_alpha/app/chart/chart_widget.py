from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget
from app.strategy.fvg_engine import Candle, FVG, FVGEngine

class ChartWidget(QWidget):
    """Early custom chart.

    This is still a lightweight canvas, not the final pro chart engine.
    v0.1.2 focuses on less flashing, saner zoom, shorter FVG boxes, and structure labels.
    """
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(720, 420)
        self.candles: list[Candle] = []
        self.fvgs: list[FVG] = []
        self.zoom = 1.0
        self.offset = 0
        self.engine = FVGEngine()
        self.last_mouse = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def set_candles(self, candles: list[Candle]) -> None:
        self.candles = candles[-500:]
        self.fvgs = self.engine.detect(self.candles)
        self.update()

    def zoom_in(self) -> None:
        self.zoom = max(0.45, min(5.0, self.zoom * 1.22))
        self.update()

    def zoom_out(self) -> None:
        self.zoom = max(0.45, min(5.0, self.zoom / 1.22))
        self.update()

    def reset_view(self) -> None:
        self.zoom = 1.0
        self.offset = 0
        self.update()

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def mousePressEvent(self, event):
        self.last_mouse = event.position()

    def mouseMoveEvent(self, event):
        if self.last_mouse and event.buttons() & Qt.LeftButton:
            dx = event.position().x() - self.last_mouse.x()
            self.offset -= int(dx / 9)
            if self.candles:
                self.offset = max(0, min(max(0, len(self.candles) - 15), self.offset))
            self.last_mouse = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.last_mouse = None

    def _visible(self):
        if not self.candles:
            return [], 0, 0
        visible_count = max(18, min(len(self.candles), int(95 / self.zoom)))
        end = len(self.candles) - self.offset
        end = max(visible_count, min(len(self.candles), end))
        start = max(0, end - visible_count)
        return self.candles[start:end], start, end

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
        return swings[-10:]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        bg = QColor("#0f141c")
        p.fillRect(rect, bg)
        w = max(1, rect.width())
        h = max(1, rect.height() - 28)

        # grid
        p.setPen(QPen(QColor("#202a36"), 1))
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

        hi = max(c.high for c in candles)
        lo = min(c.low for c in candles)
        if hi == lo:
            hi += 1; lo -= 1
        pad = max((hi - lo) * 0.12, 2.0)
        hi += pad; lo -= pad
        step = w / max(1, len(candles))
        candle_w = max(2, min(14, step * 0.58))

        def ymap(price: float) -> float:
            return 10 + (hi - price) / (hi - lo) * (h - 20)

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

        # FVG boxes, shortened so they don't dominate the chart
        for fvg in self.fvgs[-20:]:
            local_idx = None
            for i, c in enumerate(candles):
                if c.ts >= fvg.start_ts:
                    local_idx = i
                    break
            if local_idx is None:
                continue
            x1 = max(0, local_idx * step)
            x2 = min(w, x1 + step * 18)
            y1, y2 = ymap(fvg.top), ymap(fvg.bottom)
            color = QColor(31, 184, 113, 42) if fvg.direction == "BULLISH" else QColor(239, 68, 68, 42)
            border = QColor("#1fb871") if fvg.direction == "BULLISH" else QColor("#ef4444")
            p.fillRect(int(x1), int(min(y1,y2)), int(max(3, x2-x1)), int(max(3, abs(y2-y1))), color)
            p.setPen(QPen(border, 1))
            p.drawRect(int(x1), int(min(y1,y2)), int(max(3, x2-x1)), int(max(3, abs(y2-y1))))

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
            x = int(xmap(i))
            y = int(ymap(price))
            if typ == "H":
                p.setPen(QColor("#f8c14a"))
                p.drawText(x - 8, y - 8, "H")
            else:
                p.setPen(QColor("#60a5fa"))
                p.drawText(x - 8, y + 15, "L")

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
        p.drawText(8, 18, f"BTC-USD Coinbase | {len(self.candles)} candles | Active FVGs {len(self.fvgs)} | Zoom {self.zoom:.2f}x")
