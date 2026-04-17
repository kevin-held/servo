from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStatusBar,
    QLabel, QComboBox, QWidget,
)
from PySide6.QtCore import Qt, Slot

from core.loop          import CoreLoop
from core.state         import StateStore
from core.ollama_client import OllamaClient
from core.tool_registry import ToolRegistry
from gui.loop_panel     import LoopPanel
from gui.chat_panel     import ChatPanel
from gui.tool_panel     import ToolPanel


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Servo - Cybernetic Actuator")
        self.setMinimumSize(1400, 820)

        # Core systems
        self.state  = StateStore()
        self.ollama = OllamaClient()
        self.tools  = ToolRegistry()
        self.loop   = CoreLoop(self.state, self.ollama, self.tools)

        self._build_ui()
        self._connect_signals()
        self._start()

    # ── UI ────────────────────────────────────────

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
        splitter.setSizes([280, 720, 400])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)

        self.setCentralWidget(splitter)
        self.setStyleSheet("QMainWindow { background: #111; }")

        # Status bar
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background: #0d0d0d; color: #888; font-size: 11px; } QStatusBar QLabel { color: #888; }")
        self.setStatusBar(sb)

        self.status_label = QLabel("Starting…")
        sb.addWidget(self.status_label)

        sb.addPermanentWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setFixedWidth(200)
        self.model_combo.setStyleSheet("""
            QComboBox {
                background: #1a1a1a;
                color: #aaa;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                color: #aaa;
                border: 1px solid #333;
                selection-background-color: #2a2a2a;
            }
        """)
        self._populate_models()
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        sb.addPermanentWidget(self.model_combo)
        
        # Fire manually once on boot to establish the exact configs for the loaded model
        self._on_model_changed(self.ollama.model)

    def _populate_models(self):
        models = self.ollama.list_models()
        for m in models:
            self.model_combo.addItem(m)
        idx = self.model_combo.findText(self.ollama.model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

    # ── Signals ───────────────────────────────────

    def _connect_signals(self):
        self.loop.step_changed.connect(self.loop_panel.on_step_changed)
        self.loop.trace_event.connect(self.loop_panel.on_trace_event)
        self.loop.tool_called.connect(self.loop_panel.on_tool_called)
        self.loop.response_ready.connect(self.chat_panel.on_response_ready)
        self.loop.response_ready.connect(self._on_response_ready)
        self.loop.error_occurred.connect(self.chat_panel.on_error)
        self.loop.error_occurred.connect(self._on_error)
        self.loop.context_limit_changed.connect(self.loop_panel.on_context_limit_changed)
        self.loop.goals_changed.connect(self.tool_panel.on_goals_changed)

        self.loop.stream_started.connect(self.tool_panel.on_stream_started)
        self.loop.stream_chunk.connect(self.tool_panel.on_stream_chunk)

        # Sentinel Log Viewer — real-time log events from the core loop
        self.loop.log_event.connect(self.tool_panel.log_panel.on_log_event)
        
        self.tool_panel.stream_enabled_check.stateChanged.connect(
            lambda state: setattr(self.loop, "stream_enabled", bool(state))
        )

        self.loop_panel.context_spin.valueChanged.connect(
            lambda val: setattr(self.loop, "context_limit", val)
        )
        self.loop_panel.temp_spin.valueChanged.connect(
            lambda val: setattr(self.ollama, "temperature", val)
        )
        self.loop_panel.tokens_spin.valueChanged.connect(
            lambda val: setattr(self.ollama, "num_predict", val)
        )
        self.loop_panel.verbosity_combo.currentTextChanged.connect(
            lambda text: setattr(self.loop, "verbosity", text)
        )
        self.loop_panel.loop_limit_spin.valueChanged.connect(
            lambda val: setattr(self.loop, "loop_limit", val)
        )
        self.loop_panel.continuous_check.toggled.connect(
            lambda checked: setattr(self.loop, "continuous_mode", checked)
        )
        self.loop_panel.stop_btn.clicked.connect(self.loop.stop)

        self.chat_panel.input_submitted.connect(self._on_input)
        self.tool_panel.tool_changed.connect(lambda: self.tools.load_all())

    # ── Startup ───────────────────────────────────

    def _start(self):
        if self.ollama.is_available():
            self.status_label.setText("Ready")
            self.loop.start()

            # Sync roles → goals on boot (ensures enabled roles have their continuous goals)
            try:
                from tools.role_manager import execute as sync_roles
                sync_roles("sync")
            except Exception:
                pass
            
            # Sync Target Goals directly to UI on initial boot
            try:
                import os, json
                goal_path = os.path.join(os.getcwd(), "goals.json")
                if os.path.exists(goal_path):
                    with open(goal_path, "r", encoding="utf-8") as f:
                        self.tool_panel.on_goals_changed(json.load(f))
            except Exception:
                pass
        else:
            self.status_label.setText(
                "⚠  Ollama not found — run 'ollama serve' then restart"
            )

    # ── Slots ─────────────────────────────────────

    @Slot(str, str)
    def _on_input(self, text: str, image_b64: str = ""):
        self.status_label.setText("Processing…")
        self.loop.submit_input(text, image_b64)

    @Slot(str, str)
    def _on_response_ready(self, _, __):
        self.status_label.setText("Ready")

    @Slot(str)
    def _on_error(self, msg: str):
        self.status_label.setText(f"Error: {msg[:60]}")

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
                            self.loop_panel.temp_spin.setValue(float(cfg["temperature"]))
                        if "max_tokens" in cfg:
                            self.loop_panel.tokens_spin.setValue(int(cfg["max_tokens"]))
                        if "context_limit" in cfg:
                            self.loop_panel.context_spin.setValue(int(cfg["context_limit"]))
                        if "loop_limit" in cfg:
                            self.loop_panel.loop_limit_spin.setValue(int(cfg["loop_limit"]))
                        if "verbosity" in cfg:
                            self.loop_panel.verbosity_combo.setCurrentText(str(cfg["verbosity"]))
            except Exception as e:
                print(f"[Config] Error loading payload for {model}: {e}")

    def closeEvent(self, event):
        self.loop.stop()
        self.loop.wait(2000)
        # Flush and close the structured log file
        try:
            from core.sentinel_logger import get_logger
            get_logger().shutdown()
        except Exception:
            pass
        event.accept()
