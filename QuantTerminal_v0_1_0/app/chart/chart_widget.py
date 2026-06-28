from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QWidget
from app.strategy.fvg_engine import Candle, FVG, FVGEngine

class ChartWidget(QWidget):
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

    def set_candles(self, candles: list[Candle]) -> None:
        self.candles = candles[-250:]
        self.fvgs = self.engine.detect(self.candles)
        self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.zoom = max(0.45, min(3.0, self.zoom + (0.1 if delta > 0 else -0.1)))
        self.update()

    def mousePressEvent(self, event):
        self.last_mouse = event.position()

    def mouseMoveEvent(self, event):
        if self.last_mouse and event.buttons() & Qt.LeftButton:
            dx = event.position().x() - self.last_mouse.x()
            self.offset += int(dx / 10)
            self.last_mouse = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self.last_mouse = None

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        p.fillRect(rect, QColor("#0b1017"))
        p.setPen(QPen(QColor("#1e293b"), 1))
        for y in range(40, rect.height(), 40):
            p.drawLine(0, y, rect.width(), y)
        if not self.candles:
            p.setPen(QColor("#8f9bad"))
            p.setFont(QFont("Segoe UI", 14))
            p.drawText(rect, Qt.AlignCenter, "Waiting for live BTC candles...")
            return

        visible_count = max(30, int(90 / self.zoom))
        candles = self.candles[-visible_count:]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        hi, lo = max(highs), min(lows)
        pad = (hi - lo) * 0.08 or 1
        hi += pad; lo -= pad
        w = rect.width(); h = rect.height() - 30
        candle_w = max(3, w / len(candles) * 0.55)
        step = w / len(candles)

        def ymap(price: float) -> float:
            return 10 + (hi - price) / (hi - lo) * (h - 20)

        # FVG boxes
        for fvg in self.fvgs[-12:]:
            try:
                idx1 = next(i for i,c in enumerate(candles) if c.ts >= fvg.start_ts)
            except StopIteration:
                continue
            x = idx1 * step
            y1, y2 = ymap(fvg.top), ymap(fvg.bottom)
            color = QColor(36, 211, 118, 45) if fvg.direction == "BULLISH" else QColor(255, 92, 122, 45)
            p.fillRect(int(x), int(min(y1,y2)), int(w-x), int(abs(y2-y1) or 2), color)

        # candles
        for i, c in enumerate(candles):
            x = i * step + step * 0.5
            up = c.close >= c.open
            col = QColor("#2bd576") if up else QColor("#ff5c7a")
            p.setPen(QPen(col, 1))
            p.drawLine(QPointF(x, ymap(c.high)), QPointF(x, ymap(c.low)))
            body_top, body_bot = ymap(max(c.open,c.close)), ymap(min(c.open,c.close))
            p.fillRect(int(x-candle_w/2), int(body_top), int(candle_w), max(2, int(body_bot-body_top)), QBrush(col))

        last = candles[-1]
        y = ymap(last.close)
        p.setPen(QPen(QColor("#60a5fa"), 1))
        p.drawLine(0, int(y), w, int(y))
        p.setPen(QColor("#d7dde8"))
        p.drawText(8, 20, f"BTC-USD Coinbase | Last {last.close:,.2f} | Candles {len(self.candles)} | FVGs {len(self.fvgs)}")
