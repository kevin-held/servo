from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame,
    QSpinBox, QDoubleSpinBox, QComboBox, QGridLayout,
    QCheckBox, QPushButton, QGroupBox, QHBoxLayout
)
from core.identity import get_system_defaults
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont

# Phase G (UPGRADE_PLAN_6 sec 2.a, D-20260427-02) -- the LOOP STATE
# panel now displays the four cognate phases directly. The historical
# six-name vocabulary in `core.lx_steps` is preserved for legacy log
# replay, but the GUI's step-indicator pills are keyed on the cognate
# loop's actual dispatch surface: OBSERVE -> REASON -> ACT -> INTEGRATE.
from core.lx_steps import Step as LoopStep


STEP_COLORS = {
    LoopStep.OBSERVE:   "#4CAF50",  # Green  -- perception ingest
    LoopStep.REASON:    "#FF9800",  # Orange -- thought / planning
    LoopStep.ACT:       "#F44336",  # Red    -- tool dispatch
    LoopStep.INTEGRATE: "#9C27B0",  # Purple -- ledger commit
}

STEP_ORDER = [
    LoopStep.OBSERVE,
    LoopStep.REASON,
    LoopStep.ACT,
    LoopStep.INTEGRATE,
]


class StepIndicator(QLabel):
    """Single step pill — lights up when active."""

    def __init__(self, step_name: str):
        super().__init__(step_name)
        self.step_name = step_name
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(34)
        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        self.setFont(f)
        self.set_active(False)

    def set_active(self, active: bool):
        color = STEP_COLORS.get(self.step_name, "#546E7A")
        if active:
            self.setStyleSheet(f"""
                background: {color};
                color: white;
                border-radius: 4px;
                padding: 4px 8px;
            """)
        else:
            self.setStyleSheet("""
                background: #1e1e1e;
                color: #888;
                border-radius: 4px;
                border: 1px solid #2a2a2a;
                padding: 4px 8px;
            """)


