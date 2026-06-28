from PySide6.QtCore import QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QPushButton, QListWidget, QTextEdit
)
from app.chart.chart_widget import ChartWidget
from app.data.coinbase import CoinbaseFeed
from app.data.candles import CandleBuilder, seconds_until_next_15m
from app.paper.account import PaperAccount
from app.version import APP_NAME, VERSION

class PriceBus(QObject):
    price = Signal(float)

class MainWindow(QMainWindow):
    def __init__(self, settings: dict, logger) -> None:
        super().__init__()
        self.settings = settings
        self.logger = logger
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1450, 850)

        self.bus = PriceBus()
        self.bus.price.connect(self.on_price)
        self.candles = CandleBuilder(60)
        self.account = PaperAccount(settings.get("starting_balance", 100000.0))
        self.feed = CoinbaseFeed(lambda p: self.bus.price.emit(p), settings.get("symbol", "BTC-USD"))

        self.price_label = QLabel("Price: --")
        self.price_label.setObjectName("Title")
        self.timer_label = QLabel("15m: --:--")
        self.timer_label.setObjectName("Title")
        self.feed_label = QLabel("● CONNECTING")
        self.feed_label.setObjectName("Muted")
        self.chart = ChartWidget()
        self.ai_box = QTextEdit()
        self.ai_box.setReadOnly(True)
        self.ai_box.setText("AI Engine\n\nWaiting for live candles...\n\nFVG method stays core. Paper trading is ON.")
        self.stats_label = QLabel()
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        self._build_ui()
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_timer)
        self.clock.start(250)
        self.update_stats()
        self.feed.start()
        self.logger.info("Quant Terminal started")

    def _panel(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        label = QLabel(title)
        label.setObjectName("Title")
        layout.addWidget(label)
        return frame

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top = QFrame(); top.setObjectName("Panel")
        top_l = QHBoxLayout(top)
        title = QLabel("BTC/USD • Coinbase")
        title.setObjectName("Title")
        top_l.addWidget(title)
        top_l.addStretch()
        top_l.addWidget(self.price_label)
        top_l.addSpacing(20)
        top_l.addWidget(self.timer_label)
        top_l.addSpacing(20)
        top_l.addWidget(self.feed_label)
        root.addWidget(top)

        mid = QHBoxLayout()
        left = self._panel("Watchlist")
        left.setFixedWidth(190)
        watch = QListWidget()
        watch.addItems(["BTC-USD", "ETH-USD", "Journal", "Backtests", "Settings"])
        left.layout().addWidget(watch)
        mid.addWidget(left)

        chart_panel = self._panel("Live Chart")
        chart_tools = QHBoxLayout()
        zoom_out = QPushButton("−")
        zoom_out.setToolTip("Zoom out / show more candles")
        zoom_out.clicked.connect(self.chart.zoom_out)
        zoom_in = QPushButton("+")
        zoom_in.setToolTip("Zoom in / make candles bigger")
        zoom_in.clicked.connect(self.chart.zoom_in)
        reset_view = QPushButton("Fit")
        reset_view.setToolTip("Reset chart zoom and pan")
        reset_view.clicked.connect(self.chart.reset_view)
        chart_tools.addWidget(QLabel("Chart scale"))
        chart_tools.addWidget(zoom_out)
        chart_tools.addWidget(zoom_in)
        chart_tools.addWidget(reset_view)
        chart_tools.addStretch()
        chart_panel.layout().addLayout(chart_tools)
        chart_panel.layout().addWidget(self.chart)
        mid.addWidget(chart_panel, 1)

        right = self._panel("AI Decision")
        right.setFixedWidth(300)
        right.layout().addWidget(self.ai_box)
        btn = QPushButton("Open Sample Paper Trade")
        btn.clicked.connect(self.open_sample_trade)
        right.layout().addWidget(btn)
        mid.addWidget(right)
        root.addLayout(mid, 1)

        tabs = QTabWidget()
        paper = QWidget(); paper_l = QVBoxLayout(paper); paper_l.addWidget(self.stats_label)
        logs = QWidget(); logs_l = QVBoxLayout(logs); logs_l.addWidget(self.log_box)
        tabs.addTab(paper, "Paper Trading")
        tabs.addTab(logs, "Logs")
        root.addWidget(tabs, 0)
        self.setCentralWidget(central)

    def update_timer(self) -> None:
        s = seconds_until_next_15m()
        self.timer_label.setText(f"15m: {s//60:02d}:{s%60:02d}")
        self.update_stats()

    def on_price(self, price: float) -> None:
        self.feed_label.setText("● LIVE")
        self.feed_label.setObjectName("Green")
        self.price_label.setText(f"Price: ${price:,.2f}")
        candles = self.candles.update_price(price)
        self.account.update(price)
        self.chart.set_candles(candles)
        self.update_ai(price)

    def update_ai(self, price: float) -> None:
        fvg_count = len(self.chart.fvgs)
        last_fvg = self.chart.fvgs[-1].direction if self.chart.fvgs else "None"
        trend = "Building..." if len(self.candles.candles) < 15 else ("Bullish" if self.candles.candles[-1].close > self.candles.candles[-15].close else "Bearish")
        self.ai_box.setText(
            f"Market Bias\n{trend}\n\n"
            f"Active FVGs\n{fvg_count}\n\n"
            f"Latest FVG\n{last_fvg}\n\n"
            f"Strategy\nFVG confirmation\n\n"
            f"Paper Mode\nENABLED\n\n"
            f"Status\nWaiting for valid FVG retrace + confirmation"
        )

    def open_sample_trade(self) -> None:
        if not self.candles.candles:
            return
        price = self.candles.candles[-1].close
        try:
            self.account.open_position("LONG", price, price * 0.999, price * 1.002, 1000.0, "Manual sample paper trade")
            self.log("Opened sample paper LONG")
        except Exception as e:
            self.log(str(e))

    def update_stats(self) -> None:
        s = self.account.stats()
        self.stats_label.setText(
            f"Balance: ${s['balance']:,.2f}    Open P/L: ${s['open_pnl']:,.2f}    "
            f"Closed P/L: ${s['closed_pnl']:,.2f}    Trades: {s['trades']}    "
            f"Win Rate: {s['win_rate']:.1f}%    Profit Factor: {s['profit_factor']:.2f}"
        )

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_box.append(message)

    def closeEvent(self, event) -> None:
        self.feed.stop()
        event.accept()
