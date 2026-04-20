from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTreeWidget, QTreeWidgetItem, QFrame,
    QSpinBox, QDoubleSpinBox, QComboBox, QGridLayout,
    QCheckBox, QPushButton
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QColor

from core.loop import LoopStep


STEP_COLORS = {
    LoopStep.PERCEIVE:      "#4CAF50",
    LoopStep.CONTEXTUALIZE: "#2196F3",
    LoopStep.REASON:        "#FF9800",
    LoopStep.ACT:           "#F44336",
    LoopStep.INTEGRATE:     "#9C27B0",
    LoopStep.OBSERVE:       "#546E7A",
}

STEP_ORDER = [
    LoopStep.PERCEIVE,
    LoopStep.CONTEXTUALIZE,
    LoopStep.REASON,
    LoopStep.ACT,
    LoopStep.INTEGRATE,
    LoopStep.OBSERVE,
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
        self._indicators:           dict              = {}
        self._current_cycle_item:   QTreeWidgetItem   = None
        self._step_group_items:     dict              = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._section_label("SYSTEM CONTROLS", layout)

        # Stop & Continuous Row
        mode_layout = QGridLayout()
        mode_layout.setSpacing(8)
        
        self.continuous_check = QCheckBox("Continuous Mode")
        self.continuous_check.setStyleSheet("color: #FF5722; font-size: 11px; font-weight: bold;")
        self.continuous_check.toggled.connect(self._on_continuous_toggled)
        
        self.stop_btn = QPushButton("STOP SEQUENCE")
        self.stop_btn.setFixedHeight(24)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #D32F2F; color: white; border-radius: 4px; font-weight: bold; font-size: 10px; letter-spacing: 1px;
            }
            QPushButton:hover { background: #F44336; }
        """)
        mode_layout.addWidget(self.continuous_check, 0, 0)
        mode_layout.addWidget(self.stop_btn, 0, 1)
        layout.addLayout(mode_layout)

        controls_frame = QFrame()
        controls_frame.setStyleSheet("background: #161616; border-radius: 6px;")
        cf_layout = QVBoxLayout(controls_frame)
        cf_layout.setContentsMargins(8, 8, 8, 8)
        cf_layout.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(8)

        lbl = QLabel("Conversation History:")
        lbl.setStyleSheet("color: #888; font-size: 11px;")
        self.context_spin = QSpinBox()
        self.context_spin.setRange(1, 20)
        self.context_spin.setValue(5)
        self.context_spin.setStyleSheet("background: #222; color: #ccc; border: 1px solid #333;")

        lbl2 = QLabel("Temperature:")
        lbl2.setStyleSheet("color: #888; font-size: 11px;")
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.6)
        self.temp_spin.setStyleSheet("background: #222; color: #ccc; border: 1px solid #333;")
        
        lbl3 = QLabel("Max Tokens:")
        lbl3.setStyleSheet("color: #888; font-size: 11px;")
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(128, 8192)
        self.tokens_spin.setSingleStep(256)
        self.tokens_spin.setValue(2048)
        self.tokens_spin.setStyleSheet("background: #222; color: #ccc; border: 1px solid #333;")

        lbl4 = QLabel("Verbosity:")
        lbl4.setStyleSheet("color: #888; font-size: 11px;")
        self.verbosity_combo = QComboBox()
        self.verbosity_combo.addItems(["Concise", "Normal", "Detailed"])
        self.verbosity_combo.setCurrentText("Normal")
        self.verbosity_combo.setStyleSheet("background: #222; color: #ccc; border: 1px solid #333;")

        lbl5 = QLabel("Chain Limit:")
        lbl5.setStyleSheet("color: #888; font-size: 11px;")
        self.loop_limit_spin = QSpinBox()
        self.loop_limit_spin.setRange(1, 10)
        self.loop_limit_spin.setValue(3)
        self.loop_limit_spin.setStyleSheet("background: #222; color: #ccc; border: 1px solid #333;")

        grid.addWidget(lbl, 0, 0)
        grid.addWidget(self.context_spin, 0, 1)
        grid.addWidget(lbl2, 1, 0)
        grid.addWidget(self.temp_spin, 1, 1)
        grid.addWidget(lbl3, 2, 0)
        grid.addWidget(self.tokens_spin, 2, 1)
        grid.addWidget(lbl4, 3, 0)
        grid.addWidget(self.verbosity_combo, 3, 1)
        grid.addWidget(lbl5, 4, 0)
        grid.addWidget(self.loop_limit_spin, 4, 1)

        cf_layout.addLayout(grid)
        layout.addWidget(controls_frame)

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

        self._section_label("TRACE", layout)

        # Trace tree
        self.trace_tree = QTreeWidget()
        self.trace_tree.setHeaderHidden(True)
        self.trace_tree.setIndentation(14)
        self.trace_tree.setAnimated(True)
        self.trace_tree.setStyleSheet("""
            QTreeWidget {
                background: #161616;
                color: #bbb;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                font-family: Consolas, monospace;
            }
            QTreeWidget::item { padding: 2px 4px; }
            QTreeWidget::item:hover { background: #222; }
            QTreeWidget::item:selected { background: #1e2a1e; }
            QTreeWidget::branch { background: #161616; }
        """)
        layout.addWidget(self.trace_tree)

        self.setStyleSheet("QWidget { background: #111; }")

    def _section_label(self, text: str, layout: QVBoxLayout):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color: #888; font-size: 10px; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(lbl)

    # ── Slots ─────────────────────────────────────

    @Slot(str)
    def on_step_changed(self, step: str):
        for name, ind in self._indicators.items():
            ind.set_active(name == step)

        if step == LoopStep.PERCEIVE:
            # New cycle — new root item in trace
            cycle_num = self.trace_tree.topLevelItemCount() + 1
            self._current_cycle_item = QTreeWidgetItem(
                self.trace_tree, [f"Cycle {cycle_num}"]
            )
            self._current_cycle_item.setForeground(0, QColor("#555"))
            self._current_cycle_item.setExpanded(True)
            self._step_group_items = {}
            self.trace_tree.scrollToItem(self._current_cycle_item)

    @Slot(str, str)
    def on_trace_event(self, step: str, message: str):
        if self._current_cycle_item is None:
            return

        color = STEP_COLORS.get(step, "#546E7A")

        # Get or create step group
        if step not in self._step_group_items:
            group = QTreeWidgetItem(self._current_cycle_item, [step])
            group.setForeground(0, QColor(color))
            group.setExpanded(True)
            self._step_group_items[step] = group
        else:
            group = self._step_group_items[step]

        msg_item = QTreeWidgetItem(group, [message])
        msg_item.setForeground(0, QColor("#888"))
        self.trace_tree.scrollToItem(msg_item)

    @Slot(str, str, str)
    def on_tool_called(self, tool_name: str, args: str, result: str):
        if self._current_cycle_item is None:
            return
        tool_item = QTreeWidgetItem(self._current_cycle_item, [f"⚡  {tool_name}"])
        tool_item.setForeground(0, QColor("#FFD700"))
        QTreeWidgetItem(tool_item, [f"args   → {args[:100]}"]).setForeground(
            0, QColor("#777")
        )
        QTreeWidgetItem(tool_item, [f"result → {result[:100]}"]).setForeground(
            0, QColor("#777")
        )
        tool_item.setExpanded(True)


    @Slot(bool)
    def _on_continuous_toggled(self, checked: bool):
        self.loop_limit_spin.setEnabled(not checked)
        if checked:
            self.loop_limit_spin.setStyleSheet("background: #111; color: #555; border: 1px solid #222;")
        else:
            self.loop_limit_spin.setStyleSheet("background: #222; color: #ccc; border: 1px solid #333;")