class LoopPanel(QWidget):

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(260)
        self._indicators: dict = {}
        self._build_ui()
        self._sync_ranges()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._section_label("SYSTEM CONTROLS", layout)

        # ── PROFILE SELECTION ──
        profile_frame = QFrame()
        profile_frame.setStyleSheet("background: #1a1a1a; border-radius: 4px; border: 1px solid #2a2a2a;")
        pf_layout = QHBoxLayout(profile_frame)
        pf_layout.setContentsMargins(8, 4, 8, 4)
        
        prof_lbl = QLabel("Active Profile:")
        prof_lbl.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        self.profile_combo = QComboBox()
        self.profile_combo.setEditable(True)
        self.profile_combo.setStyleSheet("""
            QComboBox { 
                background: #111; color: #00E5FF; border: 1px solid #2a2a2a; border-radius: 4px; 
                padding: 2px 8px; font-size: 11px; font-weight: bold; 
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox::down-arrow {
                image: none; border-left: 3px solid transparent; border-right: 3px solid transparent;
                border-top: 3px solid #00E5FF; width: 0; height: 0; margin-right: 4px;
            }
            QComboBox QAbstractItemView { background: #111; color: #00E5FF; selection-background-color: #1a1a1a; }
        """)
        
        self.save_profile_btn = QPushButton("💾")
        self.save_profile_btn.setFixedSize(24, 24)
        self.save_profile_btn.setToolTip("Save Current Profile")
        self.save_profile_btn.setStyleSheet("""
            QPushButton { 
                background: #111; color: #00E5FF; border: 1px solid #2a2a2a; border-radius: 4px; 
                font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #1a1a1a; border-color: #00E5FF; }
            QPushButton:pressed { background: #00E5FF; color: black; }
        """)
        
        pf_layout.addWidget(prof_lbl)
        pf_layout.addWidget(self.profile_combo, 1)
        pf_layout.addWidget(self.save_profile_btn)
        layout.addWidget(profile_frame)

        # ── AUTONOMY GROUP ──
        autonomy_group = QGroupBox("Autonomy && Endurance")
        autonomy_group.setStyleSheet("""
            QGroupBox { color: #aaa; font-size: 10px; font-weight: bold; margin-top: 10px; border: 1px solid #333; border-radius: 4px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; background: #111; }
        """)
        ag_layout = QVBoxLayout(autonomy_group)
        
        # STOP Button Row
        stop_layout = QHBoxLayout()
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setFixedHeight(24)
        self.stop_btn.setStyleSheet("""
            QPushButton { background: #E61717; color: white; border-radius: 4px; font-weight: bold; font-size: 11px; letter-spacing: 2px; }
            QPushButton:hover { background: #FF2E2E; }
            QPushButton:pressed { background: #990000; }
        """)
        stop_layout.addWidget(self.stop_btn)
        ag_layout.addLayout(stop_layout)

        ag_grid = QGridLayout()
        ag_grid.setSpacing(8)
        
        lbl5 = QLabel("Chain Limit:")
        lbl5.setToolTip("Max tools per turn cycle.")
        self.loop_limit_spin = QSpinBox()
        self.loop_limit_spin.setFixedWidth(102)
        
        lbl7 = QLabel("Autonomous Loop Limit:")
        lbl7.setToolTip("Max re-loops before forced pause. 0=Infinite.")
        self.autonomous_limit_spin = QSpinBox()
        self.autonomous_limit_spin.setSpecialValueText("Endless (0)")
        self.autonomous_limit_spin.setFixedWidth(102)
        
        lbl6 = QLabel("Max Auto Continues:")
        lbl6.setToolTip("Max response stitchings (the \'glue\').")
        self.auto_continue_spin = QSpinBox()
        self.auto_continue_spin.setFixedWidth(102)

        ag_grid.addWidget(lbl5, 0, 0); ag_grid.addWidget(self.loop_limit_spin, 0, 1)
        ag_grid.addWidget(lbl7, 1, 0); ag_grid.addWidget(self.autonomous_limit_spin, 1, 1)
        ag_grid.addWidget(lbl6, 2, 0); ag_grid.addWidget(self.auto_continue_spin, 2, 1)
        
        ag_layout.addLayout(ag_grid)
        layout.addWidget(autonomy_group)

        # ── REASONING GROUP ──
        reason_group = QGroupBox("Resource Reasoning")
        reason_group.setStyleSheet(autonomy_group.styleSheet())
        rg_layout = QVBoxLayout(reason_group)
        rg_grid = QGridLayout()
        rg_grid.setSpacing(8)

        lbl2 = QLabel("Temperature:")
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setFixedWidth(102)
        
        lbl3 = QLabel("Max Tokens:")
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setSingleStep(256)
        self.tokens_spin.setFixedWidth(102)

        lbl = QLabel("Conversation History:")
        self.context_spin = QSpinBox()
        self.context_spin.setFixedWidth(102)
        
        lbl4 = QLabel("Verbosity:")
        self.verbosity_combo = QComboBox()
        self.verbosity_combo.addItems(["Concise", "Normal", "Detailed"])
        self.verbosity_combo.setFixedWidth(102)
        
        rg_grid.addWidget(lbl2, 0, 0); rg_grid.addWidget(self.temp_spin, 0, 1)
        rg_grid.addWidget(lbl3, 1, 0); rg_grid.addWidget(self.tokens_spin, 1, 1)
        rg_grid.addWidget(lbl, 2, 0);  rg_grid.addWidget(self.context_spin, 2, 1)
        rg_grid.addWidget(lbl4, 3, 0); rg_grid.addWidget(self.verbosity_combo, 3, 1)
        
        # Hardware Throttling (Moved here per D-20260421-09)
        ag_grid_hw = QGridLayout()
        self.throttle_enable_check = QCheckBox("Hardware Throttling")
        self.throttle_enable_check.setStyleSheet("color: #aaa; font-size: 11px; font-weight: bold;")
        
        self.throttle_enter_spin = QSpinBox()
        self.throttle_enter_spin.setSuffix("%")
        self.throttle_enter_spin.setFixedWidth(50)
        
        self.throttle_exit_spin = QSpinBox()
        self.throttle_exit_spin.setSuffix("%")
        self.throttle_exit_spin.setFixedWidth(50)
        
        ag_grid_hw.addWidget(self.throttle_enable_check, 0, 0)
        ag_grid_hw.addWidget(self.throttle_enter_spin, 0, 1)
        ag_grid_hw.addWidget(self.throttle_exit_spin, 0, 2)
        
        rg_layout.addSpacing(4)
        rg_layout.addLayout(ag_grid_hw)
        rg_layout.addSpacing(4)

        rg_layout.addLayout(rg_grid)
        layout.addWidget(reason_group)

        # ── SUMMARIZER SETTINGS ──
        summarizer_group = QGroupBox("Summarizer Settings")
        summarizer_group.setStyleSheet(autonomy_group.styleSheet())
        sg_layout = QVBoxLayout(summarizer_group)
        sg_layout.setSpacing(4)
        
        # 1. Prior Context
        self.summarize_context_check = QCheckBox("Prior Context")
        self.summarize_context_check.setStyleSheet("color: #aaa; font-size: 11px;")
        sg_layout.addWidget(self.summarize_context_check)

        # 2. History (Trigger/Target)
        hist_row = QHBoxLayout()
        self.summarize_history_check = QCheckBox("History")
        self.summarize_history_check.setStyleSheet("color: #aaa; font-size: 11px;")
        
        lbl_h_mult = QLabel("Trig:")
        lbl_h_mult.setStyleSheet("color: #666; font-size: 10px;")
        self.summarize_history_multiplier_spin = QDoubleSpinBox()
        self.summarize_history_multiplier_spin.setSuffix("x")
        self.summarize_history_multiplier_spin.setFixedWidth(50)
        
        lbl_h_target = QLabel("Tgt:")
        lbl_h_target.setStyleSheet("color: #666; font-size: 10px;")
        self.summarize_history_target_spin = QSpinBox()
        self.summarize_history_target_spin.setFixedWidth(50)
        
        hist_row.addWidget(self.summarize_history_check)
        hist_row.addStretch()
        hist_row.addWidget(lbl_h_mult); hist_row.addWidget(self.summarize_history_multiplier_spin)
        hist_row.addWidget(lbl_h_target); hist_row.addWidget(self.summarize_history_target_spin)
        sg_layout.addLayout(hist_row)

        # 3. Tools
        tool_row = QHBoxLayout()
        self.summarize_tool_check = QCheckBox("Tools")
        self.summarize_tool_check.setStyleSheet("color: #aaa; font-size: 11px;")
        
        lbl_t_thresh = QLabel("Trig:")
        lbl_t_thresh.setStyleSheet("color: #666; font-size: 10px;")
        self.summarize_tool_threshold_spin = QSpinBox()
        self.summarize_tool_threshold_spin.setSuffix("c")
        self.summarize_tool_threshold_spin.setFixedWidth(50)
        
        lbl_t_target = QLabel("Tgt:")
        lbl_t_target.setStyleSheet("color: #666; font-size: 10px;")
        self.summarize_tool_target_spin = QSpinBox()
        self.summarize_tool_target_spin.setFixedWidth(50)
        
        tool_row.addWidget(self.summarize_tool_check)
        tool_row.addStretch()
        tool_row.addWidget(lbl_t_thresh); tool_row.addWidget(self.summarize_tool_threshold_spin)
        tool_row.addWidget(lbl_t_target); tool_row.addWidget(self.summarize_tool_target_spin)
        sg_layout.addLayout(tool_row)

        # 4. Files
        file_grid = QGridLayout()
        self.summarize_context_threshold_check = QCheckBox("Files")
        self.summarize_context_threshold_check.setStyleSheet("color: #aaa; font-size: 11px;")
        
        lbl_f_thresh = QLabel("Trigger:")
        lbl_f_thresh.setStyleSheet("color: #666; font-size: 10px;")
        self.summarize_context_threshold_spin = QSpinBox()
        self.summarize_context_threshold_spin.setSuffix(" L")
        self.summarize_context_threshold_spin.setFixedWidth(60)
        
        file_grid.addWidget(self.summarize_context_threshold_check, 0, 0)
        file_grid.addWidget(lbl_f_thresh, 0, 1); file_grid.addWidget(self.summarize_context_threshold_spin, 0, 2)
        sg_layout.addLayout(file_grid)

        # 5. UI/Thinking (D-20260421-12)
        self.show_thinking_check = QCheckBox("Show Thinking Blocks")
        self.show_thinking_check.setStyleSheet("color: #00E5FF; font-size: 11px; font-weight: bold;")
        sg_layout.addWidget(self.show_thinking_check)

        layout.addWidget(summarizer_group)

        # Master Spinbox Styling — Added Cyan Accents (D-20260421-03)
        spin_style = """
            QSpinBox, QDoubleSpinBox {
                background: #111;
                color: #eee;
                border: 1px solid #333;
                border-radius: 3px;
                padding: 1px 4px;
                font-size: 11px;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border; subcontrol-position: top right;
                width: 14px; border-left: 1px solid #333; background: #1a1a1a;
                border-top-right-radius: 3px;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border; subcontrol-position: bottom right;
                width: 14px; border-left: 1px solid #333; background: #1a1a1a;
                border-bottom-right-radius: 3px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #222;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                image: none; border-left: 3px solid transparent; border-right: 3px solid transparent;
                border-bottom: 3px solid #00E5FF; width: 0; height: 0;
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                image: none; border-left: 3px solid transparent; border-right: 3px solid transparent;
                border-top: 3px solid #00E5FF; width: 0; height: 0;
            }
        """
        for spin in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            spin.setStyleSheet(spin_style)

        for combo in self.findChildren(QComboBox):
            if combo != self.profile_combo:
                combo.setStyleSheet("""
                    QComboBox { background: #1a1a1a; color: #eee; border: 1px solid #333; border-radius: 3px; padding: 1px 4px; font-size: 11px; }
                    QComboBox::drop-down { border: none; width: 14px; }
                    QComboBox::down-arrow {
                        image: none; border-left: 3px solid transparent; border-right: 3px solid transparent;
                        border-top: 3px solid #00E5FF; width: 0; height: 0;
                    }
                    QComboBox QAbstractItemView { background: #1a1a1a; color: #eee; selection-background-color: #333; }
                """)
        
        for lbl in self.findChildren(QLabel):
            if not lbl.styleSheet():
                lbl.setStyleSheet("color: #ccc; font-size: 11px;")

        self._section_label("LOOP STATE", layout)

        # Step indicators
        steps_frame = QFrame()
        steps_frame.setStyleSheet("background: #161616; border-radius: 6px;")
        sf_layout = QVBoxLayout(steps_frame)
        sf_layout.setContentsMargins(8, 8, 8, 8)
        sf_layout.setSpacing(4)

        for step in STEP_ORDER:
            ind = StepIndicator(step)
            self._indicators[step] = ind
            sf_layout.addWidget(ind)

        layout.addWidget(steps_frame)
        layout.addStretch(1)

        # Phase G (UPGRADE_PLAN_6 sec 2.c, D-20260427-02) -- the TRACE
        # tree was removed. The cognate runtime emits its observability
        # surface through the LogPanel + benchmark criteria; the tree
        # widget under LOOP STATE was redundant and visually heavy.
        # The `trace_event` signal on `lx_servo_thread.ServoCoreThread`
        # remains defined but unsubscribed -- emissions are no-ops.

        # Removed local background: #111 to allow global QMainWindow styling to propagate.

    def _section_label(self, text: str, layout: QVBoxLayout):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #aaa; font-size: 10px; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(lbl)
    
    def _sync_ranges(self):
        """Loads and applies numeric safety bounds from system_defaults.json."""
        bounds = get_system_defaults().get("bounds", {})
        if not bounds: return
        
        mapping = {
            "temperature":                         self.temp_spin,
            "max_tokens":                          self.tokens_spin,
            "conversation_history":                self.context_spin,
            "chain_limit":                         self.loop_limit_spin,
            "autonomous_loop_limit":               self.autonomous_limit_spin,
            "max_auto_continues":                  self.auto_continue_spin,
            "history_compression_trigger":         self.summarize_history_multiplier_spin,
            "history_compression_target_chars":    self.summarize_history_target_spin,
            "tool_result_compression_threshold":    self.summarize_tool_threshold_spin,
            "tool_result_compression_target_chars": self.summarize_tool_target_spin,
            "summarize_read_threshold":            self.summarize_context_threshold_spin,
            "hardware_throttle_threshold_enter":    self.throttle_enter_spin,
            "hardware_throttle_threshold_exit":     self.throttle_exit_spin,
        }
        
        for key, widget in mapping.items():
            if key in bounds:
                lo, hi = bounds[key]
                widget.setRange(lo, hi)

    # ── Slots ─────────────────────────

    @Slot(str)
    def on_step_changed(self, step: str):
        # Phase G (UPGRADE_PLAN_6 sec 2.a, D-20260427-02) -- with the
        # four-cognate vocabulary, OBSERVE is the cycle root. Anything
        # not in STEP_ORDER (e.g. legacy "PERCEIVE" / "CONTEXTUALIZE"
        # emissions from older traces) just leaves all indicators
        # inactive, which is the correct visual when the loop is
        # between recognized phases.
        for name, ind in self._indicators.items():
            ind.set_active(name == step)
