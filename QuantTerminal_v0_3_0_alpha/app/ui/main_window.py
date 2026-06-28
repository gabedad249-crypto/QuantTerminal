from PySide6.QtCore import QTimer, Signal, QObject, Qt
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QPushButton, QListWidget, QTextEdit, QDoubleSpinBox,
    QComboBox, QFormLayout
)
from app.chart.chart_widget import ChartWidget


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """Prevents accidental scroll-wheel value changes inside the order panel."""
    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

from app.data.coinbase import CoinbaseFeed
from app.data.candles import CandleBuilder, seconds_until_next_15m
from app.paper.account import PaperAccount
from app.strategy.setup_engine import FVGSetupEngine
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
        self._last_ai_text = ""
        self.last_decision = None

        self.bus = PriceBus()
        self.bus.price.connect(self.queue_price)
        self.candles = CandleBuilder(60)
        self.account = PaperAccount(settings.get("starting_balance", 100000.0))
        self.setup_engine = FVGSetupEngine(min_rr=float(settings.get("minimum_rr", 2.0)))
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
        self.trades_box = QTextEdit(); self.trades_box.setReadOnly(True)

        self.side_box = QComboBox(); self.side_box.addItems(["LONG", "SHORT"])
        self.size_box = NoWheelDoubleSpinBox(); self.size_box.setRange(10, 100000); self.size_box.setValue(1000); self.size_box.setPrefix("$")
        self.stop_box = NoWheelDoubleSpinBox(); self.stop_box.setRange(0.01, 10); self.stop_box.setValue(0.10); self.stop_box.setSuffix("% default stop")
        self.rr_box = NoWheelDoubleSpinBox(); self.rr_box.setRange(0.5, 10); self.rr_box.setValue(2.0); self.rr_box.setSuffix("R")

        self.entry_price_box = self._price_spin()
        self.stop_price_box = self._price_spin()
        self.target_price_box = self._price_spin()
        self.plan_rr_label = QLabel("RR --")
        self.plan_rr_label.setObjectName("Title")

        self._build_ui()
        self.seed_historical_candles()

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
        self.tick_timer.start(250)  # live but throttled enough to keep UI smooth

        self.update_stats()
        self.feed.start()
        self.logger.info("Quant Terminal started")

    def _price_spin(self) -> QDoubleSpinBox:
        box = NoWheelDoubleSpinBox()
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
        chart_tools.addStretch(); chart_tools.addWidget(QLabel("v0.3.0: real FVG checklist • buy-ins only after confirmation"))
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
        paper_l.addWidget(self.stats_label); paper_l.addWidget(self.open_trade_label); paper_l.addWidget(self.trades_box); paper_l.addStretch()
        logs = QWidget(); logs_l = QVBoxLayout(logs); logs_l.addWidget(self.log_box)
        tabs.addTab(paper, "Paper Trading")
        tabs.addTab(logs, "Logs")
        root.addWidget(tabs, 0)
        self.setCentralWidget(central)

    def seed_historical_candles(self) -> None:
        try:
            history = self.feed.fetch_historical_candles(granularity=60, limit=240)
            if history:
                self.candles.seed(history)
                self.chart.set_candles(self.candles.candles)
                self.log(f"Loaded {len(history)} Coinbase 1m historical candles for context")
        except Exception as e:
            self.log(f"Historical candle load failed: {e}")

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
        self.last_decision = self.setup_engine.evaluate(candles)
        self.apply_valid_setup_to_chart()
        self.update_ai(price)
        self.update_stats()

    def update_timer(self) -> None:
        s = seconds_until_next_15m()
        self.timer_label.setText(f"15m: {s//60:02d}:{s%60:02d}")

    def update_ai(self, price: float) -> None:
        cs = self.candles.candles
        d = self.last_decision or self.setup_engine.evaluate(cs)
        self.last_decision = d

        if d.ready and d.plan:
            plan_note = (
                f"VALID {d.plan.side} SETUP\n"
                f"Entry  {d.plan.entry:,.2f}\n"
                f"Stop   {d.plan.stop:,.2f}\n"
                f"Target {d.plan.target:,.2f}\n"
                f"RR     {d.plan.rr:.2f}:1\n"
                f"Reason {d.plan.reason}"
            )
        else:
            plan_note = "No buy-in yet. Waiting for full FVG + retrace + engulfing/rejection confirmation."

        checklist = "\n".join(d.checklist[-8:]) if d.checklist else "Building candle context..."
        reasons = "\n".join("• " + r for r in d.reasons[-6:]) if d.reasons else "• Monitoring"

        ai_text = (
            f"FVG Confirmation Engine\n\n"
            f"Decision\n{('READY ' + d.side) if d.ready else 'WAIT'}\n\n"
            f"Grade / Confidence\n{d.grade} / {d.confidence}%\n\n"
            f"15m Trend\n{d.trend_15m}\n\n"
            f"5m Trend\n{d.trend_5m}\n\n"
            f"FVG Count\n{d.fvg_count}\n\n"
            f"Latest FVG\n{d.latest_fvg}\n\n"
            f"Checklist\n{checklist}\n\n"
            f"Suggested Buy-In\n{plan_note}\n\n"
            f"Why Waiting\n{reasons}\n\n"
            f"Rule\nNo suggested trade unless: trend + impulse + FVG + pullback + engulfing/rejection + RR >= 2."
        )
        if ai_text != self._last_ai_text:
            self._last_ai_text = ai_text
            old = self.ai_box.verticalScrollBar().value()
            self.ai_box.setPlainText(ai_text)
            self.ai_box.verticalScrollBar().setValue(old)

    def apply_valid_setup_to_chart(self) -> None:
        d = self.last_decision
        if not d or not d.ready or not d.plan:
            return
        # Do not overwrite an active manual plan unless the chart has no active plan.
        if self.chart.trade_plan.get("active"):
            return
        self.chart.set_plan(d.plan.side, d.plan.entry, d.plan.stop, d.plan.target, active=True)
        self.log(f"AI suggested {d.plan.side}: entry {d.plan.entry:,.2f}, stop {d.plan.stop:,.2f}, target {d.plan.target:,.2f}, RR {d.plan.rr:.2f}:1")

    def suggest_plan(self) -> None:
        self.last_decision = self.setup_engine.evaluate(self.candles.candles)
        d = self.last_decision
        if not d.ready or not d.plan:
            self.chart.trade_plan["active"] = False
            self.chart._redraw()
            self.log("No buy-in: full FVG method not confirmed yet")
            for reason in d.reasons[-4:]:
                self.log("WAIT: " + reason)
            self.update_ai(self.candles.candles[-1].close if self.candles.candles else 0)
            return
        self.side_box.setCurrentText(d.plan.side)
        self.chart.set_plan(d.plan.side, d.plan.entry, d.plan.stop, d.plan.target)
        self.log(f"Suggested {d.plan.side} FVG confirmation plan: entry {d.plan.entry:,.2f}, stop {d.plan.stop:,.2f}, target {d.plan.target:,.2f}, RR {d.plan.rr:.2f}:1")

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
            self.chart.set_plan(self.side_box.currentText(), entry, stop, target, active=True)

    def rebuild_plan_from_inputs(self) -> None:
        if self._syncing_plan:
            return
        if self.candles.candles and self.chart.trade_plan.get("active"):
            self.chart.create_default_plan(self.entry_price_box.value() if self.entry_price_box.value() > 1 else self.candles.candles[-1].close,
                                           side=self.side_box.currentText(), rr=self.rr_box.value())

    def open_planned_trade(self) -> None:
        plan = self.chart.trade_plan
        if not plan.get("active") or not all(isinstance(plan.get(k), (int, float)) for k in ("entry", "stop", "target")):
            self.log("No active trade plan yet. Click Suggest Buy-In From Chart first.")
            return
        if not self.last_decision or not self.last_decision.ready:
            self.log("Blocked: paper trade requires valid FVG confirmation decision first.")
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
        closed = [x for x in self.account.trades if x.status == "CLOSED"][-8:]
        if closed:
            lines = ["Recent closed paper trades:"]
            for tr in reversed(closed):
                result = "WIN" if tr.pnl > 0 else "LOSS"
                lines.append(f"{result} {tr.side} entry {tr.entry:,.2f} exit {float(tr.exit_price or 0):,.2f} P/L ${tr.pnl:,.2f}")
            self.trades_box.setPlainText("\n".join(lines))
        else:
            self.trades_box.setPlainText("No closed paper trades yet. The account will update automatically after TP/SL is hit.")

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_box.append(message)

    def closeEvent(self, event) -> None:
        self.feed.stop()
        event.accept()
