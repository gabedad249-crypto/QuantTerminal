from PySide6.QtCore import QTimer, Signal, QObject, Qt
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QPushButton, QListWidget, QTextEdit, QDoubleSpinBox,
    QComboBox, QFormLayout, QCheckBox, QLineEdit
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
from app.data.kalshi import KalshiBTC15Timer
from app.paper.account import PaperAccount
from app.strategy.setup_engine import FVGSetupEngine
from app.memory.learning import LearningMemory
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
        self._last_thinking_text = ""
        self._last_ai_update_ts = 0.0
        self._last_chart_update_ts = 0.0
        self._last_decision_signature = ""
        self.last_decision = None
        self._learned_closed_trade_ids = set()
        self._last_auto_plan_sig = ""
        self._last_ready_signal_sig = ""
        self._journal_lines: list[str] = []
        self._auto_opened_signal_sig = ""

        self.bus = PriceBus()
        self.bus.price.connect(self.queue_price)
        self.candles = CandleBuilder(60)
        self.account = PaperAccount(settings.get("starting_balance", 100000.0))
        self.setup_engine = FVGSetupEngine(min_rr=float(settings.get("minimum_rr", 2.0)))
        from pathlib import Path
        self.learning = LearningMemory(Path("memory"))
        self.kalshi_timer = KalshiBTC15Timer(settings.get("kalshi_market_url", "https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/kxbtc15m-26jun280030"))
        self._last_kalshi_refresh = 0.0
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
        self.thinking_box = QTextEdit(); self.thinking_box.setReadOnly(True)
        self.thinking_box.setText("Thinking Panel\n\nWaiting for candle context...")
        self.stats_label = QLabel()
        self.open_trade_label = QLabel("No open paper trade")
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        self.trades_box = QTextEdit(); self.trades_box.setReadOnly(True)
        self.learning_box = QTextEdit(); self.learning_box.setReadOnly(True)
        self.signal_box = QTextEdit(); self.signal_box.setReadOnly(True)
        self.kalshi_debug_box = QTextEdit(); self.kalshi_debug_box.setReadOnly(True)
        self.learning_toggle = QCheckBox("Learning Mode")
        self.learning_toggle.setChecked(True)
        self.learning_toggle.stateChanged.connect(self.on_learning_toggle)
        self.auto_paper_toggle = QCheckBox("Auto-open paper when ready")
        self.auto_paper_toggle.setChecked(False)
        self.kalshi_url_box = QLineEdit(settings.get("kalshi_market_url", "https://kalshi.com/markets/kxbtc15m/bitcoin-price-up-down/kxbtc15m-26jun280030"))
        self.kalshi_url_box.setPlaceholderText("Paste Kalshi BTC15 market URL")

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
        clean_btn = QPushButton("Clean Chart")
        clean_btn.clicked.connect(self.clean_chart_view)
        gap_btn = QPushButton("Toggle Filled Gaps")
        gap_btn.clicked.connect(self.toggle_filled_gaps)
        swing_btn = QPushButton("Toggle H/L")
        swing_btn.clicked.connect(self.toggle_swing_labels)
        chart_tools.addSpacing(12); chart_tools.addWidget(clean_btn); chart_tools.addWidget(gap_btn); chart_tools.addWidget(swing_btn)
        chart_tools.addStretch(); chart_tools.addWidget(QLabel("v0.3.5: exact Kalshi URL • readiness border • auto paper mode"))
        chart_panel.layout().addLayout(chart_tools)
        chart_panel.layout().addWidget(self.chart)
        mid.addWidget(chart_panel, 1)

        right = self._panel("AI / Thinking")
        right.setFixedWidth(400)
        decision_tabs = QTabWidget()
        decision_tabs.addTab(self.ai_box, "Decision")
        decision_tabs.addTab(self.thinking_box, "Thinking Checklist")
        right.layout().addWidget(decision_tabs)

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
        self.open_btn = QPushButton("Open Auto Plan Paper Trade")
        self.open_btn.clicked.connect(self.open_planned_trade)
        fl.addRow(self.open_btn)
        fl.addRow("Auto paper", self.auto_paper_toggle)
        note = QLabel("Auto plan appears only after FVG + pullback + confirmation")
        note.setObjectName("Muted")
        fl.addRow(note)
        right.layout().addWidget(planner)
        mid.addWidget(right)
        root.addLayout(mid, 1)

        tabs = QTabWidget()
        paper = QWidget(); paper_l = QVBoxLayout(paper)
        paper_l.addWidget(self.stats_label); paper_l.addWidget(self.open_trade_label); paper_l.addWidget(self.trades_box); paper_l.addStretch()
        logs = QWidget(); logs_l = QVBoxLayout(logs); logs_l.addWidget(self.log_box)
        learning_tab = QWidget(); learning_l = QVBoxLayout(learning_tab)
        learning_l.addWidget(self.learning_toggle)
        learning_l.addWidget(self.learning_box)
        signal_tab = QWidget(); signal_l = QVBoxLayout(signal_tab); signal_l.addWidget(self.signal_box)
        kalshi_tab = QWidget(); kalshi_l = QVBoxLayout(kalshi_tab)
        apply_kalshi = QPushButton("Sync this Kalshi URL")
        apply_kalshi.clicked.connect(self.apply_kalshi_url)
        kalshi_l.addWidget(QLabel("Kalshi BTC15 market URL"))
        kalshi_l.addWidget(self.kalshi_url_box)
        kalshi_l.addWidget(apply_kalshi)
        kalshi_l.addWidget(self.kalshi_debug_box)
        tabs.addTab(paper, "Paper Trading")
        tabs.addTab(signal_tab, "Signal Journal")
        tabs.addTab(learning_tab, "Learning")
        tabs.addTab(kalshi_tab, "Kalshi Debug")
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
        self.capture_closed_trades_for_learning()

        # Heavy visual/text widgets are throttled so the UI does not look like it
        # is rebuilding every tick. Price/P&L still update instantly.
        now = time.time()
        if now - self._last_chart_update_ts >= 0.90:
            self._last_chart_update_ts = now
            self.chart.set_candles(candles)

        self.last_decision = self.setup_engine.evaluate(candles)
        self.learning.record_snapshot(price, self.last_decision)
        self.auto_manage_signal_plan()
        self.update_trade_button_state()

        sig = self._decision_signature(self.last_decision)
        if now - self._last_ai_update_ts >= 1.25 or sig != self._last_decision_signature:
            self._last_ai_update_ts = now
            self._last_decision_signature = sig
            self.update_ai(price)
        self.update_stats()

    def update_timer(self) -> None:
        import time
        now = time.time()
        if now - self._last_kalshi_refresh > 20:
            self._last_kalshi_refresh = now
            self.kalshi_timer.refresh_async()
        snap = self.kalshi_timer.snapshot()
        s = snap.seconds_left()
        src = "Kalshi" if snap.source == "KALSHI" else "Est"
        ticker = f" {snap.ticker}" if snap.ticker else ""
        self.timer_label.setText(f"BTC15 {src}: {s//60:02d}:{s%60:02d}{ticker}")
        self.update_kalshi_debug(snap)

    def _decision_signature(self, d) -> str:
        if not d:
            return "none"
        plan = getattr(d, "plan", None)
        plan_sig = ""
        if plan:
            plan_sig = f"{plan.side}:{plan.entry:.2f}:{plan.stop:.2f}:{plan.target:.2f}"
        return "|".join([
            str(getattr(d, "ready", False)),
            str(getattr(d, "side", "WAIT")),
            str(getattr(d, "grade", "")),
            str(getattr(d, "confidence", 0)),
            str(getattr(d, "latest_fvg", "")),
            plan_sig,
            ";".join(getattr(d, "reasons", [])[-3:]),
        ])

    def _set_text_stable(self, box: QTextEdit, text: str, attr_name: str) -> None:
        # QTextEdit.setPlainText resets scroll/caret. Only write if content actually
        # changed, preserve scroll, and do not steal focus from the chart.
        if getattr(self, attr_name, "") == text:
            return
        setattr(self, attr_name, text)
        bar = box.verticalScrollBar()
        old = bar.value()
        at_bottom = old >= max(0, bar.maximum() - 3)
        box.blockSignals(True)
        box.setUpdatesEnabled(False)
        box.setPlainText(text)
        box.setUpdatesEnabled(True)
        box.blockSignals(False)
        if at_bottom:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(min(old, bar.maximum()))

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
            f"Auto Plan\n{plan_note}\n\n"
            f"Why Waiting\n{reasons}\n\n"
            f"Rule\nNo auto plan unless: trend + impulse + FVG + pullback + engulfing/rejection + RR >= 2."
        )
        self._set_text_stable(self.ai_box, ai_text, "_last_ai_text")
        self.update_thinking_panel(d)

    def update_thinking_panel(self, d) -> None:
        snap = self.kalshi_timer.snapshot()
        timer_line = f"Kalshi BTC15: {snap.label()} ({snap.source})"
        if snap.ticker:
            timer_line += f"\nMarket: {snap.ticker}"
        if snap.last_error and snap.source != "KALSHI":
            timer_line += f"\nTimer note: {snap.last_error}"

        checklist = d.checklist or ["❌ Still building candle context"]
        reasons = d.reasons or ["Monitoring live BTC candles"]
        plan = "No buy-in yet"
        if d.ready and d.plan:
            plan = (
                f"{d.plan.side} AUTO PLAN READY\n"
                f"Entry:  {d.plan.entry:,.2f}\n"
                f"Stop:   {d.plan.stop:,.2f}\n"
                f"Target: {d.plan.target:,.2f}\n"
                f"RR:     {d.plan.rr:.2f}:1"
            )
        text = (
            "FVG Method Thinking\n\n"
            f"{timer_line}\n\n"
            "Question Process\n"
            "1. Do we have enough 1m candles?\n"
            "2. Are 15m and 5m trend aligned?\n"
            "3. Did impulse create a clean FVG/GAP?\n"
            "4. Did price pull back into the GAP?\n"
            "5. Did engulfing/rejection confirm?\n"
            "6. Is RR >= minimum?\n\n"
            "Live Checklist\n" + "\n".join(checklist[-10:]) + "\n\n"
            "Why waiting / why ready\n" + "\n".join("• " + r for r in reasons[-8:]) + "\n\n"
            "Trade Plan\n" + plan
        )
        self._set_text_stable(self.thinking_box, text, "_last_thinking_text")

    def clean_chart_view(self) -> None:
        self.chart.max_gap_boxes = 6
        self.chart.show_filled_gaps = False
        self.chart.show_gap_labels = True
        self.chart.show_swing_labels = True
        self.chart._redraw()
        self.log("Clean Chart: reduced to the newest active GAP boxes, fewer labels, and major H/L only")

    def toggle_filled_gaps(self) -> None:
        self.chart.show_filled_gaps = not self.chart.show_filled_gaps
        self.chart._redraw()
        self.log(f"Filled GAP visibility: {'ON' if self.chart.show_filled_gaps else 'OFF'}")

    def toggle_swing_labels(self) -> None:
        self.chart.show_swing_labels = not self.chart.show_swing_labels
        self.chart._redraw()
        self.log(f"High/Low labels: {'ON' if self.chart.show_swing_labels else 'OFF'}")

    def update_trade_button_state(self) -> None:
        ready = bool(self.last_decision and self.last_decision.ready and getattr(self.last_decision, "plan", None))
        has_open = bool(self.account.open_trade)
        if has_open:
            text = "Paper Trade Open"
            css = "QPushButton { border: 2px solid #2563eb; color: #bfdbfe; font-weight: 700; }"
        elif ready:
            text = "Open Auto Plan Paper Trade"
            css = "QPushButton { border: 2px solid #22c55e; color: #bbf7d0; font-weight: 700; }"
        else:
            text = "Waiting For Valid Setup"
            css = "QPushButton { border: 2px solid #dc2626; color: #fecaca; font-weight: 700; }"
        if hasattr(self, "open_btn"):
            self.open_btn.setText(text)
            self.open_btn.setStyleSheet(css)
            self.open_btn.setEnabled(ready and not has_open)

    def apply_kalshi_url(self) -> None:
        url = self.kalshi_url_box.text().strip()
        self.kalshi_timer.set_target_url(url)
        self.log(f"Kalshi target URL set: {url}")

    def auto_manage_signal_plan(self) -> None:
        """Create/clear the chart plan from the strategy only.

        This prevents the app from showing fake ENTRY lines. If there is no
        validated FVG confirmation setup and no open paper trade, the chart plan
        is cleared. When the setup becomes valid, a BUY-IN/STOP/TARGET plan is
        displayed automatically.
        """
        d = self.last_decision
        if not d or not d.ready or not d.plan:
            if not self.account.open_trade and self.chart.trade_plan.get("active"):
                self.chart.clear_plan()
                self._last_auto_plan_sig = ""
            return

        sig = f"{d.plan.side}:{d.plan.entry:.2f}:{d.plan.stop:.2f}:{d.plan.target:.2f}"
        if sig == self._last_auto_plan_sig:
            return
        self._last_auto_plan_sig = sig
        self.side_box.setCurrentText(d.plan.side)
        self.chart.set_plan(d.plan.side, d.plan.entry, d.plan.stop, d.plan.target, active=True, mode="plan")
        self.log_signal(
            f"AUTO PLAN {d.plan.side} | buy-in {d.plan.entry:,.2f} | stop {d.plan.stop:,.2f} | "
            f"target {d.plan.target:,.2f} | RR {d.plan.rr:.2f}:1 | confidence {d.confidence}% | grade {d.grade}"
        )
        # Major feature: optional hands-free paper mode. OFF by default.
        if self.auto_paper_toggle.isChecked() and not self.account.open_trade and sig != self._auto_opened_signal_sig:
            self._auto_opened_signal_sig = sig
            self.open_planned_trade()

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
            self.log("No auto plan yet. Waiting for confirmed FVG setup first.")
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
            self.chart.set_plan(str(plan.get("side", "LONG")), float(plan["entry"]), float(plan["stop"]), float(plan["target"]), active=True, mode="trade")
            self.log_signal(f"OPENED PAPER {plan.get('side')} @ {float(plan['entry']):,.2f} | stop {float(plan['stop']):,.2f} | target {float(plan['target']):,.2f}")
        except Exception as e:
            self.log(str(e))

    def on_learning_toggle(self) -> None:
        self.learning.enabled = self.learning_toggle.isChecked()
        self.update_learning_panel()
        self.update_trade_button_state()

    def capture_closed_trades_for_learning(self) -> None:
        for trade in self.account.trades:
            if trade.status == "CLOSED" and id(trade) not in self._learned_closed_trade_ids:
                self._learned_closed_trade_ids.add(id(trade))
                self.learning.record_trade_outcome(trade)
                result = "WIN" if trade.pnl > 0 else "LOSS"
                self.log_signal(f"CLOSED {result} {trade.side} | exit {float(trade.exit_price or 0):,.2f} | P/L ${trade.pnl:,.2f}")
                if not self.account.open_trade:
                    self.chart.clear_plan(emit=False)
                self.log(f"Learning saved outcome: {trade.side} P/L ${trade.pnl:,.2f}")

    def update_learning_panel(self) -> None:
        if hasattr(self, "learning_box"):
            self.learning_box.setPlainText(self.learning.summary_text())

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
        self.update_learning_panel()
        self.update_trade_button_state()

    def log_signal(self, message: str) -> None:
        from datetime import datetime
        line = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        self._journal_lines.append(line)
        self._journal_lines = self._journal_lines[-200:]
        if hasattr(self, "signal_box"):
            self.signal_box.setPlainText("\n".join(reversed(self._journal_lines)) or "No auto signals yet.")
        self.logger.info("SIGNAL " + message)

    def update_kalshi_debug(self, snap) -> None:
        if not hasattr(self, "kalshi_debug_box"):
            return
        close = snap.close_time.isoformat() if snap.close_time else "None"
        updated = f"{time.time() - snap.updated_at:.1f}s ago" if snap.updated_at else "never"
        text = (
            "Kalshi BTC15 Sync Debug\n\n"
            f"Source: {snap.source}\n"
            f"Target URL: {self.kalshi_url_box.text().strip()}\n"
            f"Target ticker: {getattr(self.kalshi_timer, 'target_ticker', '') or 'None'}\n"
            f"Matched ticker: {snap.ticker or 'None'}\n"
            f"Title: {snap.title or 'None'}\n"
            f"Close time: {close}\n"
            f"Time left: {snap.seconds_left()//60:02d}:{snap.seconds_left()%60:02d}\n"
            f"Updated: {updated}\n"
            f"Last error: {snap.last_error or 'None'}\n\n"
            "If source says ESTIMATED, the public Kalshi lookup did not find the same active BTC15 market your app is showing yet."
        )
        self.kalshi_debug_box.setPlainText(text)

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_box.append(message)

    def closeEvent(self, event) -> None:
        self.feed.stop()
        event.accept()
