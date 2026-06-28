from PySide6.QtCore import QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QPushButton, QListWidget, QTextEdit, QDoubleSpinBox,
    QComboBox, QFormLayout
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
        self.resize(1500, 880)

        self.latest_price: float | None = None
        self._syncing_plan = False

        self.bus = PriceBus()
        self.bus.price.connect(self.queue_price)
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
        self.chart.planChanged.connect(self.on_chart_plan_changed)
        self.ai_box = QTextEdit(); self.ai_box.setReadOnly(True)
        self.ai_box.setText("AI Engine\n\nWaiting for live candles...\n\nFVG confirmation strategy will plug in here.")
        self.stats_label = QLabel()
        self.open_trade_label = QLabel("No open paper trade")
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)

        self.side_box = QComboBox(); self.side_box.addItems(["LONG", "SHORT"])
        self.size_box = QDoubleSpinBox(); self.size_box.setRange(10, 100000); self.size_box.setValue(1000); self.size_box.setPrefix("$")
        self.stop_box = QDoubleSpinBox(); self.stop_box.setRange(0.01, 10); self.stop_box.setValue(0.10); self.stop_box.setSuffix("% default stop")
        self.rr_box = QDoubleSpinBox(); self.rr_box.setRange(0.5, 10); self.rr_box.setValue(2.0); self.rr_box.setSuffix("R")

        self.entry_price_box = self._price_spin()
        self.stop_price_box = self._price_spin()
        self.target_price_box = self._price_spin()
        self.plan_rr_label = QLabel("RR --")
        self.plan_rr_label.setObjectName("Title")

        self._build_ui()

        self.side_box.currentTextChanged.connect(self.rebuild_plan_from_inputs)
        self.rr_box.valueChanged.connect(self.rebuild_plan_from_inputs)
        self.stop_box.valueChanged.connect(self.rebuild_plan_from_inputs)
        self.entry_price_box.valueChanged.connect(self.on_plan_inputs_changed)
        self.stop_price_box.valueChanged.connect(self.on_plan_inputs_changed)
        self.target_price_box.valueChanged.connect(self.on_plan_inputs_changed)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_timer)
        self.clock.start(250)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.process_latest_price)
        self.tick_timer.start(300)  # modest throttle while the placeholder canvas exists

        self.update_stats()
        self.feed.start()
        self.logger.info("Quant Terminal started")

    def _price_spin(self) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(1, 10000000)
        box.setDecimals(2)
        box.setSingleStep(10)
        box.setPrefix("$")
        return box

    def _panel(self, title: str) -> QFrame:
        frame = QFrame(); frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        label = QLabel(title); label.setObjectName("Title")
        layout.addWidget(label)
        return frame

    def _build_ui(self) -> None:
        central = QWidget(); root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10); root.setSpacing(10)

        top = QFrame(); top.setObjectName("Panel")
        top_l = QHBoxLayout(top)
        title = QLabel("BTC/USD • Coinbase"); title.setObjectName("Title")
        top_l.addWidget(title); top_l.addStretch(); top_l.addWidget(self.price_label)
        top_l.addSpacing(20); top_l.addWidget(self.timer_label); top_l.addSpacing(20); top_l.addWidget(self.feed_label)
        root.addWidget(top)

        mid = QHBoxLayout()
        left = self._panel("Watchlist"); left.setFixedWidth(190)
        watch = QListWidget(); watch.addItems(["BTC-USD", "ETH-USD", "Journal", "Backtests", "Settings"])
        left.layout().addWidget(watch); mid.addWidget(left)

        chart_panel = self._panel("Live Chart")
        chart_tools = QHBoxLayout()
        zoom_out = QPushButton("−"); zoom_out.clicked.connect(self.chart.zoom_out)
        zoom_in = QPushButton("+"); zoom_in.clicked.connect(self.chart.zoom_in)
        reset_view = QPushButton("Fit"); reset_view.clicked.connect(self.chart.reset_view)
        chart_tools.addWidget(QLabel("Zoom")); chart_tools.addWidget(zoom_out); chart_tools.addWidget(zoom_in); chart_tools.addWidget(reset_view)
        chart_tools.addStretch(); chart_tools.addWidget(QLabel("v0.1.3: draggable trade planner; pro chart replacement still coming"))
        chart_panel.layout().addLayout(chart_tools)
        chart_panel.layout().addWidget(self.chart)
        mid.addWidget(chart_panel, 1)

        right = self._panel("AI Decision")
        right.setFixedWidth(370)
        right.layout().addWidget(self.ai_box)

        planner = QFrame(); planner.setObjectName("Panel")
        fl = QFormLayout(planner)
        fl.addRow("Side", self.side_box)
        fl.addRow("Size", self.size_box)
        fl.addRow("Default stop", self.stop_box)
        fl.addRow("Target RR", self.rr_box)
        fl.addRow("Entry", self.entry_price_box)
        fl.addRow("Stop", self.stop_price_box)
        fl.addRow("Target", self.target_price_box)
        fl.addRow("Ratio", self.plan_rr_label)
        use_ai_btn = QPushButton("Suggest Buy-In From Chart")
        use_ai_btn.clicked.connect(self.suggest_plan)
        open_btn = QPushButton("Open Planned Paper Trade")
        open_btn.clicked.connect(self.open_planned_trade)
        fl.addRow(use_ai_btn)
        fl.addRow(open_btn)
        right.layout().addWidget(planner)
        mid.addWidget(right)
        root.addLayout(mid, 1)

        tabs = QTabWidget()
        paper = QWidget(); paper_l = QVBoxLayout(paper)
        paper_l.addWidget(self.stats_label); paper_l.addWidget(self.open_trade_label); paper_l.addStretch()
        logs = QWidget(); logs_l = QVBoxLayout(logs); logs_l.addWidget(self.log_box)
        tabs.addTab(paper, "Paper Trading")
        tabs.addTab(logs, "Logs")
        root.addWidget(tabs, 0)
        self.setCentralWidget(central)

    def queue_price(self, price: float) -> None:
        self.latest_price = price

    def process_latest_price(self) -> None:
        if self.latest_price is None:
            return
        price = self.latest_price
        self.feed_label.setText("● LIVE")
        self.feed_label.setObjectName("Green")
        self.price_label.setText(f"Price: ${price:,.2f}")
        candles = self.candles.update_price(price)
        self.account.update(price)
        self.chart.set_candles(candles)
        if self.entry_price_box.value() <= 1 and candles:
            self.suggest_plan()
        self.update_ai(price)
        self.update_stats()

    def update_timer(self) -> None:
        s = seconds_until_next_15m()
        self.timer_label.setText(f"15m: {s//60:02d}:{s%60:02d}")

    def update_ai(self, price: float) -> None:
        fvg_count = len(self.chart.fvgs)
        last_fvg = self.chart.fvgs[-1].direction if self.chart.fvgs else "None"
        cs = self.candles.candles
        trend = "Building..."
        plan_note = "Waiting for candles"
        if len(cs) >= 15:
            trend = "Bullish" if cs[-1].close > cs[-15].close else "Bearish"
        if cs:
            p = self.chart.trade_plan
            side = p.get("side", "LONG")
            rr = p.get("rr", 0)
            entry = p.get("entry")
            plan_note = f"Suggested {side} buy-in near {entry:,.2f} | RR {rr:.2f}:1" if isinstance(entry, (int, float)) else "No plan yet"
        self.ai_box.setText(
            f"FVG Method Coach\n\n"
            f"Market Bias\n{trend}\n\n"
            f"Active FVGs\n{fvg_count}\n\n"
            f"Latest FVG\n{last_fvg}\n\n"
            f"Buy-In Plan\n{plan_note}\n\n"
            f"How to use\nDrag ENTRY / STOP / TARGET lines on chart, then click Open Planned Paper Trade.\n\n"
            f"Next Feature\nReal chart engine + auto FVG confirmation entries"
        )

    def suggest_plan(self) -> None:
        if not self.candles.candles:
            self.log("No price yet")
            return
        price = self.candles.candles[-1].close
        side = self.side_box.currentText()
        rr = self.rr_box.value()
        self.chart.create_default_plan(price, side=side, rr=rr)

    def on_chart_plan_changed(self, plan: dict) -> None:
        self._syncing_plan = True
        try:
            if plan.get("side") in ["LONG", "SHORT"]:
                self.side_box.setCurrentText(str(plan["side"]))
            for key, box in [("entry", self.entry_price_box), ("stop", self.stop_price_box), ("target", self.target_price_box)]:
                val = plan.get(key)
                if isinstance(val, (int, float)):
                    box.setValue(float(val))
            rr = float(plan.get("rr") or 0)
            self.plan_rr_label.setText(f"RR {rr:.2f}:1")
        finally:
            self._syncing_plan = False

    def on_plan_inputs_changed(self) -> None:
        if self._syncing_plan:
            return
        entry = self.entry_price_box.value()
        stop = self.stop_price_box.value()
        target = self.target_price_box.value()
        if entry > 1 and stop > 1 and target > 1:
            self.chart.set_plan(self.side_box.currentText(), entry, stop, target)

    def rebuild_plan_from_inputs(self) -> None:
        if self._syncing_plan:
            return
        if self.candles.candles:
            self.chart.create_default_plan(self.entry_price_box.value() if self.entry_price_box.value() > 1 else self.candles.candles[-1].close,
                                           side=self.side_box.currentText(), rr=self.rr_box.value())

    def open_planned_trade(self) -> None:
        plan = self.chart.trade_plan
        if not all(isinstance(plan.get(k), (int, float)) for k in ("entry", "stop", "target")):
            self.log("No complete trade plan yet")
            return
        try:
            self.account.open_position(
                str(plan.get("side", "LONG")),
                float(plan["entry"]),
                float(plan["stop"]),
                float(plan["target"]),
                self.size_box.value(),
                f"Planned paper trade RR {float(plan.get('rr', 0)):.2f}:1"
            )
            self.log(f"Opened planned {plan.get('side')} paper trade @ {float(plan['entry']):,.2f} stop {float(plan['stop']):,.2f} target {float(plan['target']):,.2f}")
        except Exception as e:
            self.log(str(e))

    def update_stats(self) -> None:
        s = self.account.stats()
        self.stats_label.setText(
            f"Balance: ${s['balance']:,.2f}    Open P/L: ${s['open_pnl']:,.2f}    "
            f"Closed P/L: ${s['closed_pnl']:,.2f}    Trades: {s['trades']}    "
            f"Win Rate: {s['win_rate']:.1f}%    Profit Factor: {s['profit_factor']:.2f}"
        )
        t = self.account.open_trade
        if t:
            self.open_trade_label.setText(
                f"OPEN {t.side} | Entry {t.entry:,.2f} | Stop {t.stop:,.2f} | Target {t.target:,.2f} | P/L ${t.pnl:,.2f}"
            )
        else:
            self.open_trade_label.setText("No open paper trade")

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_box.append(message)

    def closeEvent(self, event) -> None:
        self.feed.stop()
        event.accept()
