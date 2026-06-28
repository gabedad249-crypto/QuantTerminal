from PySide6.QtCore import QTimer, Signal, QObject, Qt
import time
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTabWidget, QPushButton, QListWidget, QTextEdit, QDoubleSpinBox,
    QComboBox, QFormLayout, QCheckBox, QLineEdit, QSplitter
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
        self._last_auto_log_sig = ""
        self._last_signal_ready = False
        self._last_ready_signal_sig = ""
        self._journal_lines: list[str] = []
        self._timeline_lines: list[str] = []
        self._last_timeline_state = ""
        self._auto_opened_signal_sig = ""
        self._last_self_tune_ts = 0.0
        self._active_gap_key = ""
        self._planned_gap_key = ""
        self._used_gap_keys: set[str] = set()
        self._last_15m_bucket = 0
        self._last_15m_open = None

        self.bus = PriceBus()
        self.bus.price.connect(self.queue_price)
        self.candles = CandleBuilder(60)
        self.account = PaperAccount(settings.get("starting_balance", 100000.0))
        self.setup_engine = FVGSetupEngine(min_rr=float(settings.get("minimum_rr", 2.0)))
        from pathlib import Path
        self.learning = LearningMemory(Path("memory"))
        self.kalshi_timer = KalshiBTC15Timer(settings.get("kalshi_market_url", "https://kalshi.com/category/crypto/btc?frequency=fifteen_min"))
        self._last_kalshi_refresh = 0.0
        self.feed = CoinbaseFeed(lambda p: self.bus.price.emit(p), settings.get("symbol", "BTC-USD"))

        self.price_label = QLabel("Price: --")
        self.price_label.setObjectName("Title")
        self.timer_label = QLabel("15m: --:--")
        self.timer_label.setObjectName("Title")
        self.move_label = QLabel("BTC15 Δ --")
        self.move_label.setObjectName("Muted")
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
        self.audit_box = QTextEdit(); self.audit_box.setReadOnly(True)
        self.learning_box = QTextEdit(); self.learning_box.setReadOnly(True)
        self.signal_box = QTextEdit(); self.signal_box.setReadOnly(True)
        self.timeline_box = QTextEdit(); self.timeline_box.setReadOnly(True)
        self.kalshi_debug_box = QTextEdit(); self.kalshi_debug_box.setReadOnly(True)
        self.backtest_box = QTextEdit(); self.backtest_box.setReadOnly(True)
        self.memory_stats_box = QTextEdit(); self.memory_stats_box.setReadOnly(True)
        self.auto_tune_box = QTextEdit(); self.auto_tune_box.setReadOnly(True)
        self.learning_toggle = QCheckBox("Learning Mode")
        self.learning_toggle.setChecked(True)
        self.learning_toggle.stateChanged.connect(self.on_learning_toggle)
        self.auto_paper_toggle = QCheckBox("Auto-open paper when ready")
        self.auto_paper_toggle.setChecked(True)
        self.mode_box = QComboBox(); self.mode_box.addItems(["Paper Training (auto paper)", "Recommend Only (alerts)"])
        self.kalshi_url_box = QLineEdit(settings.get("kalshi_market_url", "https://kalshi.com/category/crypto/btc?frequency=fifteen_min"))
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
        self.mode_box.currentTextChanged.connect(self.on_mode_changed)
        self.auto_paper_toggle.stateChanged.connect(self.on_mode_changed)

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
        top_l.addSpacing(20); top_l.addWidget(self.timer_label); top_l.addSpacing(20); top_l.addWidget(self.move_label); top_l.addSpacing(20); top_l.addWidget(self.feed_label)
        root.addWidget(top)

        mid = QSplitter(Qt.Horizontal)
        mid.setChildrenCollapsible(False)
        left = self._panel("Watchlist"); left.setMinimumWidth(140); left.setMaximumWidth(360)
        self.watchlist = QListWidget(); self.watchlist.addItems(["Paper Trading", "Journal", "Signals", "Timeline", "Learning", "Memory", "Backtests", "Kalshi", "Logs", "Settings"])
        self.watchlist.itemClicked.connect(self.on_watchlist_clicked)
        left.layout().addWidget(self.watchlist); mid.addWidget(left)

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
        chart_tools.addStretch(); chart_tools.addWidget(QLabel("v0.5.1: paper training mode • auto UP/DOWN • resizable layout"))
        chart_panel.layout().addLayout(chart_tools)
        chart_panel.layout().addWidget(self.chart)
        mid.addWidget(chart_panel)

        right = self._panel("AI / Thinking")
        right.setMinimumWidth(300); right.setMaximumWidth(650)
        decision_tabs = QTabWidget()
        decision_tabs.addTab(self.ai_box, "Decision")
        decision_tabs.addTab(self.thinking_box, "Thinking Checklist")
        right.layout().addWidget(decision_tabs)

        planner = QFrame(); planner.setObjectName("Panel")
        fl = QFormLayout(planner)
        direction_label = QLabel("Direction: AUTO from chart (UP/LONG or DOWN/SHORT)")
        direction_label.setObjectName("Title")
        fl.addRow(direction_label)
        side_help = QLabel("UP/LONG = paper buy when chart favors up. DOWN/SHORT = paper sell when chart favors down. On Kalshi this maps to Up/Down style thinking.")
        side_help.setObjectName("Muted")
        fl.addRow(side_help)
        fl.addRow("Mode", self.mode_box)
        fl.addRow("Buy-in USD", self.size_box)
        fl.addRow("Stop loss %", self.stop_box)
        fl.addRow("Target RR", self.rr_box)
        fl.addRow("Planned buy-in", self.entry_price_box)
        fl.addRow("Planned stop", self.stop_price_box)
        fl.addRow("Planned target", self.target_price_box)
        fl.addRow("Ratio", self.plan_rr_label)
        fl.addRow("Auto paper", self.auto_paper_toggle)
        note = QLabel("Training mode auto-opens paper trades only after FVG + pullback + confirmation. Recommend mode only tells you what to do.")
        note.setObjectName("Muted")
        fl.addRow(note)
        right.layout().addWidget(planner)
        mid.addWidget(right)
        mid.setSizes([180, 900, 420])
        root.addWidget(mid, 1)

        self.tabs = QTabWidget()
        tabs = self.tabs
        paper = QWidget(); paper_l = QVBoxLayout(paper)
        paper_l.addWidget(self.stats_label); paper_l.addWidget(self.open_trade_label); paper_l.addWidget(self.trades_box); paper_l.addStretch()
        audit_tab = QWidget(); audit_l = QVBoxLayout(audit_tab)
        audit_l.addWidget(QLabel("Paper Journal / Trade Audit — verifies wins by TARGET and losses by STOP"))
        audit_l.addWidget(self.audit_box)
        logs = QWidget(); logs_l = QVBoxLayout(logs); logs_l.addWidget(self.log_box)
        learning_tab = QWidget(); learning_l = QVBoxLayout(learning_tab)
        learning_l.addWidget(self.learning_toggle)
        learning_l.addWidget(self.learning_box)
        memory_tab = QWidget(); memory_l = QVBoxLayout(memory_tab)
        memory_l.addWidget(QLabel("Memory Stats — similarity scoring + learned paper outcomes"))
        memory_l.addWidget(self.memory_stats_box)
        tune_btn = QPushButton("Apply Safe Auto-Tune")
        tune_btn.clicked.connect(self.apply_auto_tune)
        memory_l.addWidget(tune_btn)
        memory_l.addWidget(self.auto_tune_box)
        backtest_tab = QWidget(); backtest_l = QVBoxLayout(backtest_tab)
        run_backtest = QPushButton("Run FVG Replay Backtest")
        run_backtest.clicked.connect(self.run_replay_backtest)
        export_btn = QPushButton("Export Paper Report")
        export_btn.clicked.connect(self.export_paper_report)
        backtest_l.addWidget(run_backtest)
        backtest_l.addWidget(export_btn)
        backtest_l.addWidget(self.backtest_box)
        signal_tab = QWidget(); signal_l = QVBoxLayout(signal_tab); signal_l.addWidget(self.signal_box)
        timeline_tab = QWidget(); timeline_l = QVBoxLayout(timeline_tab)
        timeline_l.addWidget(QLabel("Signal Timeline — step-by-step reasoning trail for each setup"))
        timeline_l.addWidget(self.timeline_box)
        kalshi_tab = QWidget(); kalshi_l = QVBoxLayout(kalshi_tab)
        apply_kalshi = QPushButton("Sync this Kalshi URL")
        apply_kalshi.clicked.connect(self.apply_kalshi_url)
        kalshi_l.addWidget(QLabel("Kalshi BTC15 URL — category page is best for live sync"))
        kalshi_l.addWidget(self.kalshi_url_box)
        kalshi_l.addWidget(apply_kalshi)
        kalshi_l.addWidget(self.kalshi_debug_box)
        tabs.addTab(paper, "Paper Trading")
        tabs.addTab(audit_tab, "Paper Journal / Audit")
        tabs.addTab(signal_tab, "Signal Journal")
        tabs.addTab(timeline_tab, "Signal Timeline")
        tabs.addTab(learning_tab, "Learning")
        tabs.addTab(memory_tab, "Memory Stats")
        tabs.addTab(backtest_tab, "Backtest / Replay")
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
        self.update_btc15_move(price)
        candles = self.candles.update_price(price)
        # Paper trades are forced closed at the Kalshi BTC15 close time; no paper trade is allowed to survive past the 15m market.
        snap_for_trade = self.kalshi_timer.snapshot()
        expired = bool(snap_for_trade.close_time and snap_for_trade.seconds_left() <= 0)
        self.account.update(price, force_close=expired, force_reason="KALSHI_15M_END" if expired else "")
        open_trade = self.account.open_trade
        self.chart.set_live_price(price, open_trade.pnl if open_trade else 0.0, open_trade.side if open_trade else "")
        self.capture_closed_trades_for_learning()

        # Heavy visual/text widgets are throttled so the UI does not look like it
        # is rebuilding every tick. Price/P&L still update instantly.
        now = time.time()
        if now - self._last_chart_update_ts >= 0.90:
            self._last_chart_update_ts = now
            self.chart.set_candles(candles)

        if self.account.open_trade:
            # During an active paper trade, stop hunting for new trades. Watch and manage the current one.
            if now - self._last_ai_update_ts >= 0.75:
                self._last_ai_update_ts = now
                self.update_active_trade_decision(price)
            self.update_stats()
            self.self_auto_tune()
            return

        self.last_decision = self.setup_engine.evaluate(candles)
        self.learning.record_snapshot(price, self.last_decision)
        self.auto_manage_signal_plan()
        self.update_trade_button_state()
        self.self_auto_tune()

        sig = self._decision_signature(self.last_decision)
        if now - self._last_ai_update_ts >= 1.25 or sig != self._last_decision_signature:
            self._last_ai_update_ts = now
            self._last_decision_signature = sig
            self.update_ai(price)
        self.update_stats()


    def update_btc15_move(self, price: float) -> None:
        # Watch the current 15-minute BTC move as UP/DOWN %. This is not a
        # Kalshi contract price; it is the underlying BTC move within the active
        # 15m candle/window so you can compare direction quickly.
        bucket = int(time.time()) - (int(time.time()) % 900)
        if self._last_15m_bucket != bucket or self._last_15m_open is None:
            self._last_15m_bucket = bucket
            # Prefer the first 1m candle inside this 15m window.
            inside = [c for c in self.candles.candles if int(c.ts) >= bucket]
            self._last_15m_open = float(inside[0].open) if inside else float(price)
        base = float(self._last_15m_open or price)
        pct = ((float(price) - base) / base * 100.0) if base else 0.0
        arrow = "UP" if pct >= 0 else "DOWN"
        self.move_label.setText(f"BTC15 {arrow} {pct:+.3f}%")
        self.move_label.setObjectName("Green" if pct >= 0 else "Red")
        self.move_label.style().unpolish(self.move_label); self.move_label.style().polish(self.move_label)

    def on_watchlist_clicked(self, item) -> None:
        name = item.text()
        # Watchlist is now real navigation, not just decoration.
        mapping = {
            "Paper Trading": 0,
            "Journal": 1,
            "Signals": 2,
            "Timeline": 3,
            "Learning": 4,
            "Memory": 5,
            "Backtests": 6,
            "Kalshi": 7,
            "Logs": 8,
            "Settings": 7,
        }
        if hasattr(self, "tabs") and name in mapping:
            self.tabs.setCurrentIndex(mapping[name])

    def update_timer(self) -> None:
        import time
        now = time.time()
        if now - self._last_kalshi_refresh > 5:
            self._last_kalshi_refresh = now
            self.kalshi_timer.refresh_async()
        snap = self.kalshi_timer.snapshot()
        s = snap.seconds_left()
        src = "Kalshi" if snap.source in ("KALSHI", "KALSHI_ACTIVE", "URL_TICKER") else "Est"
        ticker = f" {snap.ticker}" if snap.ticker else ""
        self.timer_label.setText(f"BTC15 {src}: {s//60:02d}:{s%60:02d}{ticker}")
        self.update_kalshi_debug(snap)
        # Also close an open paper trade exactly when the BTC15 market ends, even if price is flat.
        if self.latest_price is not None and self.account.open_trade and snap.close_time and snap.seconds_left() <= 0:
            self.account.update(float(self.latest_price), force_close=True, force_reason="KALSHI_15M_END")
            self.capture_closed_trades_for_learning()
            self.update_stats()

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

    def _set_text_stable(self, box: QTextEdit, text: str, attr_name: str | None = None) -> None:
        # QTextEdit.setPlainText resets scroll/caret. Only write if content actually
        # changed, preserve scroll, and do not steal focus from the chart.
        if attr_name is None:
            attr_name = f"_stable_text_{id(box)}"
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
        if self.account.open_trade:
            self.update_active_trade_decision(price)
            return
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
        sim = self.learning.similarity(d)
        sim_text = f"{sim['matches']} matches | {sim['win_rate']:.1f}% WR | avg ${sim['avg_pnl']:.2f} | score {sim['score']}/100 | {sim['label']}"

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
        sim = self.learning.similarity(d)
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
        self.chart.max_gap_boxes = 3
        self.chart.show_filled_gaps = False
        self.chart.show_gap_labels = True
        self.chart.show_swing_labels = False
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


    def on_mode_changed(self) -> None:
        """Keep training/recommend mode obvious and deterministic."""
        mode = self.mode_box.currentText() if hasattr(self, "mode_box") else "Paper Training (auto paper)"
        training = mode.startswith("Paper Training")
        if hasattr(self, "auto_paper_toggle"):
            self.auto_paper_toggle.blockSignals(True)
            self.auto_paper_toggle.setChecked(training)
            self.auto_paper_toggle.setEnabled(training)
            self.auto_paper_toggle.blockSignals(False)
        self.log(f"Mode set: {mode}")
        self.update_trade_button_state()

    def _configured_plan_values(self, d):
        """Apply user buy-in/stop/target controls to the strategy plan.

        The strategy decides WHEN and DIRECTION. The controls decide HOW MUCH,
        stop distance, and reward target.
        """
        if not d or not getattr(d, "plan", None):
            return None
        side = d.plan.side
        entry = float(d.plan.entry)
        stop_pct = max(float(self.stop_box.value()), 0.01) / 100.0
        rr = max(float(self.rr_box.value()), 0.25)
        risk = max(entry * stop_pct, 1.0)
        if side == "LONG":
            stop = entry - risk
            target = entry + risk * rr
        else:
            stop = entry + risk
            target = entry - risk * rr
        return side, entry, stop, target, rr

    def update_active_trade_decision(self, price: float) -> None:
        t = self.account.open_trade
        if not t:
            return
        snap = self.kalshi_timer.snapshot()
        if t.side == "LONG":
            dist_target = max(0.0, t.target - price)
            dist_stop = max(0.0, price - t.stop)
            direction = "UP / LONG"
        else:
            dist_target = max(0.0, price - t.target)
            dist_stop = max(0.0, t.stop - price)
            direction = "DOWN / SHORT"
        text = (
            "ACTIVE PAPER TRADE — WATCHING\n\n"
            "The bot is NOT hunting for a new setup while this trade is open.\n\n"
            f"Direction: {direction}\n"
            f"Buy-in size: ${t.size_usd:,.2f}\n"
            f"Entry:  {t.entry:,.2f}\n"
            f"Now:    {price:,.2f}\n"
            f"Stop:   {t.stop:,.2f}\n"
            f"Target: {t.target:,.2f}\n"
            f"Live P/L: ${t.pnl:,.2f}\n"
            f"BTC15 expires: {snap.label()}\n\n"
            f"Distance to target: {dist_target:,.2f}\n"
            f"Distance to stop:   {dist_stop:,.2f}\n\n"
            "Exit rules:\n"
            "• Target hit = win.\n"
            "• Stop hit = loss.\n"
            "• BTC15 timer ends = close trade at current price."
        )
        self._set_text_stable(self.ai_box, text, "_last_ai_text")
        self._set_text_stable(self.thinking_box, text, "_last_thinking_text")

    def auto_manage_signal_plan(self) -> None:
        """Create/clear the chart plan from the strategy only.

        This prevents the app from showing fake ENTRY lines. If there is no
        validated FVG confirmation setup and no open paper trade, the chart plan
        is cleared. When the setup becomes valid, a BUY-IN/STOP/TARGET plan is
        displayed automatically.
        """
        if self.account.open_trade:
            return
        d = self.last_decision
        gap_key = getattr(d, "active_fvg_key", "") if d else ""
        if gap_key and hasattr(self.chart, "set_focus_gap_key"):
            self.chart.set_focus_gap_key(gap_key)

        if not d or not d.ready or not d.plan:
            if d:
                state = "WAIT:" + str(gap_key) + ";" + ";".join(getattr(d, "checklist", [])[-4:]) + ";" + ";".join(getattr(d, "reasons", [])[-3:])
                if state != self._last_timeline_state:
                    self._last_timeline_state = state
                    reason = (getattr(d, "reasons", [])[-1] if getattr(d, "reasons", []) else "Building candle context")
                    self.log_timeline(f"WAIT | {reason}")
            if not self.account.open_trade and self.chart.trade_plan.get("active"):
                self.chart.clear_plan()
                self._last_auto_plan_sig = ""
                self._planned_gap_key = ""
            return

        # One focused GAP at a time: once a GAP has produced a plan/trade, do not
        # spam fresh plans from that same FVG. Wait for a new GAP.
        if gap_key in self._used_gap_keys and not self.account.open_trade:
            if self.chart.trade_plan.get("active"):
                self.chart.clear_plan()
            self.log_timeline(f"SKIP | GAP already used {gap_key}")
            return

        configured = self._configured_plan_values(d)
        if not configured:
            return
        side, entry, stop, target, user_rr = configured
        visual_sig = f"{gap_key}:{side}:{entry:.0f}:{stop:.0f}:{target:.0f}:{self.size_box.value():.0f}"
        self.side_box.setCurrentText(side)
        if visual_sig != self._last_auto_plan_sig:
            self.chart.set_plan(side, entry, stop, target, active=True, mode="plan")
            self._last_auto_plan_sig = visual_sig
            self._planned_gap_key = gap_key

        log_sig = f"{gap_key}:{side}:{round(stop/25)*25:.0f}:{round(target/25)*25:.0f}:{d.grade}:{d.confidence//5*5}:{self.size_box.value():.0f}"
        if log_sig != self._last_auto_log_sig:
            self._last_auto_log_sig = log_sig
            self.log_signal(
                f"AUTO PLAN READY {side} | GAP {gap_key or 'unknown'} | buy-in {entry:,.2f} | stop {stop:,.2f} | "
                f"target {target:,.2f} | RR {user_rr:.2f}:1 | confidence {d.confidence}% | grade {d.grade}"
            )
            self.log_timeline(
                f"READY {side} | GAP {gap_key or 'unknown'} | Trend {d.trend_15m}/{d.trend_5m} | FVG {d.latest_fvg} | "
                f"Buy-in {entry:,.2f} Stop {stop:,.2f} Target {target:,.2f}"
            )
        training_mode = hasattr(self, "mode_box") and self.mode_box.currentText().startswith("Paper Training")
        if training_mode and self.auto_paper_toggle.isChecked() and not self.account.open_trade and log_sig != self._auto_opened_signal_sig:
            self._auto_opened_signal_sig = log_sig
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
        # If the strategy has a valid setup, changing stop/RR/buy-in instantly updates the planned lines.
        if self.last_decision and self.last_decision.ready and getattr(self.last_decision, "plan", None) and not self.account.open_trade:
            self._last_auto_plan_sig = ""
            self.auto_manage_signal_plan()
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
                f"FVG setup | {self.last_decision.trend_15m}/{self.last_decision.trend_5m} | {self.last_decision.latest_fvg} | confidence {self.last_decision.confidence}% | RR {float(plan.get('rr', 0)):.2f}:1",
                expires_at=self.kalshi_timer.snapshot().close_time.timestamp() if self.kalshi_timer.snapshot().close_time else None
            )
            if self._planned_gap_key:
                self._used_gap_keys.add(self._planned_gap_key)
            self.chart.set_plan(str(plan.get("side", "LONG")), float(plan["entry"]), float(plan["stop"]), float(plan["target"]), active=True, mode="trade")
            exp = self.kalshi_timer.snapshot().label()
            self.log_signal(f"OPENED PAPER {plan.get('side')} @ {float(plan['entry']):,.2f} | stop {float(plan['stop']):,.2f} | target {float(plan['target']):,.2f} | expires BTC15 {exp}")
            self.log_timeline(f"OPENED PAPER {plan.get('side')} | entry {float(plan['entry']):,.2f} | expires BTC15 {exp}")
        except Exception as e:
            self.log(str(e))

    def on_learning_toggle(self) -> None:
        self.learning.enabled = self.learning_toggle.isChecked()
        self.update_learning_panel()
        self.update_memory_stats_panel()
        self.update_trade_button_state()

    def capture_closed_trades_for_learning(self) -> None:
        for trade in self.account.trades:
            if trade.status == "CLOSED" and id(trade) not in self._learned_closed_trade_ids:
                self._learned_closed_trade_ids.add(id(trade))
                self.learning.record_trade_outcome(trade)
                result = "WIN" if trade.exit_reason == "TARGET" or trade.pnl > 0 else "LOSS"
                why = trade.exit_reason or ("TARGET" if trade.pnl > 0 else "STOP")
                self.log_signal(f"CLOSED {result} {trade.side} via {why} | exit {float(trade.exit_price or 0):,.2f} | P/L ${trade.pnl:,.2f}")
                self.log_timeline(f"CLOSED {result} {trade.side} via {why} | exit {float(trade.exit_price or 0):,.2f} | P/L ${trade.pnl:,.2f}")
                if not self.account.open_trade:
                    self.chart.clear_plan(emit=False)
                self.log(f"Learning saved outcome: {trade.side} P/L ${trade.pnl:,.2f}")

    def update_learning_panel(self) -> None:
        if hasattr(self, "learning_box"):
            self._set_text_stable(self.learning_box, self.learning.summary_text(self.last_decision), "_last_learning_text")

    def update_stats(self) -> None:
        s = self.account.stats()
        self.stats_label.setText(
            f"Cash: ${s['balance']:,.2f}    Reserved: ${s.get('reserved', 0):,.2f}    "
            f"Equity: ${s.get('equity', s['balance']):,.2f}    Open P/L: ${s['open_pnl']:,.2f}    "
            f"Closed P/L: ${s['closed_pnl']:,.2f}    Trades: {s['trades']}    "
            f"Win Rate: {s['win_rate']:.1f}%    Profit Factor: {s['profit_factor']:.2f}"
        )
        t = self.account.open_trade
        if t:
            self.open_trade_label.setText(
                f"OPEN {t.direction_label()} | Size ${t.size_usd:,.2f} | Entry {t.entry:,.2f} | "
                f"Stop {t.stop:,.2f} | Target {t.target:,.2f} | Live P/L ${t.pnl:,.2f}"
            )
        else:
            self.open_trade_label.setText("No open paper trade")
        closed = [x for x in self.account.trades if x.status == "CLOSED"][-8:]
        if closed:
            lines = ["Recent closed paper trades:"]
            for tr in reversed(closed):
                result = "WIN" if tr.exit_reason == "TARGET" or tr.pnl > 0 else "LOSS"
                reason = tr.exit_reason or ("TARGET" if tr.pnl > 0 else "STOP")
                lines.append(f"#{tr.trade_id:04d} {result} {tr.side} via {reason} | size ${tr.size_usd:,.0f} | entry {tr.entry:,.2f} exit {float(tr.exit_price or 0):,.2f} P/L ${tr.pnl:,.2f}")
            self._set_text_stable(self.trades_box, "\n".join(lines), "_last_trades_text")
        else:
            self._set_text_stable(self.trades_box, "No closed paper trades yet. The account will update automatically after TP/SL is hit.", "_last_trades_text")
        self.update_audit_panel()
        self.update_learning_panel()
        self.update_memory_stats_panel()
        self.update_trade_button_state()

    def update_audit_panel(self) -> None:
        if not hasattr(self, "audit_box"):
            return
        if not self.account.trades:
            self._set_text_stable(
                self.audit_box,
                "No paper trades yet.\n\n"
                "Audit rules:\n"
                "• LONG wins only if price reaches target above entry.\n"
                "• LONG loses if price reaches stop below entry.\n"
                "• SHORT wins only if price reaches target below entry.\n"
                "• SHORT loses if price reaches stop above entry.\n"
                "• Final P/L is recalculated from actual exit price, not from the label.",
                "_last_audit_text"
            )
            return
        lines = [
            "Paper Trade Audit",
            "Wins are counted only when exit_reason = TARGET or P/L > 0. Losses are STOP or P/L <= 0.",
            ""
        ]
        for tr in reversed(self.account.trades[-60:]):
            lines.append(tr.audit_line())
            if tr.status == "CLOSED":
                if tr.side == "LONG":
                    formula = f"LONG P/L = (exit-entry)/entry*size = ({float(tr.exit_price or 0):,.2f}-{tr.entry:,.2f})/{tr.entry:,.2f}*${tr.size_usd:,.0f}"
                else:
                    formula = f"SHORT P/L = (entry-exit)/entry*size = ({tr.entry:,.2f}-{float(tr.exit_price or 0):,.2f})/{tr.entry:,.2f}*${tr.size_usd:,.0f}"
                lines.append("   " + formula)
        self._set_text_stable(self.audit_box, "\n".join(lines), "_last_audit_text")


    def apply_auto_tune(self) -> None:
        """Safely apply the learned minimum RR recommendation.

        Auto-tune is conservative: it only changes the RR threshold after the
        memory engine has enough closed paper trades. It does not change the
        strategy or force trades.
        """
        current_rr = float(getattr(self.setup_engine, "min_rr", 2.0))
        try:
            result = self.learning.auto_tune(current_rr)
        except Exception as exc:
            msg = f"Auto-tune failed safely: {exc}"
            self.auto_tune_box.setPlainText(msg)
            self.log(msg)
            return

        if not result.get("ready"):
            msg = result.get("reason", "Auto-tune is not ready yet.")
            self.auto_tune_box.setPlainText(
                "Safe Auto-Tune\n\n"
                f"Status: WAIT\n"
                f"Current minimum RR: {current_rr:.2f}:1\n"
                f"Reason: {msg}\n\n"
                "Needs more closed paper trades before changing settings."
            )
            self.log("Auto-tune skipped: " + msg)
            return

        new_rr = float(result.get("recommended_min_rr", current_rr))
        self.setup_engine.min_rr = new_rr
        # Keep visible RR control in sync without triggering noisy rebuilds.
        if hasattr(self, "rr_box"):
            self.rr_box.blockSignals(True)
            self.rr_box.setValue(new_rr)
            self.rr_box.blockSignals(False)

        msg = (
            "Safe Auto-Tune\n\n"
            "Status: APPLIED\n"
            f"Old minimum RR: {current_rr:.2f}:1\n"
            f"New minimum RR: {new_rr:.2f}:1\n"
            f"Sample: {int(result.get('sample', 0))} closed trades\n"
            f"Win rate: {float(result.get('win_rate', 0.0)):.1f}%\n"
            f"Avg P/L: ${float(result.get('avg_pnl', 0.0)):.2f}\n\n"
            f"Reason: {result.get('reason', 'No reason supplied.')}"
        )
        self.auto_tune_box.setPlainText(msg)
        self.log(f"Auto-tune applied: min RR {current_rr:.2f} -> {new_rr:.2f}")

    def self_auto_tune(self) -> None:
        """Hands-free conservative auto-tune.

        It only changes the minimum RR after the memory engine has enough closed
        paper trades. It never invents new logic and never opens a trade by itself
        unless the Auto-open toggle is ON.
        """
        now = time.time()
        if now - getattr(self, "_last_self_tune_ts", 0.0) < 60:
            return
        self._last_self_tune_ts = now
        current_rr = float(getattr(self.setup_engine, "min_rr", 2.0))
        try:
            result = self.learning.auto_tune(current_rr)
        except Exception:
            return
        if not result.get("ready"):
            return
        new_rr = float(result.get("recommended_min_rr", current_rr))
        if abs(new_rr - current_rr) >= 0.05:
            self.setup_engine.min_rr = new_rr
            if hasattr(self, "rr_box"):
                self.rr_box.blockSignals(True)
                self.rr_box.setValue(new_rr)
                self.rr_box.blockSignals(False)
            self.log(f"Self auto-tune adjusted minimum RR {current_rr:.2f} -> {new_rr:.2f}")

    def update_memory_stats_panel(self) -> None:
        if not hasattr(self, "memory_stats_box"):
            return
        stats = self.learning.stats()
        closed = [t for t in self.account.trades if t.status == "CLOSED"]
        total_pnl = sum(t.pnl for t in closed)
        best = max((t.pnl for t in closed), default=0.0)
        worst = min((t.pnl for t in closed), default=0.0)
        text = (
            "Memory / Edge Stats\n\n"
            f"Learning: {'ON' if stats.get('enabled') else 'OFF'}\n"
            f"Setup snapshots saved: {stats.get('snapshots', 0)}\n"
            f"Outcomes learned: {stats.get('outcomes', 0)}\n"
            f"Learned win rate: {stats.get('win_rate', 0.0):.1f}%\n"
            f"Learned avg P/L: ${stats.get('avg_pnl', 0.0):.2f}\n\n"
            "Current session paper stats\n"
            f"Closed trades: {len(closed)}\n"
            f"Session P/L: ${total_pnl:,.2f}\n"
            f"Best trade: ${best:,.2f}\n"
            f"Worst trade: ${worst:,.2f}\n\n"
            "v0.5.0: one GAP at a time, similarity score, and conservative self auto-tune are active."
        )
        self._set_text_stable(self.memory_stats_box, text, "_last_memory_stats_text")

    def run_replay_backtest(self) -> None:
        candles = list(self.candles.candles)
        if len(candles) < 90:
            self._set_text_stable(self.backtest_box, "Need at least 90 one-minute candles before replay backtest can run.", "_last_backtest_text")
            return
        wins = losses = trades = 0
        total_pnl = 0.0
        lines = ["FVG Replay Backtest", "No future candles are shown to the engine during decisions.", ""]
        # Lightweight replay: evaluate one candle at a time and simulate a single open trade.
        open_trade = None
        for i in range(60, len(candles)):
            visible = candles[:i+1]
            price = visible[-1].close
            if open_trade:
                side, entry, stop, target, size = open_trade
                if side == "LONG":
                    hit_stop = price <= stop; hit_target = price >= target
                    pnl = (price - entry) / entry * size
                else:
                    hit_stop = price >= stop; hit_target = price <= target
                    pnl = (entry - price) / entry * size
                if hit_stop or hit_target:
                    trades += 1
                    total_pnl += pnl
                    if hit_target or pnl > 0:
                        wins += 1
                    else:
                        losses += 1
                    lines.append(f"#{trades:03d} {'WIN' if (hit_target or pnl > 0) else 'LOSS'} {side} exit {price:,.2f} P/L ${pnl:.2f}")
                    open_trade = None
                continue
            d = self.setup_engine.evaluate(visible)
            if d.ready and d.plan:
                open_trade = (d.plan.side, d.plan.entry, d.plan.stop, d.plan.target, 1000.0)
        win_rate = (wins / trades * 100) if trades else 0.0
        summary = [
            f"Trades: {trades}",
            f"Wins/Losses: {wins}/{losses}",
            f"Win rate: {win_rate:.1f}%",
            f"Paper P/L on $1,000 test size: ${total_pnl:,.2f}",
            "",
        ]
        self._set_text_stable(self.backtest_box, "\n".join(summary + lines[-80:]), "_last_backtest_text")

    def export_paper_report(self) -> None:
        from pathlib import Path
        from datetime import datetime
        out_dir = Path("exports"); out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"paper_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        s = self.account.stats()
        lines = [
            "Quant Terminal Paper Report",
            f"Generated: {datetime.now().isoformat(timespec='seconds')}",
            "",
            f"Cash: ${s['balance']:,.2f}",
            f"Equity: ${s.get('equity', s['balance']):,.2f}",
            f"Closed P/L: ${s['closed_pnl']:,.2f}",
            f"Trades: {s['trades']}",
            f"Win Rate: {s['win_rate']:.1f}%",
            f"Profit Factor: {s['profit_factor']:.2f}",
            "",
            "Trades:",
        ]
        for tr in self.account.trades:
            lines.append(tr.audit_line())
        path.write_text("\n".join(lines), encoding="utf-8")
        self.log(f"Exported paper report: {path}")
        self._set_text_stable(self.backtest_box, f"Exported report to:\n{path}", "_last_backtest_text")


    def log_timeline(self, message: str) -> None:
        import time
        stamp = time.strftime("%H:%M:%S")
        line = f"{stamp}  {message}"
        self._timeline_lines.append(line)
        self._timeline_lines = self._timeline_lines[-250:]
        if hasattr(self, "timeline_box"):
            self._set_text_stable(self.timeline_box, "\n".join(reversed(self._timeline_lines)) or "No signal timeline yet.", "_last_timeline_text")

    def log_signal(self, message: str) -> None:
        from datetime import datetime
        line = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        self._journal_lines.append(line)
        self._journal_lines = self._journal_lines[-200:]
        if hasattr(self, "signal_box"):
            self._set_text_stable(self.signal_box, "\n".join(reversed(self._journal_lines)) or "No auto signals yet.", "_last_signal_text")
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
            f"Candidates found: {getattr(snap, 'candidate_count', 0)}\n"
            f"Updated: {updated}\n"
            f"Last error: {snap.last_error or 'None'}\n\n"
            "Timer sources:\n"
            "• KALSHI_ACTIVE = nearest open KXBTC15M from the category page style sync.\n"
            "• URL_TICKER = exact pasted market URL, only used while still active.\n"
            "• ESTIMATED = quarter-hour fallback only."
        )
        self._set_text_stable(self.kalshi_debug_box, text, "_last_kalshi_debug_text")

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_box.append(message)

    def closeEvent(self, event) -> None:
        self.feed.stop()
        event.accept()
