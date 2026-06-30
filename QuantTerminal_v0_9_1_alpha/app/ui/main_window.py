from PySide6.QtCore import QTimer, Signal, QObject, Qt
import time
import json
from pathlib import Path
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
        self._ready_confirm_sig = ""
        self._ready_confirm_candle_ts = 0
        self._ready_confirm_count = 0
        self._traded_15m_buckets: set[int] = set()
        self._last_trade_open_ts = 0.0
        self._last_entry_block_reason = ""
        self._last_auto_entry_key = ""

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
        self.coach_box = QTextEdit(); self.coach_box.setReadOnly(True)
        self.coach_box.setText("Logic Coach\n\nWaiting for first evaluated setup...")
        self.stats_label = QLabel()
        self.open_trade_label = QLabel("No open paper trade")
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        self.trades_box = QTextEdit(); self.trades_box.setReadOnly(True)
        self.audit_box = QTextEdit(); self.audit_box.setReadOnly(True)
        self.learning_box = QTextEdit(); self.learning_box.setReadOnly(True)
        self.signal_box = QTextEdit(); self.signal_box.setReadOnly(True)
        self.timeline_box = QTextEdit(); self.timeline_box.setReadOnly(True)
        self.kalshi_debug_box = QTextEdit(); self.kalshi_debug_box.setReadOnly(True)
        self.data_health_box = QTextEdit(); self.data_health_box.setReadOnly(True)
        saved_ui = self._load_trading_ui_settings()
        self.backtest_box = QTextEdit(); self.backtest_box.setReadOnly(True)
        self.memory_stats_box = QTextEdit(); self.memory_stats_box.setReadOnly(True)
        self.auto_tune_box = QTextEdit(); self.auto_tune_box.setReadOnly(True)
        self.learning_toggle = QCheckBox("Learning Mode")
        self.learning_toggle.setChecked(True)
        self.learning_toggle.stateChanged.connect(self.on_learning_toggle)
        self.auto_paper_toggle = QCheckBox("Auto-open paper when ready")
        self.auto_paper_toggle.setChecked(bool(saved_ui.get("auto_paper", True)))
        self.mode_box = QComboBox(); self.mode_box.addItems(["Paper Training (auto paper)", "Recommend Only (alerts)"]); self.mode_box.setCurrentText(str(saved_ui.get("mode", "Paper Training (auto paper)")))
        self.training_speed_box = QComboBox(); self.training_speed_box.addItems(["More Trades", "Scalp Heavy", "Strict Quality", "Max Training Data"]); self.training_speed_box.setCurrentText(str(saved_ui.get("training_speed", "More Trades")))
        self.kalshi_url_box = QLineEdit(settings.get("kalshi_market_url", "https://kalshi.com/category/crypto/btc?frequency=fifteen_min"))
        self.kalshi_url_box.setPlaceholderText("Paste Kalshi BTC15 market URL")

        self.side_box = QComboBox(); self.side_box.addItems(["LONG", "SHORT"])
        self.size_box = NoWheelDoubleSpinBox(); self.size_box.setRange(1, 100000); self.size_box.setDecimals(2); self.size_box.setSingleStep(1); self.size_box.setValue(float(saved_ui.get("buy_in_usd", 20.00))); self.size_box.setPrefix("$")
        self.stop_box = NoWheelDoubleSpinBox(); self.stop_box.setRange(0.01, 100000); self.stop_box.setDecimals(2); self.stop_box.setSingleStep(0.10); self.stop_box.setValue(float(saved_ui.get("stop_loss_usd", 0.50))); self.stop_box.setPrefix("$")
        self.rr_box = NoWheelDoubleSpinBox(); self.rr_box.setRange(0.01, 100000); self.rr_box.setDecimals(2); self.rr_box.setSingleStep(0.10); self.rr_box.setValue(float(saved_ui.get("target_payout_usd", 1.00))); self.rr_box.setPrefix("$")
        self.min_rr_box = NoWheelDoubleSpinBox(); self.min_rr_box.setRange(0.5, 10); self.min_rr_box.setDecimals(2); self.min_rr_box.setValue(float(saved_ui.get("min_setup_rr", self.setup_engine.min_rr)))

        self.entry_price_box = self._price_spin()
        self.stop_price_box = self._price_spin()
        self.target_price_box = self._price_spin()
        self.plan_rr_label = QLabel("Plan RR --")
        self.plan_rr_label.setObjectName("Title")
        self.config_rr_label = QLabel("Configured RR 2.00:1 | risk $0.50 → payout $1.00")
        self.config_rr_label.setObjectName("Title")
        self.config_rr_label.setWordWrap(True)

        self._build_ui()
        self.seed_historical_candles()

        self.side_box.currentTextChanged.connect(self.rebuild_plan_from_inputs)
        self.size_box.valueChanged.connect(self.rebuild_plan_from_inputs)
        self.rr_box.valueChanged.connect(self.rebuild_plan_from_inputs)
        self.min_rr_box.valueChanged.connect(self.on_min_rr_changed)
        self.stop_box.valueChanged.connect(self.rebuild_plan_from_inputs)
        for _cash_box in (self.size_box, self.stop_box, self.rr_box):
            # valueChanged can wait until the spinbox commits text. textEdited makes
            # Ratio update while you type values like 0.50.
            _cash_box.lineEdit().textEdited.connect(self.on_cash_text_edited)
            _cash_box.editingFinished.connect(self.rebuild_plan_from_inputs)
        self.entry_price_box.valueChanged.connect(self.on_plan_inputs_changed)
        self.stop_price_box.valueChanged.connect(self.on_plan_inputs_changed)
        self.target_price_box.valueChanged.connect(self.on_plan_inputs_changed)
        self.mode_box.currentTextChanged.connect(self.on_mode_changed)
        self.training_speed_box.currentTextChanged.connect(self.on_training_speed_changed)
        self.auto_paper_toggle.stateChanged.connect(self.on_mode_changed)
        self._update_configured_rr_label()

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_timer)
        self.clock.start(250)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.process_latest_price)
        self.tick_timer.start(250)  # live but throttled enough to keep UI smooth

        self.update_stats()
        self.feed.start()
        self.logger.info("Quant Terminal started")


    def _trading_ui_settings_path(self) -> Path:
        return Path("config") / "paper_trading_ui.json"

    def _load_trading_ui_settings(self) -> dict:
        path = self._trading_ui_settings_path()
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save_trading_ui_settings(self) -> None:
        data = {
            "buy_in_usd": self._cash_size(),
            "stop_loss_usd": self._cash_stop_loss(),
            "target_payout_usd": self._cash_payout(),
            "min_setup_rr": float(self.min_rr_box.value()) if hasattr(self, "min_rr_box") else 2.0,
            "mode": self.mode_box.currentText() if hasattr(self, "mode_box") else "Paper Training (auto paper)",
            "training_speed": self.training_speed_box.currentText() if hasattr(self, "training_speed_box") else "More Trades",
            "auto_paper": bool(self.auto_paper_toggle.isChecked()) if hasattr(self, "auto_paper_toggle") else True,
        }
        path = self._trading_ui_settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.log(f"Saved paper settings: buy-in ${data['buy_in_usd']:.2f}, stop ${data['stop_loss_usd']:.2f}, payout ${data['target_payout_usd']:.2f}, min RR {data['min_setup_rr']:.2f}")

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
        root.setContentsMargins(8, 8, 8, 8); root.setSpacing(8)

        top = QFrame(); top.setObjectName("TopBar")
        top_l = QHBoxLayout(top); top_l.setContentsMargins(12, 8, 12, 8)
        title = QLabel("QUANT TERMINAL  •  BTC15 RESEARCH"); title.setObjectName("Brand")
        top_l.addWidget(title); top_l.addStretch(); top_l.addWidget(self.price_label)
        top_l.addSpacing(20); top_l.addWidget(self.timer_label); top_l.addSpacing(20); top_l.addWidget(self.move_label); top_l.addSpacing(20); top_l.addWidget(self.feed_label)
        root.addWidget(top)

        workspace = QSplitter(Qt.Horizontal)
        workspace.setChildrenCollapsible(False)
        workspace.setHandleWidth(7)

        left = self._panel("Navigator")
        left.setMinimumWidth(145); left.setMaximumWidth(320)
        self.watchlist = QListWidget(); self.watchlist.addItems(["Paper Trading", "Journal", "Signals", "Timeline", "Coach", "Learning", "Memory", "Backtests", "Data Health", "Kalshi", "Logs", "Settings"])
        self.watchlist.itemClicked.connect(self.on_watchlist_clicked)
        left.layout().addWidget(self.watchlist)
        workspace.addWidget(left)

        center = QSplitter(Qt.Vertical)
        center.setChildrenCollapsible(False)
        center.setHandleWidth(7)

        chart_panel = self._panel("Live BTC-USD Chart")
        chart_tools = QHBoxLayout(); chart_tools.setSpacing(6)
        zoom_out = QPushButton("−"); zoom_out.clicked.connect(self.chart.zoom_out)
        zoom_in = QPushButton("+"); zoom_in.clicked.connect(self.chart.zoom_in)
        reset_view = QPushButton("Fit"); reset_view.clicked.connect(self.chart.reset_view)
        chart_tools.addWidget(QLabel("Zoom")); chart_tools.addWidget(zoom_out); chart_tools.addWidget(zoom_in); chart_tools.addWidget(reset_view)
        clean_btn = QPushButton("Clean")
        clean_btn.clicked.connect(self.clean_chart_view)
        gap_btn = QPushButton("Filled gaps")
        gap_btn.clicked.connect(self.toggle_filled_gaps)
        swing_btn = QPushButton("H/L")
        swing_btn.clicked.connect(self.toggle_swing_labels)
        chart_tools.addSpacing(12); chart_tools.addWidget(clean_btn); chart_tools.addWidget(gap_btn); chart_tools.addWidget(swing_btn)
        chart_tools.addStretch(); chart_tools.addWidget(QLabel("v0.9.0 scalp mode • multi-trade BTC15 paper training"))
        chart_panel.layout().addLayout(chart_tools)
        chart_panel.layout().addWidget(self.chart, 1)
        center.addWidget(chart_panel)

        self.tabs = QTabWidget(); tabs = self.tabs
        paper = QWidget(); paper_l = QVBoxLayout(paper)
        paper_l.addWidget(self.stats_label)
        paper_l.addWidget(self.open_trade_label)
        paper_l.addWidget(self.trades_box, 1)
        audit_tab = QWidget(); audit_l = QVBoxLayout(audit_tab)
        audit_l.addWidget(QLabel("Paper Journal / Trade Audit — verifies wins by TARGET and losses by STOP"))
        audit_l.addWidget(self.audit_box, 1)
        logs = QWidget(); logs_l = QVBoxLayout(logs); logs_l.addWidget(self.log_box, 1)
        learning_tab = QWidget(); learning_l = QVBoxLayout(learning_tab)
        learning_l.addWidget(self.learning_toggle)
        learning_l.addWidget(self.learning_box, 1)
        memory_tab = QWidget(); memory_l = QVBoxLayout(memory_tab)
        memory_l.addWidget(QLabel("Memory Stats — similarity scoring + learned paper outcomes"))
        memory_l.addWidget(self.memory_stats_box, 1)
        tune_btn = QPushButton("Apply Safe Auto-Tune")
        tune_btn.clicked.connect(self.apply_auto_tune)
        memory_l.addWidget(tune_btn)
        memory_l.addWidget(self.auto_tune_box, 1)
        backtest_tab = QWidget(); backtest_l = QVBoxLayout(backtest_tab)
        run_backtest = QPushButton("Run FVG Replay Backtest")
        run_backtest.clicked.connect(self.run_replay_backtest)
        export_btn = QPushButton("Export Paper Report")
        export_btn.clicked.connect(self.export_paper_report)
        backtest_l.addWidget(run_backtest)
        backtest_l.addWidget(export_btn)
        backtest_l.addWidget(self.backtest_box, 1)
        signal_tab = QWidget(); signal_l = QVBoxLayout(signal_tab); signal_l.addWidget(self.signal_box, 1)
        timeline_tab = QWidget(); timeline_l = QVBoxLayout(timeline_tab)
        timeline_l.addWidget(QLabel("Signal Timeline — step-by-step reasoning trail for each setup"))
        timeline_l.addWidget(self.timeline_box, 1)
        coach_tab = QWidget(); coach_l = QVBoxLayout(coach_tab)
        coach_l.addWidget(QLabel("Logic Coach — confidence breakdown, safety rules, and setup state"))
        coach_l.addWidget(self.coach_box, 1)
        data_tab = QWidget(); data_l = QVBoxLayout(data_tab)
        data_l.addWidget(QLabel("Feed Accuracy / Data Health — warns if Coinbase, candles, Kalshi timer, or odds are stale"))
        data_l.addWidget(self.data_health_box, 1)
        kalshi_tab = QWidget(); kalshi_l = QVBoxLayout(kalshi_tab)
        apply_kalshi = QPushButton("Sync this Kalshi URL")
        apply_kalshi.clicked.connect(self.apply_kalshi_url)
        kalshi_l.addWidget(QLabel("Kalshi BTC15 URL — category page is best for live sync"))
        kalshi_l.addWidget(self.kalshi_url_box)
        kalshi_l.addWidget(apply_kalshi)
        kalshi_l.addWidget(self.kalshi_debug_box, 1)
        tabs.addTab(paper, "Paper Trading")
        tabs.addTab(audit_tab, "Paper Journal / Audit")
        tabs.addTab(signal_tab, "Signal Journal")
        tabs.addTab(timeline_tab, "Signal Timeline")
        tabs.addTab(coach_tab, "Logic Coach")
        tabs.addTab(learning_tab, "Learning")
        tabs.addTab(memory_tab, "Memory Stats")
        tabs.addTab(backtest_tab, "Backtest / Replay")
        tabs.addTab(data_tab, "Data Health")
        tabs.addTab(kalshi_tab, "Kalshi Debug")
        tabs.addTab(logs, "Logs")
        center.addWidget(tabs)
        center.setSizes([610, 240])
        workspace.addWidget(center)

        right = self._panel("AI / Thinking + Paper Controls")
        right.setMinimumWidth(330)
        right_split = QSplitter(Qt.Vertical)
        right_split.setChildrenCollapsible(False)
        right_split.setHandleWidth(7)
        decision_tabs = QTabWidget()
        decision_tabs.addTab(self.ai_box, "Decision")
        decision_tabs.addTab(self.thinking_box, "Checklist")
        decision_tabs.addTab(self.coach_box, "Coach")
        right_split.addWidget(decision_tabs)

        planner = QFrame(); planner.setObjectName("Panel")
        fl = QFormLayout(planner)
        fl.setContentsMargins(10, 10, 10, 10); fl.setSpacing(8)
        direction_label = QLabel("Direction: AUTO from chart")
        direction_label.setObjectName("Title")
        fl.addRow(direction_label)
        side_help = QLabel("UP/LONG = buy when chart favors up. DOWN/SHORT = sell when chart favors down. Bot pauses new reads while a trade is active.")
        side_help.setObjectName("Muted"); side_help.setWordWrap(True)
        fl.addRow(side_help)
        fl.addRow("Mode", self.mode_box)
        fl.addRow("Training speed", self.training_speed_box)
        fl.addRow("Buy-in USD", self.size_box)
        fl.addRow("Stop loss USD", self.stop_box)
        fl.addRow("Target payout USD", self.rr_box)
        fl.addRow("Min setup RR filter", self.min_rr_box)
        fl.addRow("Ratio", self.plan_rr_label)
        fl.addRow("Auto paper", self.auto_paper_toggle)
        save_settings_btn = QPushButton("Save paper settings")
        save_settings_btn.clicked.connect(self.save_trading_ui_settings)
        fl.addRow(save_settings_btn)
        note = QLabel("Each BTC15 starts a fresh read. More Trades waits a few candles; Max Data enters faster but labels probes separately.")
        note.setObjectName("Muted"); note.setWordWrap(True)
        fl.addRow(note)
        right_split.addWidget(planner)
        right_split.setSizes([620, 260])
        right.layout().addWidget(right_split)
        workspace.addWidget(right)
        workspace.setSizes([170, 960, 430])
        workspace.setStretchFactor(0, 0)
        workspace.setStretchFactor(1, 1)
        workspace.setStretchFactor(2, 0)
        root.addWidget(workspace, 1)
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
        src = getattr(self.feed, "last_source", "LIVE")
        self.feed_label.setText(f"● LIVE {src}")
        self.feed_label.setObjectName("Green")
        self.price_label.setText(f"BTC-USD: ${price:,.2f}")
        self.update_btc15_move(price)
        candles = self.candles.update_price(price)
        # Keep chart candle data current on every tick so the LIVE label and last candle
        # use the same price. Full FVG recalculation is still throttled below.
        if hasattr(self.chart, "candles"):
            self.chart.candles = candles[-800:]
        # Paper trade lifecycle lock:
        # the trade's own expires_at is the source of truth. Do NOT force-close
        # from a possibly stale Kalshi snapshot, because that caused open→instant
        # close flicker while the chart still had a plan overlay.
        before_trade = self.account.open_trade
        if before_trade and not before_trade.expires_at:
            before_trade.expires_at = self._safe_trade_expiry_ts()
        self.account.update(price)
        open_trade = self.account.open_trade
        if before_trade and not open_trade:
            self.log_timeline(f"EXIT {before_trade.exit_reason or 'CLOSED'} | Paper trade closed cleanly — waiting for new 15m read")
            # A real paper trade ended. Remove the active trade overlay immediately;
            # the strategy may later draw a separate PENDING plan, but it will not
            # look like an open trade.
            if str(self.chart.trade_plan.get("mode") or "") == "trade":
                self.chart.clear_plan(emit=False)
        if open_trade:
            risk_cash = float(open_trade.setup_meta.get("cash_stop_loss", self._cash_stop_loss())) if hasattr(open_trade, "setup_meta") else self._cash_stop_loss()
            payout_cash = float(open_trade.setup_meta.get("cash_payout", self._cash_payout())) if hasattr(open_trade, "setup_meta") else self._cash_payout()
            self.chart.set_cash_metrics(open_trade.size_usd, risk_cash, payout_cash)
            # Keep the chart in OPEN TRADE mode every tick so live payout/SHORT P&L
            # and the green/red zones cannot desync from the account state.
            self.chart.set_plan(open_trade.side, open_trade.entry, open_trade.stop, open_trade.target, active=True, mode="trade", emit=False)
        else:
            self.chart.set_cash_metrics(self._cash_size(), self._cash_stop_loss(), self._cash_payout())
            if str(self.chart.trade_plan.get("mode") or "") == "trade":
                self.chart.clear_plan(emit=False)
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

        try:
            snap_ctx = self.kalshi_timer.snapshot()
            self.setup_engine.configure_context(self._used_gap_keys, snap_ctx.seconds_left(), self._training_speed())
        except Exception:
            self.setup_engine.configure_context(self._used_gap_keys, None, self._training_speed())
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
        bucket = self._current_btc15_bucket()
        if self._last_15m_bucket != bucket or self._last_15m_open is None:
            self._last_15m_bucket = bucket
            # New Kalshi BTC15 window = fresh read. Clear per-window GAP locks so
            # the bot starts over instead of carrying old FVG decisions forward.
            self._used_gap_keys.clear()
            self._ready_confirm_sig = ""
            self._ready_confirm_count = 0
            self._ready_confirm_sig = ""
            self._auto_opened_signal_sig = ""
            self._planned_gap_key = ""
            self._last_auto_plan_sig = ""
            self._last_auto_log_sig = ""
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
            "Coach": 4,
            "Learning": 5,
            "Memory": 6,
            "Backtests": 7,
            "Data Health": 8,
            "Kalshi": 9,
            "Logs": 10,
            "Settings": 9,
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
        self.update_data_health_panel(snap)
        # Do NOT close an open paper trade from the live Kalshi snapshot here.
        # In prior builds a stale/expired Kalshi snapshot could say 00:00 right
        # after a trade opened, causing the "pop trade then disappear" bug.
        # Every paper trade now locks its own BTC15 expiry at entry time; that
        # locked timestamp is the only timer allowed to close it. This keeps the
        # chart overlay, Paper Trading tab, and account state in sync.
        t = self.account.open_trade
        if self.latest_price is not None and t and t.expires_at and time.time() >= float(t.expires_at):
            self.account.update(float(self.latest_price), force_close=True, force_reason="LOCKED_BTC15_END")
            self.capture_closed_trades_for_learning()
            if str(self.chart.trade_plan.get("mode") or "") == "trade" and not self.account.open_trade:
                self.chart.clear_plan(emit=False)
            self.update_stats()

    def _decision_signature(self, d) -> str:
        if not d:
            return "none"
        plan = getattr(d, "plan", None)
        plan_sig = ""
        if plan:
            plan_sig = f"{plan.side}:{plan.entry:.2f}:{plan.stop:.2f}:{plan.target:.2f}"
        return "|".join([
            str(getattr(d, "state", "UNKNOWN")),
            str(getattr(d, "ready", False)),
            str(getattr(d, "side", "WAIT")),
            str(getattr(d, "grade", "")),
            str(getattr(d, "confidence", 0)),
            str(getattr(d, "latest_fvg", "")),
            plan_sig,
            ";".join(getattr(d, "reasons", [])[-3:]),
        ])

    def _auto_entry_key(self, d, gap_key: str = "") -> str:
        """Stable key for auto-entry waits.

        Do NOT include live entry/stop/target price here. Those change every tick,
        which was resetting the read-confirmation counter and creating lots of
        AUTO PLAN READY logs with zero paper entries.
        """
        if not d:
            return "none"
        key = gap_key or str(getattr(d, "active_fvg_key", "")) or str(getattr(d, "setup_signature", ""))
        side = str(getattr(d, "side", "WAIT"))
        grade = str(getattr(d, "grade", ""))
        model = str(getattr(d, "entry_model", ""))[:24]
        bucket = self._current_btc15_bucket() if hasattr(self, "_current_btc15_bucket") else 0
        return f"{bucket}|{key}|{side}|{grade}|{model}"

    def _entry_block(self, reason: str) -> None:
        """Log auto-entry blockers without spamming the timeline every tick."""
        if reason != getattr(self, "_last_entry_block_reason", ""):
            self._last_entry_block_reason = reason
            self.log_timeline(reason)

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

        self._update_configured_rr_label()
        configured_cash_line = self._configured_cash_summary()
        display_plan = self._current_display_plan(d)
        if d.ready and display_plan:
            side, entry, stop, target, rr = display_plan
            cash_line = self._plan_cash_summary(side, entry, stop, target)
            plan_note = (
                f"VALID {side} SETUP\n"
                f"Planned buy-in  {entry:,.2f}\n"
                f"Planned stop    {stop:,.2f}\n"
                f"Planned target  {target:,.2f}\n"
                f"Cash math       {cash_line}\n"
                f"Reason {getattr(d.plan, 'reason', 'Configured paper plan')}"
            )
        else:
            plan_note = "No buy-in yet. Waiting for the state machine to reach READY."

        checklist = "\n".join(d.checklist[-10:]) if d.checklist else "Building candle context..."
        reasons = "\n".join("• " + r for r in d.reasons[-8:]) if d.reasons else "• Monitoring"
        breakdown = "\n".join(getattr(d, "confidence_breakdown", [])[-10:]) or "No score yet"
        safety = "\n".join(getattr(d, "safety_checks", [])[-8:]) or "Safety checks pending"
        sim = self.learning.similarity(d)
        sim_text = f"{sim['matches']} matches | {sim['win_rate']:.1f}% WR | avg ${sim['avg_pnl']:.2f} | score {sim['score']}/100 | {sim['label']}"
        edge_text = self._edge_filter_summary(d)
        contract_text = self._kalshi_contract_summary(getattr(d, "side", ""))
        recommend_line = ""
        if hasattr(self, "mode_box") and self.mode_box.currentText().startswith("Recommend") and d.ready:
            recommend_line = f"\nRecommend Only: alert this setup, do not auto-paper. Suggested cash plan = {configured_cash_line}."

        ai_text = (
            f"FVG Logic Engine v0.8.2\n\n"
            f"State\n{getattr(d, 'state', 'UNKNOWN')}\n\n"
            f"Decision\n{('READY ' + d.side) if d.ready else 'WAIT'}\n\n"
            f"Grade / Confidence\n{d.grade} / {d.confidence}%\n\n"
            f"Confidence Breakdown\n{breakdown}\n\n"
            f"15m Trend\n{d.trend_15m}\n\n"
            f"5m Trend\n{d.trend_5m}\n\n"
            f"Entry Model\n{getattr(d, 'entry_model', 'FVG')}\n\n"
            f"Latest Candle Read\n{', '.join(getattr(d, 'candlestick_patterns', [])[:4]) or 'No candle pattern yet'}\n\n"
            f"Training Speed\n{self._training_speed()}\n\n"
            f"Kalshi Odds Context\n{contract_text}\n\n"
            f"Edge Filter\n{edge_text}\n\n"
            f"5m Bias\n{getattr(d, 'higher_tf_bias', 'WAIT')}\n\n"
            f"Trigger Quality\n{getattr(d, 'trigger_quality', 'Waiting')} {'(paper probe)' if getattr(d, 'training_probe', False) else ''}\n\n"
            f"Session\n{getattr(d, 'session_label', 'Unknown')}\n\n"
            f"Focused GAP\n{d.latest_fvg}\n\n"
            f"Similarity Memory\n{sim_text}\n\n"
            f"Checklist\n{checklist}\n\n"
            f"Safety Rules\n{safety}\n\n"
            f"Configured Cash RR\n{configured_cash_line}\n\n"
            f"Auto Plan\n{plan_note}{recommend_line}\n\n"
            f"Why Waiting / Why Ready\n{reasons}\n\n"
            f"Hard Rule\nNo buy-in unless state = READY. In Paper Training, B-grade probes and optional scout probes are labeled so the bot can collect learning data."
        )
        self._set_text_stable(self.ai_box, ai_text, "_last_ai_text")
        self.update_thinking_panel(d)
        self.update_coach_panel(d)

    def update_thinking_panel(self, d) -> None:
        snap = self.kalshi_timer.snapshot()
        timer_line = f"Kalshi BTC15: {snap.label()} ({snap.source})"
        if snap.ticker:
            timer_line += f"\nMarket: {snap.ticker}"
        if snap.last_error and snap.source != "KALSHI":
            timer_line += f"\nTimer note: {snap.last_error}"

        checklist = d.checklist or ["❌ Still building candle context"]
        reasons = d.reasons or ["Monitoring live BTC candles"]
        breakdown = getattr(d, "confidence_breakdown", []) or ["No score yet"]
        safety = getattr(d, "safety_checks", []) or ["Safety checks pending"]
        sim = self.learning.similarity(d)
        edge_text = self._edge_filter_summary(d)
        contract_text = self._kalshi_contract_summary(getattr(d, "side", ""))
        self._update_configured_rr_label()
        configured_cash_line = self._configured_cash_summary()
        plan = "No buy-in yet"
        display_plan = self._current_display_plan(d)
        if d.ready and display_plan:
            side, entry, stop, target, rr = display_plan
            plan = (
                f"{side} AUTO PLAN READY\n"
                f"Planned buy-in: {entry:,.2f}\n"
                f"Planned stop:   {stop:,.2f}\n"
                f"Planned target: {target:,.2f}\n"
                f"Cash math:      {self._plan_cash_summary(side, entry, stop, target)}"
            )
        text = (
            "FVG Method State Machine\n\n"
            f"{timer_line}\n\n"
            f"Current State: {getattr(d, 'state', 'UNKNOWN')}\n"
            f"Entry Model: {getattr(d, 'entry_model', 'FVG')}\n"
            f"Kalshi Odds Context: {contract_text}\n"
            f"5m Bias: {getattr(d, 'higher_tf_bias', 'WAIT')} | Trigger: {getattr(d, 'trigger_quality', 'Waiting')}\n"
            f"Latest Candle Read: {', '.join(getattr(d, 'candlestick_patterns', [])[:4]) or 'No pattern yet'}\n"
            f"Sequence: {getattr(d, 'trigger_sequence', 'Waiting')}\n"
            f"Setup Signature: {getattr(d, 'setup_signature', '') or 'None yet'}\n\n"
            "Question Process\n"
            "1. Do we have enough 1m candles?\n"
            "2. What is the 5m bias / 15m context?\n"
            "3. Did 1m print an execution FVG/GAP?\n"
            "4. Did price pull back into or near the GAP?\n"
            "5. Did Sweep → CHoCH → displacement print?\n"
            "6. Does cash RR pass your filter?\n"
            "7. Do safety rules allow a paper trade?\n\n"
            "Live Checklist\n" + "\n".join(checklist[-12:]) + "\n\n"
            "Confidence Breakdown\n" + "\n".join(breakdown[-12:]) + "\n\n"
            "Safety\n" + "\n".join(safety[-10:]) + "\n\n"
            "Memory / Edge Filter\n"
            f"{sim['matches']} similar | WR {sim['win_rate']:.1f}% | score {sim['score']}/100 | {sim['label']}\n"
            f"{edge_text}\n\n"
            "Configured Cash RR\n" + configured_cash_line + "\n\n"
            "Why waiting / why ready\n" + "\n".join("• " + r for r in reasons[-8:]) + "\n\n"
            "Trade Plan\n" + plan
        )
        self._set_text_stable(self.thinking_box, text, "_last_thinking_text")

    def update_coach_panel(self, d) -> None:
        if not hasattr(self, "coach_box"):
            return
        sim = self.learning.similarity(d) if d else {"matches": 0, "win_rate": 0, "avg_pnl": 0, "score": 0, "label": "No setup"}
        edge_text = self._edge_filter_summary(d) if d else "Edge filter waiting for setup"
        contract_text = self._kalshi_contract_summary(getattr(d, "side", "") if d else "")
        clusters = self.learning.clusters(limit=6) if hasattr(self.learning, "clusters") else []
        cluster_text = "\n".join(
            f"• {c['cluster']} | {c['trades']} trades | WR {c['win_rate']:.1f}% | avg ${c['avg_pnl']:.2f}"
            for c in clusters
        ) or "No clusters yet. Run Paper Training to build them."
        text = (
            "Logic Coach\n\n"
            "This is the part that makes the bot a chart reader, not a random signal spammer.\n\n"
            f"State: {getattr(d, 'state', 'UNKNOWN')}\n"
            f"Direction: {getattr(d, 'side', 'WAIT')}\n"
            f"Grade: {getattr(d, 'grade', 'WAIT')}\n"
            f"Confidence: {getattr(d, 'confidence', 0)}%\n"
            f"Session: {getattr(d, 'session_label', 'Unknown')}\n"
            f"Entry Model: {getattr(d, 'entry_model', 'FVG')}\n"
            f"Kalshi Odds Context: {contract_text}\n"
            f"5m Bias: {getattr(d, 'higher_tf_bias', 'WAIT')} | Trigger: {getattr(d, 'trigger_quality', 'Waiting')}\n"
            f"Latest Candle Read: {', '.join(getattr(d, 'candlestick_patterns', [])[:4]) or 'No pattern yet'}\n"
            f"Sequence: {getattr(d, 'trigger_sequence', 'Waiting')}\n"
            f"Focused GAP: {getattr(d, 'latest_fvg', 'None')}\n\n"
            "What must happen next\n"
        )
        state = getattr(d, 'state', 'UNKNOWN')
        if state == "SCANNING":
            text += "Scanning for aligned trend, fresh GAP, and enough BTC15 time. No trade yet.\n"
        elif state == "FOUND_GAP":
            text += "A focused GAP exists. It must stay valid and pull back cleanly.\n"
        elif state == "WAIT_PULLBACK":
            text += "Wait for price to return into the focused GAP. No chasing.\n"
        elif state == "WAIT_CONFIRMATION":
            text += "Wait for engulfing or rejection confirmation after the pullback.\n"
        elif state == "READY_CHECK":
            text += "Checking cash RR and safety rules before allowing a setup.\n"
        elif state == "READY":
            text += "Setup is valid. Paper Training may open automatically; Recommend Only will alert only. B-grade probes are clearly labeled.\n"
        else:
            text += "Monitoring.\n"
        text += (
            "\nMemory Similarity\n"
            f"Matches: {sim['matches']} | Similar WR: {sim['win_rate']:.1f}% | Avg P/L: ${sim['avg_pnl']:.2f} | Score: {sim['score']}/100 | {sim['label']}\n\n"
            "Best Learned Clusters\n" + cluster_text + "\n\n"
            "Safety Guardrails\n"
            "• One open trade max.\n"
            "• One plan per GAP.\n"
            "• No buy-in until READY.\n"
            "• BTC15 expiry closes paper trades.\n"
            "• Auto-tune only changes thresholds after enough paper outcomes.\n"
        )
        self._set_text_stable(self.coach_box, text, "_last_coach_text")

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


    def on_min_rr_changed(self) -> None:
        """User/auto-tune control for the strategy minimum RR filter.

        This is intentionally separate from Target RR. Target RR controls the
        visible paper plan target. Min setup RR controls whether the setup is
        good enough for the bot to consider.
        """
        if self._syncing_plan:
            return
        self.setup_engine.min_rr = float(self.min_rr_box.value())
        self.log(f"Minimum setup RR filter set to {self.setup_engine.min_rr:.2f}:1")
        if self.last_decision and not self.account.open_trade:
            self._last_auto_plan_sig = ""
            self._last_auto_log_sig = ""



    def _training_speed(self) -> str:
        return self.training_speed_box.currentText() if hasattr(self, "training_speed_box") else "More Trades"

    def on_training_speed_changed(self) -> None:
        speed = self._training_speed()
        try:
            self.setup_engine.training_speed = speed
            self.setup_engine._apply_training_speed()
        except Exception:
            pass
        self._last_auto_plan_sig = ""
        self._last_auto_log_sig = ""
        self.log(f"Training speed set: {speed}")
        if self.latest_price is not None and not self.account.open_trade:
            self.update_ai(float(self.latest_price))

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

    def _spin_live_value(self, box, fallback: float = 0.01, minimum: float = 0.01) -> float:
        """Read a QDoubleSpinBox while the user is still typing.

        QDoubleSpinBox.value() may not update until Enter/focus-loss for text like
        `0.50`. This parser lets the Ratio label and chart plan update instantly.
        """
        try:
            raw = box.lineEdit().text()
        except Exception:
            raw = str(getattr(box, "text", lambda: "")())
        cleaned = ""
        dot_seen = False
        for ch in raw:
            if ch.isdigit():
                cleaned += ch
            elif ch == "." and not dot_seen:
                cleaned += ch
                dot_seen = True
        if cleaned in ("", "."):
            try:
                val = float(box.value())
            except Exception:
                val = fallback
        else:
            try:
                val = float(cleaned)
            except Exception:
                val = fallback
        return max(float(val), float(minimum))

    def _cash_size(self) -> float:
        return self._spin_live_value(self.size_box, 20.0, 0.01) if hasattr(self, "size_box") else 1.0

    def _cash_stop_loss(self) -> float:
        return self._spin_live_value(self.stop_box, 0.50, 0.01) if hasattr(self, "stop_box") else 0.01

    def _cash_payout(self) -> float:
        return self._spin_live_value(self.rr_box, 1.00, 0.01) if hasattr(self, "rr_box") else 0.01

    def on_cash_text_edited(self, _text: str = "") -> None:
        # Instant UI response while typing in Buy-in / Stop loss / Target payout.
        self._update_ratio_label()
        if self._syncing_plan:
            return
        self.rebuild_plan_from_inputs()

    def _configured_cash_metrics(self) -> dict:
        """Cash-only RR math that always works, even before a chart setup exists."""
        size = self._cash_size()
        stop_loss = self._cash_stop_loss()
        payout = self._cash_payout()
        rr = payout / max(stop_loss, 0.01)
        return {
            "size": size,
            "stop_loss": stop_loss,
            "payout": payout,
            "rr": rr,
            "stop_pct": (stop_loss / size * 100.0) if size else 0.0,
            "payout_pct": (payout / size * 100.0) if size else 0.0,
        }

    def _configured_cash_summary(self) -> str:
        m = self._configured_cash_metrics()
        return (
            f"RR {m['rr']:.2f}:1 | buy-in ${m['size']:,.2f} | "
            f"risk ${m['stop_loss']:,.2f} | payout ${m['payout']:,.2f} | "
            f"moves {m['stop_pct']:.3f}% / {m['payout_pct']:.3f}%"
        )


    def _kalshi_contract_summary(self, side: str | None = None) -> str:
        snap = self.kalshi_timer.snapshot()
        base = snap.price_line() if hasattr(snap, "price_line") else "contract prices unavailable"
        spread = snap.spread_cents() if hasattr(snap, "spread_cents") else None
        quality = "unknown"
        if spread is not None:
            quality = "good" if spread <= 4 else ("ok" if spread <= 8 else "wide")
        side_price = None
        if side and hasattr(snap, "side_entry_cents"):
            side_price = snap.side_entry_cents(side)
        side_txt = ""
        if side_price is not None:
            side_txt = f" | estimated {side} entry {side_price}¢"
        vol_txt = ""
        if getattr(snap, "volume", None) is not None:
            vol_txt += f" | vol {snap.volume}"
        if getattr(snap, "liquidity", None) is not None:
            vol_txt += f" | liq {snap.liquidity}"
        return f"{base}{side_txt}{vol_txt} | spread quality {quality}"

    def _edge_filter_summary(self, d=None) -> str:
        try:
            edge = self.learning.edge_profile(d)
            blocked = "BLOCK" if edge.get("blocked") else "PASS"
            sim = edge.get("similarity", {}) or {}
            return (
                f"Edge filter: {blocked}\n"
                f"Decision cluster: {edge.get('decision_cluster') or 'None yet'}\n"
                f"Similar memory: {sim.get('matches',0)} matches | WR {float(sim.get('win_rate',0)):.1f}% | "
                f"avg ${float(sim.get('avg_pnl',0)):.2f} | score {int(sim.get('score',0))}/100\n"
                f"Block reason: {edge.get('block_reason') or 'None'}"
            )
        except Exception as exc:
            return f"Edge filter unavailable: {exc}"

    def _update_ratio_label(self, side: str | None = None, entry: float | None = None, stop: float | None = None, target: float | None = None) -> None:
        if not hasattr(self, "plan_rr_label"):
            return
        if side and entry and stop and target and entry > 1 and stop > 1 and target > 1:
            text = self._plan_cash_summary(side, entry, stop, target)
        else:
            text = self._configured_cash_summary()
        self.plan_rr_label.setText(text)

    def _update_configured_rr_label(self) -> None:
        # Kept for internal calls, but the visible UI now uses only the Ratio row.
        m = self._configured_cash_metrics()
        if hasattr(self, "config_rr_label"):
            self.config_rr_label.setText(
                f"RR {m['rr']:.2f}:1  |  risk ${m['stop_loss']:.2f} → payout ${m['payout']:.2f}  |  buy-in ${m['size']:.2f}"
            )
        self._update_ratio_label()

    def _cash_metrics_from_prices(self, side: str, entry: float, stop: float, target: float) -> dict:
        """Translate chart price lines into the small-dollar plan the user sees.

        Example: buy-in $20, stop loss $0.50, payout $1.00 means RR = 2.00.
        The chart still needs BTC price levels, so the conversion uses the paper
        account's spot-style P/L formula: price move % * buy-in size.
        """
        size = self._cash_size() if hasattr(self, "size_box") else 1.0
        entry = max(float(entry), 0.01)
        stop = float(stop)
        target = float(target)
        if str(side).upper() == "LONG":
            stop_loss = max(0.0, (entry - stop) / entry * size)
            payout = max(0.0, (target - entry) / entry * size)
        else:
            stop_loss = max(0.0, (stop - entry) / entry * size)
            payout = max(0.0, (entry - target) / entry * size)
        rr = payout / max(stop_loss, 0.01)
        return {
            "size": size,
            "stop_loss": stop_loss,
            "payout": payout,
            "rr": rr,
            "stop_pct": (stop_loss / size * 100.0) if size else 0.0,
            "payout_pct": (payout / size * 100.0) if size else 0.0,
        }

    def _plan_cash_summary(self, side: str, entry: float, stop: float, target: float) -> str:
        # The visible cash plan is user-configured, not derived from spot % move.
        # Stop/target chart lines decide pass/fail; this cash line decides the paper payout scale.
        m = self._configured_cash_metrics()
        entry = max(float(entry), 0.01)
        if str(side).upper() == "LONG":
            stop_pct = max(0.0, (entry - float(stop)) / entry * 100.0)
            target_pct = max(0.0, (float(target) - entry) / entry * 100.0)
        else:
            stop_pct = max(0.0, (float(stop) - entry) / entry * 100.0)
            target_pct = max(0.0, (entry - float(target)) / entry * 100.0)
        return (
            f"RR {m['rr']:.2f}:1 | buy-in ${m['size']:,.2f} | "
            f"risk ${m['stop_loss']:,.2f} | payout ${m['payout']:,.2f} | "
            f"chart move stop {stop_pct:.3f}% / target {target_pct:.3f}%"
        )

    def _update_plan_rr_label(self, side: str, entry: float, stop: float, target: float) -> None:
        if hasattr(self, "config_rr_label"):
            m = self._configured_cash_metrics()
            self.config_rr_label.setText(
                f"RR {m['rr']:.2f}:1  |  risk ${m['stop_loss']:.2f} → payout ${m['payout']:.2f}  |  buy-in ${m['size']:.2f}"
            )
        self._update_ratio_label(side, entry, stop, target)

    def _recent_price_risk_distance(self, entry: float, planned_stop: float | None = None) -> float:
        """Pick a visible, tradeable BTC stop distance for the current 15m window.

        Cash risk/payout are controlled separately by Stop loss USD / Target payout
        USD. Chart stop/target levels should be close enough to monitor inside a
        BTC15 trade, not thousands of dollars away because of a $20 buy-in.
        """
        entry = max(float(entry), 0.01)
        ranges = []
        try:
            recent = self.candles.candles[-14:]
            ranges = [abs(c.high - c.low) for c in recent if c.high > c.low]
        except Exception:
            ranges = []
        avg_range = sum(ranges) / len(ranges) if ranges else entry * 0.001
        base = max(avg_range * 1.25, entry * 0.00075, 18.0)
        if planned_stop and planned_stop > 1:
            base = max(base, abs(entry - float(planned_stop)) * 0.55)
        # Clamp so levels are visible and realistic for a 15m scout.
        return max(entry * 0.00065, min(base, entry * 0.0045))

    def _configured_plan_values(self, d):
        """Apply user cash controls to a compact BTC15 chart plan.

        The strategy decides WHEN and DIRECTION. The side panel decides cash
        buy-in, cash stop, and cash payout. The chart lines use recent BTC
        volatility so stop/target can be watched inside the 15m window. Live P/L
        is then scaled to the cash stop/payout values.
        """
        if not d or not getattr(d, "plan", None):
            return None
        side = d.plan.side
        entry = float(d.plan.entry)
        cash_rr = self._cash_payout() / max(self._cash_stop_loss(), 0.01)
        base_risk = self._recent_price_risk_distance(entry, getattr(d.plan, "stop", None))
        reward = max(base_risk * cash_rr, entry * 0.00025)
        if side == "LONG":
            stop = max(0.01, entry - base_risk)
            target = entry + reward
        else:
            stop = entry + base_risk
            target = max(0.01, entry - reward)
        return side, entry, stop, target, cash_rr

    def _current_display_plan(self, d=None):
        """Prefer the visible chart plan; otherwise build one from the current setup."""
        plan = getattr(self.chart, "trade_plan", {}) if hasattr(self, "chart") else {}
        if plan.get("active") and all(isinstance(plan.get(k), (int, float)) for k in ("entry", "stop", "target")):
            side = str(plan.get("side", "LONG"))
            entry = float(plan["entry"]); stop = float(plan["stop"]); target = float(plan["target"])
            rr = self._configured_cash_metrics()["rr"]
            return side, entry, stop, target, rr
        return self._configured_plan_values(d)


    def _trade_manager_state(self, trade, price: float) -> str:
        snap = self.kalshi_timer.snapshot()
        seconds_left = snap.seconds_left()
        if trade.side == "LONG":
            target_dist = max(0.0, trade.target - price)
            stop_dist = max(0.0, price - trade.stop)
            progress = (price - trade.entry) / max(trade.target - trade.entry, 0.0001)
        else:
            target_dist = max(0.0, price - trade.target)
            stop_dist = max(0.0, trade.stop - price)
            progress = (trade.entry - price) / max(trade.entry - trade.target, 0.0001)
        total = max(target_dist + stop_dist, 0.0001)
        danger = stop_dist / total
        notes = []
        if seconds_left < 30:
            notes.append("EXPIRY SOON — BTC15 close will force exit")
        elif seconds_left < 75:
            notes.append("TIME WARNING — be picky; market ends soon")
        if progress >= 0.80:
            notes.append("NEAR FULL PAYOUT — target almost hit")
        elif progress >= 0.50:
            notes.append("GREEN HALF WAY — breakeven idea is reasonable in real coach mode")
        if danger < 0.20:
            notes.append("DANGER — price is close to stop")
        if not notes:
            notes.append("HOLD / WATCH — no new trades while active")
        return " | ".join(notes)

    def _live_payout_line(self, trade) -> str:
        try:
            target_cash = float(trade.setup_meta.get("cash_payout", self._cash_payout()))
            risk_cash = float(trade.setup_meta.get("cash_stop_loss", self._cash_stop_loss()))
        except Exception:
            target_cash = self._cash_payout(); risk_cash = self._cash_stop_loss()
        pnl = float(getattr(trade, "pnl", 0.0))
        green_pct = max(0.0, min(100.0, pnl / max(target_cash, 0.01) * 100.0))
        red_pct = max(0.0, min(100.0, abs(min(0.0, pnl)) / max(risk_cash, 0.01) * 100.0))
        return f"Live payout ${pnl:,.2f} / +${target_cash:,.2f} target | risk -${risk_cash:,.2f} | target {green_pct:.0f}% / stop {red_pct:.0f}%"

    def _data_freshness_text(self) -> str:
        now = time.time()
        tick_at = float(getattr(self.feed, "last_tick_at", 0.0) or 0.0)
        tick_age = now - tick_at if tick_at else 9999.0
        last_c = self.candles.candles[-1] if self.candles.candles else None
        candle_age = now - float(last_c.ts) if last_c else 9999.0
        source = str(getattr(self.feed, "last_source", "UNKNOWN"))
        warnings = []
        if source == "SIM":
            warnings.append("SIM FEED ACTIVE — not accurate; Coinbase feed failed")
        if tick_age > 5:
            warnings.append(f"Live price stale: {tick_age:.1f}s since last tick")
        if candle_age > 90:
            warnings.append(f"Last 1m candle bucket is old: {candle_age:.1f}s")
        if self.latest_price and last_c and abs(float(self.latest_price) - float(last_c.close)) > max(5.0, float(self.latest_price) * 0.001):
            warnings.append("Live price and last candle close are drifting")
        return "\n".join("⚠ " + w for w in warnings) if warnings else "✅ Data fresh enough for paper training"

    def update_data_health_panel(self, snap=None) -> None:
        if not hasattr(self, "data_health_box"):
            return
        snap = snap or self.kalshi_timer.snapshot()
        now = time.time()
        tick_at = float(getattr(self.feed, "last_tick_at", 0.0) or 0.0)
        tick_age = now - tick_at if tick_at else 9999.0
        last_c = self.candles.candles[-1] if self.candles.candles else None
        candle_age = now - float(last_c.ts) if last_c else 9999.0
        source = str(getattr(self.feed, "last_source", "UNKNOWN"))
        kalshi_age = now - float(getattr(snap, "updated_at", 0.0) or 0.0) if getattr(snap, "updated_at", 0.0) else 9999.0
        text = (
            "Feed Accuracy / Data Health\n\n"
            "Candle source: Coinbase Exchange BTC-USD 1m OHLC\n"
            "Live tick source: Coinbase WebSocket first, Coinbase REST fallback, SIM only if both fail\n"
            f"Current feed source: {source}\n"
            f"Last live tick age: {tick_age:.1f}s\n"
            f"Latest BTC-USD price: ${float(self.latest_price or 0):,.2f}\n"
            f"1m candles loaded: {len(self.candles.candles)}\n"
            f"Last candle age: {candle_age:.1f}s\n"
        )
        if last_c:
            direction = "UP/GREEN" if last_c.close >= last_c.open else "DOWN/RED"
            text += (
                f"Last candle: {direction} | O {last_c.open:,.2f} H {last_c.high:,.2f} L {last_c.low:,.2f} C {last_c.close:,.2f}\n"
                "Candle accuracy rule: green if close >= open; red if close < open. Hover any candle for OHLC + pattern read.\n"
            )
        text += (
            "\nKalshi BTC15 context\n"
            f"Timer source: {snap.source}\n"
            f"Ticker: {snap.ticker or 'None'}\n"
            f"Time left: {snap.seconds_left()//60:02d}:{snap.seconds_left()%60:02d}\n"
            f"Kalshi odds age: {kalshi_age:.1f}s\n"
            f"Odds: {snap.price_line() if hasattr(snap, 'price_line') else 'unavailable'}\n"
            f"Last Kalshi error: {snap.last_error or 'None'}\n\n"
            "Health check\n"
            f"{self._data_freshness_text()}\n\n"
            "Accuracy note: chart reading uses Coinbase BTC-USD candles; Kalshi odds/context is layered on top for payout realism."
        )
        self._set_text_stable(self.data_health_box, text, "_last_data_health_text")

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
        cash_line = self._plan_cash_summary(t.side, t.entry, t.stop, t.target)
        text = (
            "ACTIVE PAPER TRADE — WATCHING\n\n"
            "The bot is NOT hunting for a new setup while this trade is open.\n\n"
            f"Direction: {direction}\n"
            f"Buy-in size: ${t.size_usd:,.2f}\n"
            f"Entry:  {t.entry:,.2f}\n"
            f"Now:    {price:,.2f}\n"
            f"Stop:   {t.stop:,.2f}\n"
            f"Target: {t.target:,.2f}\n"
            f"{self._live_payout_line(t)}\n"
            f"MFE / MAE: ${getattr(t, 'mfe', 0.0):,.2f} / ${getattr(t, 'mae', 0.0):,.2f}\n"
            f"Lifecycle: {' | '.join(getattr(t, 'manager_notes', [])[-3:])}\n"
            f"Kalshi odds: {self._kalshi_contract_summary(t.side)}\n"
            f"BTC15 expires: {snap.label()}\n\n"
            f"Distance to target: {dist_target:,.2f}\n"
            f"Distance to stop:   {dist_stop:,.2f}\n\n"
            f"Manager state: {self._trade_manager_state(t, price)}\n\n"
            "Exit rules:\n"
            "• Target hit = win.\n"
            "• Stop hit = loss.\n"
            "• BTC15 timer ends = close trade at current price.\n"
            "• v0.8 manager labels danger / breakeven idea / near-payout, but does not fake-close early."
        )
        self._set_text_stable(self.ai_box, text, "_last_ai_text")
        self._set_text_stable(self.thinking_box, text, "_last_thinking_text")
        if hasattr(self, "coach_box"):
            self._set_text_stable(self.coach_box, text + "\n\nState: ACTIVE_TRADE. Logic engine is paused until this trade closes.", "_last_coach_text")

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

        # Learned edge filter: after enough paper results, automatically block setup families
        # that keep losing. Max Training Data can still collect scout samples.
        blocked, block_reason = self.learning.should_block_decision(d) if hasattr(self.learning, "should_block_decision") else (False, "")
        if blocked and not self._training_speed().startswith("Max"):
            if self.chart.trade_plan.get("active"):
                self.chart.clear_plan()
            self.log_timeline(f"BLOCK | Learned bad setup family | {block_reason}")
            if log_sig := f"BLOCK:{gap_key}:{block_reason}":
                if log_sig != self._last_auto_log_sig:
                    self._last_auto_log_sig = log_sig
                    self.log_signal(f"BLOCKED SETUP | {block_reason}")
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
        visual_sig = f"{gap_key}:{side}:{entry:.2f}:{stop:.2f}:{target:.2f}:{self._cash_size():.2f}:{self._cash_stop_loss():.2f}:{self._cash_payout():.2f}"
        self.side_box.setCurrentText(side)
        if visual_sig != self._last_auto_plan_sig:
            self.chart.set_plan(side, entry, stop, target, active=True, mode="plan", emit=False)
            self._update_plan_rr_label(side, entry, stop, target)
            self._last_auto_plan_sig = visual_sig
            self._planned_gap_key = gap_key

        log_sig = f"{gap_key}:{side}:{round(stop/25)*25:.0f}:{round(target/25)*25:.0f}:{d.grade}:{d.confidence//5*5}:{self._cash_size():.2f}:{self._cash_stop_loss():.2f}:{self._cash_payout():.2f}"
        if log_sig != self._last_auto_log_sig:
            self._last_auto_log_sig = log_sig
            self.log_signal(
                f"AUTO PLAN READY {side} | GAP {gap_key or 'unknown'} | buy-in {entry:,.2f} | stop {stop:,.2f} | "
                f"target {target:,.2f} | risk ${self._cash_stop_loss():.2f} | payout ${self._cash_payout():.2f} | RR {user_rr:.2f}:1 | confidence {d.confidence}% | grade {d.grade}"
            )
            self.log_timeline(
                f"READY {side} | GAP {gap_key or 'unknown'} | Trend {d.trend_15m}/{d.trend_5m} | FVG {d.latest_fvg} | "
                f"Buy-in {entry:,.2f} Stop {stop:,.2f} Target {target:,.2f}"
            )
        training_mode = hasattr(self, "mode_box") and self.mode_box.currentText().startswith("Paper Training")
        entry_key = self._auto_entry_key(d, gap_key)
        if training_mode and self.auto_paper_toggle.isChecked() and not self.account.open_trade and entry_key != self._auto_opened_signal_sig:
            bucket = self._current_btc15_bucket()
            max_trades = self._max_trades_per_window()
            current_count = self._window_trade_count(bucket)
            if current_count >= max_trades:
                self._entry_block(f"WAIT | BTC15 trade cap reached {current_count}/{max_trades}; fresh read next window")
                return
            cooldown_left = self._trade_cooldown_seconds() - int(time.time() - float(getattr(self, "_last_trade_open_ts", 0.0) or 0.0))
            if current_count > 0 and cooldown_left > 0:
                self._entry_block(f"WAIT | scalp cooldown {cooldown_left}s before next paper entry")
                return
            if self._safe_seconds_left() < max(10, int(getattr(self.setup_engine, "min_seconds_left", 18))):
                self._entry_block("WAIT | BTC15 too close to close; fresh read next window")
                return
            ok_to_open, wait_reason = self._ready_has_waited_enough(entry_key)
            if not ok_to_open:
                if wait_reason != self._last_timeline_state:
                    self._last_timeline_state = wait_reason
                    self.log_timeline(f"READ | {wait_reason}")
                return
            opened = self.open_planned_trade()
            if opened:
                self._auto_opened_signal_sig = entry_key
                self._last_entry_block_reason = ""

    def on_chart_plan_changed(self, plan: dict) -> None:
        self._syncing_plan = True
        try:
            if plan.get("side") in ["LONG", "SHORT"]:
                self.side_box.setCurrentText(str(plan["side"]))
            for key, box in [("entry", self.entry_price_box), ("stop", self.stop_price_box), ("target", self.target_price_box)]:
                val = plan.get(key)
                if isinstance(val, (int, float)):
                    box.setValue(float(val))
            side = str(plan.get("side", self.side_box.currentText()))
            entry = float(plan.get("entry") or 0)
            stop = float(plan.get("stop") or 0)
            target = float(plan.get("target") or 0)
            if entry > 1 and stop > 1 and target > 1:
                metrics = self._cash_metrics_from_prices(side, entry, stop, target)
                self.stop_box.setValue(max(0.01, metrics["stop_loss"]))
                self.rr_box.setValue(max(0.01, metrics["payout"]))
                self._update_plan_rr_label(side, entry, stop, target)
            else:
                rr = float(plan.get("rr") or 0)
                self.plan_rr_label.setText(f"Plan RR {rr:.2f}:1")
        finally:
            self._syncing_plan = False

    def on_plan_inputs_changed(self) -> None:
        if self._syncing_plan:
            return
        entry = self.entry_price_box.value()
        stop = self.stop_price_box.value()
        target = self.target_price_box.value()
        if entry > 1 and stop > 1 and target > 1:
            side = self.side_box.currentText()
            self.chart.set_plan(side, entry, stop, target, active=True, emit=False)
            self._syncing_plan = True
            try:
                self.entry_price_box.setValue(entry)
                self.stop_price_box.setValue(stop)
                self.target_price_box.setValue(target)
            finally:
                self._syncing_plan = False
            self._update_plan_rr_label(side, entry, stop, target)
            if self.latest_price is not None:
                self.update_ai(float(self.latest_price))

    def rebuild_plan_from_inputs(self) -> None:
        if self._syncing_plan:
            return
        self._update_configured_rr_label()
        # If the strategy has a valid setup, changing buy-in/stop/payout instantly updates the planned lines.
        if self.last_decision and self.last_decision.ready and getattr(self.last_decision, "plan", None) and not self.account.open_trade:
            self._last_auto_plan_sig = ""
            self.auto_manage_signal_plan()
            if self.latest_price is not None:
                self.update_ai(float(self.latest_price))
            return
        # If a plan is already visible, recalc it using cash stop/payout values.
        if self.candles.candles and self.chart.trade_plan.get("active"):
            side = self.side_box.currentText()
            entry = self.entry_price_box.value() if self.entry_price_box.value() > 1 else self.candles.candles[-1].close
            cash_rr = self._cash_payout() / max(self._cash_stop_loss(), 0.01)
            risk = self._recent_price_risk_distance(entry, self.stop_price_box.value() if self.stop_price_box.value() > 1 else None)
            reward = max(risk * cash_rr, entry * 0.00025)
            if side == "LONG":
                stop = max(0.01, entry - risk); target = entry + reward
            else:
                stop = entry + risk; target = max(0.01, entry - reward)
            self.chart.set_plan(side, entry, stop, target, active=True, emit=False)
            self._syncing_plan = True
            try:
                self.entry_price_box.setValue(entry)
                self.stop_price_box.setValue(stop)
                self.target_price_box.setValue(target)
            finally:
                self._syncing_plan = False
            self._update_plan_rr_label(side, entry, stop, target)
            if self.latest_price is not None:
                self.update_ai(float(self.latest_price))


    def _setup_meta_for_trade(self) -> dict:
        d = self.last_decision
        if not d:
            return {}
        snap = self.kalshi_timer.snapshot()
        contract_snap = self.kalshi_timer.snapshot()
        side = str(getattr(d, "side", ""))
        side_price = contract_snap.side_entry_cents(side) if hasattr(contract_snap, "side_entry_cents") else None
        spread = contract_snap.spread_cents() if hasattr(contract_snap, "spread_cents") else None
        return {
            "state": str(getattr(d, "state", "")),
            "side": str(getattr(d, "side", "")),
            "confidence": int(getattr(d, "confidence", 0)),
            "grade": str(getattr(d, "grade", "")),
            "trend_15m": str(getattr(d, "trend_15m", "")),
            "trend_5m": str(getattr(d, "trend_5m", "")),
            "confirmation": str(getattr(d, "confirmation", "")),
            "active_fvg_key": str(getattr(d, "active_fvg_key", "")),
            "active_fvg_status": str(getattr(d, "active_fvg_status", "")),
            "session_label": str(getattr(d, "session_label", "")),
            "time_left_seconds": int(snap.seconds_left()),
            "kalshi_ticker": str(getattr(contract_snap, "ticker", "")),
            "contract_price_line": contract_snap.price_line() if hasattr(contract_snap, "price_line") else "",
            "contract_side_price_cents": side_price,
            "contract_spread_cents": spread,
            "impulse_score": int(getattr(d, "impulse_score", 0)),
            "fvg_quality_score": int(getattr(d, "fvg_quality_score", 0)),
            "cash_buy_in": self._cash_size(),
            "cash_stop_loss": self._cash_stop_loss(),
            "cash_payout": self._cash_payout(),
            "cash_rr": self._cash_payout() / max(self._cash_stop_loss(), 0.01),
            "entry_model": str(getattr(d, "entry_model", "")),
            "higher_tf_bias": str(getattr(d, "higher_tf_bias", "")),
            "trigger_quality": str(getattr(d, "trigger_quality", "")),
            "trigger_sequence": str(getattr(d, "trigger_sequence", "")),
            "sweep_detected": bool(getattr(d, "sweep_detected", False)),
            "choch_detected": bool(getattr(d, "choch_detected", False)),
            "displacement_detected": bool(getattr(d, "displacement_detected", False)),
            "training_probe": bool(getattr(d, "training_probe", False)),
            "training_speed": self._training_speed(),
            "scalp_heavy": self._training_speed().startswith("Scalp"),
            "candlestick_patterns": list(getattr(d, "candlestick_patterns", [])),
            "candlestick_bias": str(getattr(d, "candlestick_bias", "")),
            "candlestick_signal": str(getattr(d, "candlestick_signal", "")),
        }



    def _current_btc15_bucket(self) -> int:
        return int(time.time()) - (int(time.time()) % 900)

    def _safe_trade_expiry_ts(self) -> float:
        """Return the locked expiry for the current BTC15 paper-trade bucket.

        For trade management we intentionally use the current 15-minute bucket
        boundary instead of a live Kalshi snapshot. The visible timer can still
        show Kalshi, but the paper trade must never inherit a stale/old snapshot
        and close immediately after opening.
        """
        now = time.time()
        local_exp = float(self._current_btc15_bucket() + 900)
        if local_exp <= now + 10:
            return float(self._current_btc15_bucket() + 1800)
        return local_exp

    def _safe_seconds_left(self) -> int:
        return max(0, int(self._safe_trade_expiry_ts() - time.time()))

    def _window_trade_count(self, bucket: int | None = None) -> int:
        bucket = self._current_btc15_bucket() if bucket is None else int(bucket)
        count = 0
        for tr in getattr(self.account, "trades", []):
            try:
                if int(tr.setup_meta.get("btc15_bucket", -1)) == bucket:
                    count += 1
            except Exception:
                pass
        return count

    def _max_trades_per_window(self) -> int:
        speed = self._training_speed() if hasattr(self, "_training_speed") else "More Trades"
        if speed.startswith("Strict"):
            return 1
        if speed.startswith("Scalp"):
            return 8
        if speed.startswith("Max"):
            return 5
        return 3

    def _trade_cooldown_seconds(self) -> int:
        speed = self._training_speed() if hasattr(self, "_training_speed") else "More Trades"
        if speed.startswith("Strict"):
            return 90
        if speed.startswith("Scalp"):
            return 12
        if speed.startswith("Max"):
            return 20
        return 45

    def _min_hold_seconds_for_mode(self) -> float:
        speed = self._training_speed() if hasattr(self, "_training_speed") else "More Trades"
        if speed.startswith("Strict"):
            return 35.0
        if speed.startswith("Scalp"):
            return 8.0
        if speed.startswith("Max"):
            return 10.0
        return 18.0

    def _rebuild_trade_lines_from_live_price(self, side: str, price: float) -> tuple[float, float, float, float]:
        """Build a fresh chart entry/stop/target from current BTC price.

        The strategy decides direction/permission. The actual paper entry uses
        the latest Coinbase BTC-USD tick so the bot does not open a stale plan
        that is already past stop or target.
        """
        entry = float(price)
        cash_rr = self._cash_payout() / max(self._cash_stop_loss(), 0.01)
        planned_stop = None
        try:
            planned_stop = float(self.chart.trade_plan.get("stop"))
        except Exception:
            planned_stop = None
        risk = self._recent_price_risk_distance(entry, planned_stop)
        reward = max(risk * cash_rr, entry * 0.00025)
        if side == "LONG":
            stop = max(0.01, entry - risk)
            target = entry + reward
        else:
            stop = entry + risk
            target = max(0.01, entry - reward)
        return entry, stop, target, cash_rr

    def _current_candle_bucket_ts(self) -> int:
        try:
            if self.candles.candles:
                return int(self.candles.candles[-1].ts)
        except Exception:
            pass
        return int(time.time() // 60 * 60)

    def _ready_confirmation_required(self) -> int:
        speed = self._training_speed() if hasattr(self, "_training_speed") else "More Trades"
        # Stable setup key now prevents the counter from resetting on every live
        # price tick. More Trades only needs one closed candle; Strict waits more.
        if speed.startswith("Strict"):
            return 2
        if speed.startswith("Scalp"):
            return 0
        if speed.startswith("Max"):
            return 0
        return 1

    def _ready_has_waited_enough(self, sig: str) -> tuple[bool, str]:
        required = self._ready_confirmation_required()
        if required <= 0:
            return True, "Aggressive mode: no extra wait after READY"
        bucket = self._current_candle_bucket_ts()
        if sig != self._ready_confirm_sig:
            self._ready_confirm_sig = sig
            self._ready_confirm_candle_ts = bucket
            self._ready_confirm_count = 0
            return False, f"Reading setup: waiting {required} closed candle(s) before paper entry"
        if bucket != self._ready_confirm_candle_ts:
            self._ready_confirm_candle_ts = bucket
            self._ready_confirm_count += 1
        ready = self._ready_confirm_count >= required
        return ready, f"Read confirmation candles {self._ready_confirm_count}/{required}"

    def open_planned_trade(self) -> bool:
        plan = self.chart.trade_plan
        if not plan.get("active") or not all(isinstance(plan.get(k), (int, float)) for k in ("entry", "stop", "target")):
            self.log("No auto plan yet. Waiting for confirmed setup first.")
            return False
        if not self.last_decision or not self.last_decision.ready:
            self.log("Blocked: paper trade requires a valid READY decision first.")
            return False
        if self.account.open_trade:
            self.log("Blocked: one paper trade already open.")
            return False

        bucket = self._current_btc15_bucket()
        max_trades = self._max_trades_per_window()
        current_count = self._window_trade_count(bucket)
        if current_count >= max_trades:
            self.log(f"Blocked: BTC15 paper trade cap reached {current_count}/{max_trades}. Waiting for next 15m read.")
            return False
        cooldown_left = self._trade_cooldown_seconds() - int(time.time() - float(getattr(self, "_last_trade_open_ts", 0.0) or 0.0))
        if current_count > 0 and cooldown_left > 0:
            self.log(f"Blocked: scalp cooldown {cooldown_left}s left before next paper entry.")
            return False
        seconds_left = self._safe_seconds_left()
        if seconds_left < max(12, int(getattr(self.setup_engine, "min_seconds_left", 25))):
            self.log(f"Blocked: BTC15 only has {seconds_left}s left. Waiting for next market.")
            return False

        try:
            side = str(plan.get("side", "LONG")).upper()
            live_entry = float(self.latest_price or plan["entry"])
            entry, stop, target, cash_rr = self._rebuild_trade_lines_from_live_price(side, live_entry)

            # Final stale-plan guard: do not open if the live price is already
            # beyond either exit line. This was the main cause of instant open/close.
            if side == "LONG" and not (stop < live_entry < target):
                self.log("Blocked stale LONG plan: live price is not between stop and target.")
                return False
            if side == "SHORT" and not (target < live_entry < stop):
                self.log("Blocked stale SHORT plan: live price is not between target and stop.")
                return False

            expiry_ts = self._safe_trade_expiry_ts()
            meta = self._setup_meta_for_trade()
            meta["cash_buy_in"] = self._cash_size()
            meta["cash_stop_loss"] = self._cash_stop_loss()
            meta["cash_payout"] = self._cash_payout()
            meta["cash_rr"] = cash_rr
            meta["btc15_bucket"] = bucket
            meta["expiry_ts"] = expiry_ts
            meta["min_hold_seconds"] = self._min_hold_seconds_for_mode()
            meta["training_speed"] = self._training_speed()
            meta["window_trade_number"] = current_count + 1
            meta["max_window_trades"] = max_trades

            self.account.open_position(
                side,
                entry,
                stop,
                target,
                self._cash_size(),
                f"{getattr(self.last_decision, 'entry_model', 'Setup')} | {getattr(self.last_decision, 'trend_15m', '')}/{getattr(self.last_decision, 'trend_5m', '')} | {getattr(self.last_decision, 'latest_fvg', '')} | {getattr(self.last_decision, 'trigger_quality', 'trigger')} | confidence {getattr(self.last_decision, 'confidence', 0)}% | risk ${self._cash_stop_loss():.2f} payout ${self._cash_payout():.2f} RR {cash_rr:.2f}:1",
                expires_at=expiry_ts,
                setup_meta=meta
            )
            self._traded_15m_buckets.add(bucket)
            self._last_trade_open_ts = time.time()
            if self._planned_gap_key:
                self._used_gap_keys.add(self._planned_gap_key)
            self.chart.set_cash_metrics(self._cash_size(), self._cash_stop_loss(), self._cash_payout())
            self.chart.set_plan(side, entry, stop, target, active=True, mode="trade", emit=False)
            exp = time.strftime("%H:%M:%S", time.localtime(expiry_ts))
            self.log_signal(f"OPENED PAPER {side} @ {entry:,.2f} | stop {stop:,.2f} | target {target:,.2f} | risk ${self._cash_stop_loss():.2f} payout ${self._cash_payout():.2f} | locked expiry {exp}")
            self.log_timeline(f"OPENED PAPER {side} | live entry {entry:,.2f} | scalp {current_count+1}/{max_trades} this BTC15 | min hold {self._min_hold_seconds_for_mode():.0f}s | locked expiry {exp}")
            return True
        except Exception as e:
            self.log(str(e))
            return False

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
                f"🟢 OPEN TRADE ACTIVE — {t.direction_label()} | Size ${t.size_usd:,.2f} | Entry {t.entry:,.2f} | "
                f"Stop {t.stop:,.2f} | Target {t.target:,.2f} | {self._live_payout_line(t)}"
            )
            self.open_trade_label.setObjectName("Green")
        else:
            self.open_trade_label.setText("⚪ No open paper trade — waiting for fresh 15m read/setup")
            self.open_trade_label.setObjectName("Muted")
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
        self.update_data_health_panel()

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
        current_rr = float(self.min_rr_box.value()) if hasattr(self, "min_rr_box") else float(getattr(self.setup_engine, "min_rr", 2.0))
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
        # Keep visible minimum RR filter in sync without changing the user's Target RR.
        if hasattr(self, "min_rr_box"):
            self.min_rr_box.blockSignals(True)
            self.min_rr_box.setValue(new_rr)
            self.min_rr_box.blockSignals(False)

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
        current_rr = float(self.min_rr_box.value()) if hasattr(self, "min_rr_box") else float(getattr(self.setup_engine, "min_rr", 2.0))
        try:
            result = self.learning.auto_tune(current_rr)
        except Exception:
            return
        if not result.get("ready"):
            return
        new_rr = float(result.get("recommended_min_rr", current_rr))
        if abs(new_rr - current_rr) >= 0.05:
            self.setup_engine.min_rr = new_rr
            if hasattr(self, "min_rr_box"):
                self.min_rr_box.blockSignals(True)
                self.min_rr_box.setValue(new_rr)
                self.min_rr_box.blockSignals(False)
            self.log(f"Self auto-tune adjusted minimum RR {current_rr:.2f} -> {new_rr:.2f}")

    def update_memory_stats_panel(self) -> None:
        if not hasattr(self, "memory_stats_box"):
            return
        stats = self.learning.stats()
        edge = self.learning.edge_profile(self.last_decision) if hasattr(self.learning, "edge_profile") else {}
        closed = [t for t in self.account.trades if t.status == "CLOSED"]
        total_pnl = sum(t.pnl for t in closed)
        best = max((t.pnl for t in closed), default=0.0)
        worst = min((t.pnl for t in closed), default=0.0)
        blacklist = "\n".join(
            f"• {c['cluster']} | {c['trades']} trades | WR {c['win_rate']:.1f}% | avg ${c['avg_pnl']:.2f}"
            for c in edge.get("blacklisted", [])[:6]
        ) or "No avoid-list setup families yet."
        proven = "\n".join(
            f"• {c['cluster']} | {c['trades']} trades | WR {c['win_rate']:.1f}% | avg ${c['avg_pnl']:.2f}"
            for c in edge.get("best", [])[:6]
        ) or "No proven setup families yet."
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
            "Proven setup families\n" + proven + "\n\n"
            "Avoid / blacklist families\n" + blacklist + "\n\n"
            + self.learning.daily_report() + "\n\n"
            "v0.8.2: edge filters, candle-pattern hover reads, data health, live payout zones, and stronger replay are active."
        )
        self._set_text_stable(self.memory_stats_box, text, "_last_memory_stats_text")

    def run_replay_backtest(self) -> None:
        candles = list(self.candles.candles)
        if len(candles) < 90:
            self._set_text_stable(self.backtest_box, "Need at least 90 one-minute candles before replay backtest can run.", "_last_backtest_text")
            return
        # Stronger walk-forward replay: no future candles in decisions, one open trade max,
        # exit by stop/target or synthetic BTC15 candle boundary.
        engine = FVGSetupEngine(min_rr=float(self.min_rr_box.value()))
        engine.training_speed = self._training_speed()
        try:
            engine._apply_training_speed()
        except Exception:
            pass
        wins = losses = trades = 0
        total_pnl = 0.0
        peak = 0.0
        max_drawdown = 0.0
        gross_win = 0.0
        gross_loss = 0.0
        open_trade = None
        used_gap_keys = set()
        by_side = {"LONG": {"trades":0,"wins":0,"pnl":0.0}, "SHORT": {"trades":0,"wins":0,"pnl":0.0}}
        by_grade = {}
        lines = ["Walk-forward Replay Backtest", "No future candles are shown to the engine during decisions.", "One open trade max, exits by stop/target/BTC15 boundary.", ""]
        for i in range(60, len(candles)):
            visible = candles[:i+1]
            c = visible[-1]
            price = c.close
            seconds_left = 900 - (int(c.ts) % 900)
            if open_trade:
                side, entry, stop, target, size, grade, open_bucket = open_trade
                if side == "LONG":
                    hit_stop = price <= stop; hit_target = price >= target
                    pnl = (price - entry) / entry * size
                else:
                    hit_stop = price >= stop; hit_target = price <= target
                    pnl = (entry - price) / entry * size
                expired = int(c.ts) // 900 != open_bucket
                if hit_stop or hit_target or expired:
                    trades += 1
                    total_pnl += pnl
                    peak = max(peak, total_pnl)
                    max_drawdown = min(max_drawdown, total_pnl - peak)
                    win = bool(hit_target or pnl > 0)
                    if win:
                        wins += 1; gross_win += max(0.0, pnl)
                    else:
                        losses += 1; gross_loss += abs(min(0.0, pnl))
                    by_side.setdefault(side, {"trades":0,"wins":0,"pnl":0.0})
                    by_side[side]["trades"] += 1; by_side[side]["wins"] += 1 if win else 0; by_side[side]["pnl"] += pnl
                    by_grade.setdefault(grade, {"trades":0,"wins":0,"pnl":0.0})
                    by_grade[grade]["trades"] += 1; by_grade[grade]["wins"] += 1 if win else 0; by_grade[grade]["pnl"] += pnl
                    reason = "TARGET" if hit_target else ("STOP" if hit_stop else "BTC15_END")
                    lines.append(f"#{trades:03d} {'WIN' if win else 'LOSS'} {side} {grade} via {reason} exit {price:,.2f} P/L ${pnl:.2f}")
                    open_trade = None
                continue
            engine.configure_context(used_gap_keys, seconds_left, self._training_speed())
            d = engine.evaluate(visible)
            blocked, _reason = self.learning.should_block_decision(d) if hasattr(self.learning, "should_block_decision") else (False, "")
            if blocked and not self._training_speed().startswith("Max"):
                continue
            if d.ready and d.plan:
                used_gap_keys.add(getattr(d, "active_fvg_key", ""))
                open_trade = (d.plan.side, d.plan.entry, d.plan.stop, d.plan.target, self._cash_size(), d.grade, int(c.ts)//900)
        win_rate = (wins / trades * 100) if trades else 0.0
        profit_factor = (gross_win / gross_loss) if gross_loss else (gross_win if gross_win else 0.0)
        side_lines = []
        for side, row in by_side.items():
            if row["trades"]:
                side_lines.append(f"{side}: {row['trades']} trades | WR {row['wins']/row['trades']*100:.1f}% | P/L ${row['pnl']:.2f}")
        grade_lines = []
        for grade, row in sorted(by_grade.items()):
            grade_lines.append(f"{grade}: {row['trades']} trades | WR {row['wins']/row['trades']*100:.1f}% | P/L ${row['pnl']:.2f}")
        summary = [
            f"Trades: {trades}",
            f"Wins/Losses: {wins}/{losses}",
            f"Win rate: {win_rate:.1f}%",
            f"Paper P/L on configured size: ${total_pnl:,.2f}",
            f"Profit factor: {profit_factor:.2f}",
            f"Max drawdown: ${abs(max_drawdown):,.2f}",
            "",
            "By side",
            *(side_lines or ["No side stats yet"]),
            "",
            "By grade",
            *(grade_lines or ["No grade stats yet"]),
            "",
        ]
        self._set_text_stable(self.backtest_box, "\n".join(summary + lines[-120:]), "_last_backtest_text")

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
            f"Contract prices: {snap.price_line() if hasattr(snap, 'price_line') else 'unavailable'}\n"
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
