from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStatusBar,
    QLabel, QComboBox, QWidget, QProgressBar,
    QPushButton
)
from PySide6.QtCore import Qt, Slot, QFileSystemWatcher
import os

from core.state         import StateStore
from core.ollama_client import OllamaClient
from core.tool_registry import ToolRegistry
from gui.loop_panel     import LoopPanel
from gui.chat_panel     import ChatPanel
from gui.tool_panel     import ToolPanel
from gui.context_viewer import ContextViewerWindow


# Phase G (UPGRADE_PLAN_6 sec 1, D-20260427-01) -- USE_SERVO_CORE no
# longer carries any branching meaning. The Phase F retirement of the
# toggle (D-20260426-01 step 8) made the constant a no-op already;
# Phase G's deletion of `core/loop.py` removes the alternative it
# would have toggled to. The constant is kept as a name in case a
# downstream consumer reads it for logging or telemetry.
USE_SERVO_CORE = True


class MainWindow(QMainWindow):

    def __init__(self, run_startup_tests=False, run_deep_diagnostics=False, run_startup_chores=False, profile=None):
        super().__init__()
        
        self.profile = profile or "default"
        self.setWindowTitle(f"Servo - Cybernetic Actuator [Profile: {self.profile}]")
        self.setMinimumSize(1500, 1000)
        
        self.run_startup_tests = run_startup_tests
        self.run_deep_diagnostics = run_deep_diagnostics
        self.run_startup_chores = run_startup_chores
        
        # v1.0.0 (D-20260421-15): Lean Hot-Reloading initialization
        self.config_watcher = QFileSystemWatcher(self)
        self.config_watcher.fileChanged.connect(self._on_config_file_changed)
        self.config_watcher.directoryChanged.connect(lambda: self._populate_profiles())

        # Core systems
        self.state  = StateStore(profile=profile)
        self.ollama = OllamaClient()
        self.tools  = ToolRegistry(config=None) # Will be injected in loop

        # ServoCore is the only path. The cognate loop owns chat
        # ingestion, OBSERVE park/wake, and response_ready emission.
        from core.lx_servo_thread import ServoCoreThread
        self.loop = ServoCoreThread(self.state, self.ollama, self.tools)

        # Inject the loop's central config registry into the tools
        self.tools.config = self.loop.config

        self._build_ui()
        self._connect_signals()
        self._start()

    # ── UI ──────────────────────

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setStyleSheet("QSplitter::handle { background: #1e1e1e; }")

        self.loop_panel = LoopPanel()
        self.chat_panel = ChatPanel()
        self.tool_panel = ToolPanel(self.tools)

        splitter.addWidget(self.loop_panel)
        splitter.addWidget(self.chat_panel)
        splitter.addWidget(self.tool_panel)
        
        # Restore button (v1.3.3)
        self.restore_tools_btn = QPushButton("«")
        self.restore_tools_btn.setFixedWidth(20)
        self.restore_tools_btn.setToolTip("Restore Tool Panel")
        self.restore_tools_btn.setStyleSheet("""
            QPushButton {
                background: #111; color: #00E5FF; border: 1px solid #2a2a2a; border-right: none;
                border-top-left-radius: 6px; border-bottom-left-radius: 6px;
                font-weight: bold; font-size: 14px;
            }
            QPushButton:hover { background: #1a1a1a; }
        """)
        self.restore_tools_btn.clicked.connect(self._toggle_tool_panel)
        self.restore_tools_btn.setVisible(False)
        splitter.addWidget(self.restore_tools_btn)

        splitter.setSizes([280, 720, 400, 0])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, True)
        splitter.setCollapsible(3, False)

        self.setCentralWidget(splitter)
        
        # Global Theme (D-20260502-02): Ensure context menus and widgets have 
        # readable contrast in dark mode.
        self.setStyleSheet("""
            QMainWindow { background: #111; }
            QWidget { color: #ccc; font-family: 'Segoe UI', 'Roboto', sans-serif; }
            
            /* Context Menus (Right-click) */
            QMenu {
                background-color: #252525;
                color: #eee;
                border: 1px solid #3a3a3a;
                padding: 4px;
            }
            QMenu::item {
                padding: 4px 20px;
                border-radius: 2px;
            }
            QMenu::item:selected {
                background-color: #00E5FF;
                color: black;
            }
            QMenu::separator {
                height: 1px;
                background: #333;
                margin: 4px 8px;
            }
            
            /* ScrollBars */
            QScrollBar:vertical {
                background: #111;
                width: 12px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #333;
                min-height: 20px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: #444;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        # Status bar
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background: #0d0d0d; color: #aaa; font-size: 11px; } QStatusBar QLabel { color: #aaa; }")
        self.setStatusBar(sb)

        self.status_label = QLabel("Starting…")
        sb.addWidget(self.status_label)

        sb.addPermanentWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(200)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a1a;
                color: #00E5FF;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
                font-weight: bold;
            }
            QComboBox::drop-down { 
                border: none; 
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #00E5FF;
                width: 0; height: 0;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #ccc;
                border: 1px solid #333;
                selection-background-color: #2a2a2a;
                selection-color: #00E5FF;
                outline: none;
            }
        """)
        self._populate_models()
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        sb.addPermanentWidget(self.model_combo)

        # Active Profile Indicator
        sb.addPermanentWidget(QLabel("  Profile:"))
        self.profile_indicator = QLabel(self.profile)
        # Cyan for custom, Dim Gray for default
        p_color = "#00E5FF" if self.profile != "default" else "#666"
        self.profile_indicator.setStyleSheet(f"color: {p_color}; font-weight: bold;")
        sb.addPermanentWidget(self.profile_indicator)

        # Context Depth Meter
        sb.addPermanentWidget(QLabel("  Context Depth (Tokens):"))
        self.context_meter = QProgressBar()
        self.context_meter.setFixedWidth(150)
        self.context_meter.setTextVisible(True)
        self.context_meter.setFormat("%v / %m")
        self.context_meter.setStyleSheet("""
            QProgressBar {
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                text-align: center;
                color: #ccc;
                font-size: 10px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #00E5FF;
                border-radius: 3px;
            }
        """)
        self.context_meter.setRange(0, self.ollama.num_ctx)
        sb.addPermanentWidget(self.context_meter)
        
        # Fire manually once on boot to establish the exact configs for the loaded model
        self._on_model_changed(self.ollama.model)

    def _populate_models(self):
        models = self.ollama.list_models()
        for m in models:
            self.model_combo.addItem(m)
        idx = self.model_combo.findText(self.ollama.model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

    def _populate_profiles(self):
        import os
        self.loop_panel.profile_combo.clear()
        self.loop_panel.profile_combo.addItem("Select Profile...")
        config_dir = os.path.join(os.getcwd(), "configs")
        if os.path.exists(config_dir):
            for f in os.listdir(config_dir):
                if f.endswith(".json") and f != "models.json":
                    self.loop_panel.profile_combo.addItem(f)
                    # Track this file for changes
                    self.config_watcher.addPath(os.path.join(config_dir, f))

    # ── Signals ───────────────────

    def _connect_signals(self):
        self.loop.step_changed.connect(self.loop_panel.on_step_changed)
        # Phase G (UPGRADE_PLAN_6 sec 2.c, D-20260427-02) -- the LOOP
        # STATE trace tree was removed, so `trace_event` and
        # `tool_called` no longer have GUI listeners. The signals are
        # still defined on `ServoCoreThread` for forward compatibility
        # (and so existing emissions don't crash); they fire into the
        # void on the cognate path.

        # ServoCoreThread emits `tool_dispatched(tool_name)` right
        # before lx_Act invokes the registry, so the tool panel can
        # highlight the active atomic primitive. The hasattr gate
        # stays for forward compatibility with future engines that
        # may not implement the signal.
        if hasattr(self.loop, "tool_dispatched"):
            self.loop.tool_dispatched.connect(self.tool_panel.on_tool_dispatched)

        self.loop.response_ready.connect(self.chat_panel.on_response_ready)
        self.loop.response_ready.connect(self._on_response_ready)
        self.loop.error_occurred.connect(self.chat_panel.on_error)
        self.loop.error_occurred.connect(self._on_error)
        self.loop.config_changed.connect(self._on_config_changed)

        self.loop.stream_started.connect(self.tool_panel.on_stream_started)
        self.loop.stream_chunk.connect(self.tool_panel.on_stream_chunk)

        # Sentinel Log Viewer — real-time log events from the core loop
        self.loop.log_event.connect(self.tool_panel.log_panel.on_log_event)
        
        # Telemetry — real-time context and bound data
        self.loop.telemetry_event.connect(self._on_telemetry_event)
        
        # Context Viewer (v1.3.2)
        self.loop.context_view_requested.connect(self._on_context_view_requested)
        
        # Tool Panel interactions (v1.3.3)
        self.tool_panel.fold_requested.connect(self._toggle_tool_panel)
        self.tool_panel.tool_execute_requested.connect(self._on_tool_execute_requested)
        
        # ── PROFILE SWITCHER ──
        self._populate_profiles()
        self.loop_panel.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        self.loop_panel.save_profile_btn.clicked.connect(self._on_save_profile)

        # ── OPTIMIZATION TOGGLES ──
        self.loop_panel.summarize_context_check.toggled.connect(
            lambda val: self.state.set("summarize_contextualize", str(val))
        )
        self.loop_panel.summarize_history_check.toggled.connect(
            lambda val: self.state.set("summarize_history_integrate", str(val))
        )
        self.loop_panel.summarize_tool_check.toggled.connect(
            lambda val: self.state.set("summarize_tool_results", str(val))
        )

        # ── HARDWARE GUARD ──
        self.loop_panel.throttle_enable_check.toggled.connect(
            lambda val: [setattr(self.loop, "hardware_throttling_enabled", val), self.state.set("hardware_throttling_enabled", str(val))]
        )
        self.loop_panel.throttle_enter_spin.valueChanged.connect(
            lambda val: [setattr(self.loop, "hardware_throttle_threshold_enter", float(val)), self.state.set("hardware_throttle_threshold_enter", str(val))]
        )
        self.loop_panel.throttle_exit_spin.valueChanged.connect(
            lambda val: [setattr(self.loop, "hardware_throttle_threshold_exit", float(val)), self.state.set("hardware_throttle_threshold_exit", str(val))]
        )

        self.loop_panel.summarize_history_multiplier_spin.valueChanged.connect(
            lambda val: self.state.set("history_compression_trigger", str(val))
        )
        self.loop_panel.summarize_history_target_spin.valueChanged.connect(
            lambda val: self.state.set("history_compression_target_chars", str(val))
        )
        self.loop_panel.summarize_tool_threshold_spin.valueChanged.connect(
            lambda val: self.state.set("tool_result_compression_threshold", str(val))
        )
        self.loop_panel.summarize_tool_target_spin.valueChanged.connect(
            lambda val: self.state.set("tool_result_compression_target_chars", str(val))
        )
        self.loop_panel.summarize_context_threshold_check.toggled.connect(
            lambda val: self.state.set("summarize_read_enabled", str(val))
        )
        self.loop_panel.summarize_context_threshold_spin.valueChanged.connect(
            lambda val: self.state.set("summarize_read_threshold", str(val))
        )
        self.loop_panel.show_thinking_check.toggled.connect(
            lambda val: self.state.set("ui_show_thinking", str(val))
        )

        self.tool_panel.stream_enabled_check.stateChanged.connect(
            lambda state: setattr(self.loop, "stream_enabled", bool(state))
        )

        self.loop_panel.context_spin.valueChanged.connect(
            lambda val: setattr(self.loop, "conversation_history", val)
        )
        self.loop_panel.temp_spin.valueChanged.connect(
            lambda val: setattr(self.ollama, "temperature", val)
        )
        self.loop_panel.tokens_spin.valueChanged.connect(
            lambda val: setattr(self.ollama, "num_predict", val)
        )
        self.loop_panel.verbosity_combo.currentTextChanged.connect(
            lambda val: setattr(self.loop, "verbosity", val)
        )
        
        # Load startup config from models.json for the default loaded model
        self._on_model_changed(self.ollama.model)
        self.loop_panel.loop_limit_spin.valueChanged.connect(
            lambda val: setattr(self.loop, "chain_limit", val)
        )
        self.loop_panel.auto_continue_spin.valueChanged.connect(
            lambda val: setattr(self.loop, "max_auto_continues", val)
        )
        self.loop_panel.autonomous_limit_spin.valueChanged.connect(
            lambda val: setattr(self.loop, "autonomous_loop_limit", val)
        )
        self.loop_panel.stop_btn.clicked.connect(self.loop.stop)

        self.chat_panel.input_submitted.connect(self._on_input)
        self.tool_panel.tool_changed.connect(lambda: self.tools.load_all())

    # ── Startup ───────────────────

    def _start(self):
        if self.ollama.is_available():
            self.status_label.setText("Ready")
            self.loop.start()

            # v1.3.4 (D-20260422-05): Startup Chores escalation
            do_tests = self.run_startup_tests or self.run_deep_diagnostics or self.run_startup_chores
            
            if do_tests:
                from gui.startup_worker import StartupWorker
                self.status_label.setText("Running startup diagnostics...")
                
                # Make sure the user can see what's happening
                self.chat_panel.append_message("System", f"Running hardware diagnostics on profile \'{self.profile}\'. Please wait...")
                
                self._startup_worker = StartupWorker(
                    run_fast=True, 
                    run_deep=self.run_deep_diagnostics
                )
                self._startup_worker.finished_report.connect(self._on_startup_tests_finished)
                self._startup_worker.start()
            else:
                # Fast standard boot without tests
                report_pieces = ["[STARTUP DIAGNOSTIC]", "System core booted cleanly. Offline tests bypassed."]
                pending_tasks = self.state.get_pending_tasks()
                if pending_tasks:
                    report_pieces.append(f"\n[WARNING] {len(pending_tasks)} pending tasks from the previous session survived the reboot.\nPlease actively review the ledger and clear them if they are no longer relevant.")
                
                report_pieces.append("\nProceed with user directives.")
                self.loop.submit_startup_diagnostic("\n".join(report_pieces))

        else:
            self.status_label.setText(
                "⚠  Ollama not found — run \'ollama serve\' then restart"
            )

    @Slot(str)
    def _on_startup_tests_finished(self, report_text: str):
        self.status_label.setText("Ready")
        
        pending_tasks = self.state.get_pending_tasks()
        if pending_tasks:
            report_text += f"\n\n[WARNING] {len(pending_tasks)} pending tasks from the previous session survived the reboot.\nPlease actively review the ledger and clear them if they are no longer relevant."

        # Operational Directives to prevent mission-residue hallucinations
        report_text += "\n\n[SYSTEM STATUS] Operational Handover complete."
        report_text += "\n[DIRECTIVE] Remediation session D-2026-04-21 is COMPLETED. All core regressions are resolved and verified."
        report_text += "\n[DIRECTIVE] You are now in IDLE mode. Await USER input. Do not spontaneously re-diagnose stable components."

        # Display the full report in the UI for the operator
        self.chat_panel.append_message("System", report_text)
        self.chat_panel.append_message("System", "Diagnostics complete. Handing over to Servo.")

        self.loop.submit_startup_diagnostic(report_text)
        
        # v1.3.4 (D-20260422-05): Auto-Initialization Chores
        if self.run_startup_chores:
            self._run_chores()

    def _run_chores(self):
        """Reads chores.md and submits the content to the agent."""
        import os
        chores_path = os.path.join(os.getcwd(), "codex", "manifests", "chores.md")
        if not os.path.exists(chores_path):
            self.chat_panel.append_message("System", "⚠ [CHORES] chores.md not found. Skipping auto-initialization.")
            return

        try:
            with open(chores_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                
            if not content:
                self.chat_panel.append_message("System", "⚠ [CHORES] chores.md is empty. Skipping.")
                return
                
            self.chat_panel.append_message("System", "🚀 [CHORES] Automated initialization starting...")
            # We use _on_input to simulate a user turn, ensuring it goes through the proper pipeline
            self._on_input(content)
        except Exception as e:
            self.chat_panel.on_error(f"Failed to run chores: {e}")

    # ── Slots ─────────────────

    @Slot(str, str)
    def _on_input(self, text: str, image_b64: str = ""):
        self.status_label.setText("Processing…")
        self.loop.submit_input(text, image_b64)

    @Slot(str, str)
    def _on_response_ready(self, _, __):
        self.status_label.setText("Ready")

    @Slot(str, object)
    def _on_config_changed(self, param: str, value: object):
        mapping = {
            "conversation_history": self.loop_panel.context_spin,
            "temperature": self.loop_panel.temp_spin,
            "max_tokens": self.loop_panel.tokens_spin,
            "chain_limit": self.loop_panel.loop_limit_spin,
            "max_auto_continues": self.loop_panel.auto_continue_spin,
            "autonomous_loop_limit": self.loop_panel.autonomous_limit_spin,
        }
        if param in mapping:
            spin = mapping[param]
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        elif param == "verbosity":
            self.loop_panel.verbosity_combo.blockSignals(True)
            self.loop_panel.verbosity_combo.setCurrentText(str(value))
            self.loop_panel.verbosity_combo.blockSignals(False)
        elif param == "summarize_contextualize":
            self.loop_panel.summarize_context_check.blockSignals(True)
            self.loop_panel.summarize_context_check.setChecked(str(value).lower() == "true")
            self.loop_panel.summarize_context_check.blockSignals(False)
        elif param == "summarize_history_integrate":
            self.loop_panel.summarize_history_check.blockSignals(True)
            self.loop_panel.summarize_history_check.setChecked(str(value).lower() == "true")
            self.loop_panel.summarize_history_check.blockSignals(False)
        elif param == "summarize_tool_results":
            self.loop_panel.summarize_tool_check.blockSignals(True)
            self.loop_panel.summarize_tool_check.setChecked(str(value).lower() == "true")
            self.loop_panel.summarize_tool_check.blockSignals(False)
        elif param == "hardware_throttling_enabled":
            self.loop_panel.throttle_enable_check.blockSignals(True)
            self.loop_panel.throttle_enable_check.setChecked(str(value).lower() == "true")
            self.loop_panel.throttle_enable_check.blockSignals(False)
        elif param == "hardware_throttle_threshold_enter":
            self.loop_panel.throttle_enter_spin.blockSignals(True)
            self.loop_panel.throttle_enter_spin.setValue(float(value))
            self.loop_panel.throttle_enter_spin.blockSignals(False)
        elif param == "hardware_throttle_threshold_exit":
            self.loop_panel.throttle_exit_spin.blockSignals(True)
            self.loop_panel.throttle_exit_spin.setValue(float(value))
            self.loop_panel.throttle_exit_spin.blockSignals(False)

    @Slot(str)
    def _on_error(self, msg: str):
        self.status_label.setText(f"Error: {msg[:60]}")

    @Slot(str)
    def _on_profile_changed(self, filename: str):
        if not filename or filename == "Select Profile...":
            return
        self.status_label.setText(f"Loading Profile: {filename}...")
        from tools.system_config import execute
        report = execute(operation="load", value=filename)
        self.chat_panel.append_message("System", report)
        # Bridge to persistent context (D-20260421-13)
        self.state.add_conversation_turn("user", f"[SYSTEM] {report}")
        self.status_label.setText("Ready")

    @Slot(str)
    def _on_config_file_changed(self, path: str):
        """Triggered when an external editor saves a JSON in configs/."""
        filename = os.path.basename(path)
        current = self.loop_panel.profile_combo.currentText()
        if filename == current:
            self.chat_panel.append_message("System", f"⚡ Hot-Reload: \'{filename}\' modified externally. Syncing...")
            self._on_profile_changed(current)

    @Slot()
    def _on_save_profile(self):
        filename = self.loop_panel.profile_combo.currentText().strip()
        if not filename or filename == "Select Profile...":
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Profile Save Error", "Please enter a valid profile name.")
            return

        if not filename.endswith(".json"):
            filename += ".json"

        self.status_label.setText(f"Saving Profile: {filename}...")
        from tools.system_config import execute
        report = execute(operation="save", value=filename)
        
        self.chat_panel.append_message("System", report)
        # Bridge to persistent context (D-20260421-13)
        self.state.add_conversation_turn("user", f"[SYSTEM] {report}")
        self.status_label.setText("Ready")
        
        # Refresh the list to include the new/renamed profile
        self.loop_panel.profile_combo.blockSignals(True)
        self._populate_profiles()
        self.loop_panel.profile_combo.setCurrentText(filename)
        self.loop_panel.profile_combo.blockSignals(False)

    @Slot(int, int)
    def _on_telemetry_event(self, current: int, limit: int):
        self.context_meter.setRange(0, limit)
        self.context_meter.setValue(current)
        
        # Style update based on pressure
        if current > limit * 0.9:
            color = "#FF1744" # Red
        elif current > limit * 0.7:
            color = "#FFEA00" # Yellow
        else:
            color = "#00E5FF" # Cyan
            
        self.context_meter.setStyleSheet(f"""
            QProgressBar {{
                background: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                text-align: center;
                color: #ccc;
                font-size: 10px;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)

    @Slot(str)
    def _on_model_changed(self, model: str):
        self.ollama.model = model
        self.status_label.setText(f"Model → {model}")
        
        # Auto-load Model defaults
        import json
        import os
        config_path = os.path.join(os.getcwd(), "configs", "models.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    models_configs = json.load(f).get("models", {})
                    
                    if model in models_configs:
                        cfg = models_configs[model]
                        if "temperature" in cfg:
                            val = float(cfg["temperature"])
                            self.ollama.temperature = val
                            self.loop_panel.temp_spin.setValue(val)
                        if "max_tokens" in cfg:
                            val = int(cfg["max_tokens"])
                            self.ollama.num_predict = val
                            self.loop_panel.tokens_spin.setValue(val)
                        if "conversation_history" in cfg:
                            val = int(cfg["conversation_history"])
                            self.loop.conversation_history = val
                            self.loop.default_conversation_history = val
                            self.loop_panel.context_spin.setValue(val)
                        if "chain_limit" in cfg:
                            val = int(cfg["chain_limit"])
                            self.loop.chain_limit = val
                            self.loop_panel.loop_limit_spin.setValue(val)
                        if "verbosity" in cfg:
                            val = str(cfg["verbosity"])
                            self.loop.verbosity = val
                            self.loop_panel.verbosity_combo.setCurrentText(val)
                        if "max_auto_continues" in cfg:
                            val = int(cfg["max_auto_continues"])
                            self.loop.max_auto_continues = val
                            self.loop_panel.auto_continue_spin.setValue(val)
                        if "autonomous_loop_limit" in cfg:
                            val = int(cfg["autonomous_loop_limit"])
                            self.loop.autonomous_loop_limit = val
                            self.loop_panel.autonomous_limit_spin.setValue(val)
                    
                    # Also sync the new toggles from State
                    self.loop_panel.summarize_context_check.setChecked(self.state.get("summarize_contextualize", "True").lower() == "true")
                    self.loop_panel.summarize_history_check.setChecked(self.state.get("summarize_history_integrate", "True").lower() == "true")
                    self.loop_panel.summarize_tool_check.setChecked(self.state.get("summarize_tool_results", "True").lower() == "true")
                    self.loop_panel.throttle_enable_check.setChecked(self.state.get("hardware_throttling_enabled", "True").lower() == "true")
                    self.loop_panel.throttle_enter_spin.setValue(float(self.state.get("hardware_throttle_threshold_enter", "95.0")))
                    self.loop_panel.throttle_exit_spin.setValue(float(self.state.get("hardware_throttle_threshold_exit", "90.0")))
                    
                    self.loop_panel.summarize_history_multiplier_spin.setValue(float(self.state.get("history_compression_trigger", "2.0")))
                    self.loop_panel.summarize_history_target_spin.setValue(int(self.state.get("history_compression_target_chars", "800")))
                    self.loop_panel.summarize_tool_threshold_spin.setValue(int(self.state.get("tool_result_compression_threshold", "4000")))
                    self.loop_panel.summarize_tool_target_spin.setValue(int(self.state.get("tool_result_compression_target_chars", "500")))
                    self.loop_panel.summarize_context_threshold_check.setChecked(self.state.get("summarize_read_enabled", "True").lower() == "true")
                    self.loop_panel.summarize_context_threshold_spin.setValue(int(self.state.get("summarize_read_threshold", "800")))
                    self.loop_panel.show_thinking_check.setChecked(self.state.get("ui_show_thinking", "True").lower() == "true")
            except Exception as e:
                print(f"[Config] Error loading payload for {model}: {e}")

    @Slot()
    def _toggle_tool_panel(self):
        is_visible = self.tool_panel.isVisible()
        self.tool_panel.setVisible(not is_visible)
        self.restore_tools_btn.setVisible(is_visible)
        
        # Adjust splitter to reclaim space
        splitter = self.centralWidget()
        if is_visible:
            # Hiding: loop=280, chat=fill, tools=0, restore=20
            splitter.setSizes([280, 1000, 0, 20])
        else:
            # Showing: restore to previous split
            splitter.setSizes([280, 720, 400, 0])

    @Slot(str, dict)
    def _on_tool_execute_requested(self, name: str, args: dict):
        """Formats and submits a tool call as if it were typed by the user."""
        import json
        call_json = json.dumps({"tool": name, "args": args})
        # Inject directly into the chat panel's logic
        self.chat_panel.input_field.setText(call_json)
        self.chat_panel._submit()

    @Slot(list)
    def _on_context_view_requested(self, history: list):
        viewer = ContextViewerWindow(history, parent=self)
        # Ensure that resuming logic is tied to both the Resume button and closing the window
        viewer.resume_btn.clicked.connect(self.loop.resume)
        viewer.resume_btn.clicked.connect(viewer.close)
        viewer.closed.connect(self.loop.resume)
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        viewer.show()

    def closeEvent(self, event):
        self.loop.stop()
        # v1.0.0 (D-20260421-14): Execute session sentinel cleanup
        self.loop.cleanup()
        self.loop.wait(2000)
        # Flush and close the structured log file
        try:
            from core.sentinel_logger import get_logger
            get_logger().shutdown()
        except Exception:
            pass
        event.accept()
