from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPlainTextEdit,
    QPushButton, QCheckBox, QInputDialog, QSplitter,
    QSizePolicy, QAbstractScrollArea
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCursor

from core.tool_registry import ToolRegistry
from gui.log_panel import LogPanel


NEW_TOOL_TEMPLATE = '''\
TOOL_NAME        = "{name}"
TOOL_DESCRIPTION = "Describe what this tool does"
TOOL_ENABLED     = True
TOOL_SCHEMA      = {{
    "param": {{"type": "string", "description": "A parameter"}},
}}


def execute(param: str) -> str:
    # Your implementation here
    return f"Result: {{param}}"
'''


class ToolPanel(QWidget):

    tool_changed = Signal()   # emitted when tools are modified / reloaded

    def __init__(self, registry: ToolRegistry):
        super().__init__()
        self.registry = registry
        self._build_ui()
        self._populate()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        lbl = QLabel("TOOLS")
        lbl.setStyleSheet(
            "color: #444; font-size: 10px; font-weight: bold; letter-spacing: 2px;"
        )
        header.addWidget(lbl)
        header.addStretch()

        add_btn = QPushButton("+ New")
        add_btn.setFixedWidth(58)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #1e1e1e;
                color: #888;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 11px;
            }
            QPushButton:hover { background: #252525; color: #ccc; }
        """)
        add_btn.clicked.connect(self._add_tool)
        header.addWidget(add_btn)

        reload_btn = QPushButton("↺")
        reload_btn.setFixedWidth(28)
        reload_btn.setToolTip("Reload all tools from disk")
        reload_btn.setStyleSheet(add_btn.styleSheet())
        reload_btn.clicked.connect(self._reload_all)
        header.addWidget(reload_btn)

        layout.addLayout(header)

        # Tool list
        self.tool_list = QListWidget()
        self.tool_list.setStyleSheet("""
            QListWidget {
                background: #161616;
                color: #ccc;
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-family: Consolas, monospace;
            }
            QListWidget::item { padding: 6px 10px; }
            QListWidget::item:selected { background: #1e2a1e; color: white; }
            QListWidget::item:hover { background: #1e1e1e; }
        """)
        self.tool_list.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self.tool_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.tool_list.currentItemChanged.connect(self._on_selected)
        layout.addWidget(self.tool_list)

        # Editor area container
        editor_widget = QWidget()
        editor_main_layout = QVBoxLayout(editor_widget)
        editor_main_layout.setContentsMargins(0, 0, 0, 0)
        editor_main_layout.setSpacing(4)
        
        self.toggle_editor_btn = QPushButton("▶ Tool Editor")
        self.toggle_editor_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a;
                color: #aaa;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                text-align: left;
                font-weight: bold;
            }
            QPushButton:hover { background: #252525; color: #ddd; }
        """)
        self.toggle_editor_btn.clicked.connect(self._toggle_editor)
        editor_main_layout.addWidget(self.toggle_editor_btn)

        # Inner content that collapses
        self.editor_content = QWidget()
        editor_layout = QVBoxLayout(self.editor_content)
        editor_layout.setContentsMargins(0, 4, 0, 0)
        editor_layout.setSpacing(6)

        # Controls row
        controls = QHBoxLayout()
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setStyleSheet("color: #888; font-size: 11px;")
        self.enabled_check.stateChanged.connect(self._toggle_enabled)
        controls.addWidget(self.enabled_check)
        controls.addStretch()

        self.save_btn = QPushButton("Save")
        self.save_btn.setFixedWidth(58)
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background: #1565C0;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
            QPushButton:hover   { background: #1976D2; }
            QPushButton:disabled { background: #1e1e1e; color: #444; }
        """)
        self.save_btn.clicked.connect(self._save_tool)
        controls.addWidget(self.save_btn)
        editor_layout.addLayout(controls)

        # Code editor
        self.code_editor = QPlainTextEdit()
        self.code_editor.setStyleSheet("""
            QPlainTextEdit {
                background: #161616;
                color: #ddd;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)
        self.code_editor.textChanged.connect(lambda: self.save_btn.setEnabled(True))
        editor_layout.addWidget(self.code_editor)
        
        editor_main_layout.addWidget(self.editor_content)
        self.editor_content.setVisible(False)  # Collapsed by default
        
        layout.addWidget(editor_widget)

        # Stream container
        stream_container = QWidget()
        sc_layout = QVBoxLayout(stream_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(4)
        
        self.stream_toggle_btn = QPushButton("▶ Stream Viewer")
        self.stream_toggle_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a;
                color: #aaa;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                text-align: left;
                font-weight: bold;
            }
            QPushButton:hover { background: #252525; color: #ddd; }
        """)
        self.stream_toggle_btn.clicked.connect(self._toggle_stream_ui)
        sc_layout.addWidget(self.stream_toggle_btn)

        self.stream_content = QWidget()
        stream_layout = QVBoxLayout(self.stream_content)
        stream_layout.setContentsMargins(0, 4, 0, 0)
        stream_layout.setSpacing(6)

        stream_controls = QHBoxLayout()
        stream_controls.setContentsMargins(0, 0, 0, 0)
        self.stream_enabled_check = QCheckBox("Enable Live Streaming")
        self.stream_enabled_check.setStyleSheet("color: #888; font-size: 11px;")
        stream_controls.addWidget(self.stream_enabled_check)
        stream_controls.addStretch()
        
        stream_controls_widget = QWidget()
        stream_controls_widget.setLayout(stream_controls)
        stream_layout.addWidget(stream_controls_widget)

        self.stream_output = QPlainTextEdit()
        self.stream_output.setReadOnly(True)
        self.stream_output.setFixedHeight(120)
        self.stream_output.setStyleSheet("""
            QPlainTextEdit {
                background: #161616;
                color: #888;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                padding: 8px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        stream_layout.addWidget(self.stream_output)
        
        sc_layout.addWidget(self.stream_content)
        self.stream_content.setVisible(False)
        layout.addWidget(stream_container)

        # Log Viewer container
        log_container = QWidget()
        lc_layout = QVBoxLayout(log_container)
        lc_layout.setContentsMargins(0, 0, 0, 0)
        lc_layout.setSpacing(4)

        self.log_toggle_btn = QPushButton("▶ Log Viewer")
        self.log_toggle_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a;
                color: #FF5722;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                text-align: left;
                font-weight: bold;
            }
            QPushButton:hover { background: #252525; color: #FF8A65; }
        """)
        self.log_toggle_btn.clicked.connect(self._toggle_log_ui)
        lc_layout.addWidget(self.log_toggle_btn)

        self.log_content = QWidget()
        log_inner = QVBoxLayout(self.log_content)
        log_inner.setContentsMargins(0, 4, 0, 0)
        log_inner.setSpacing(4)

        self.log_panel = LogPanel()
        log_inner.addWidget(self.log_panel)

        lc_layout.addWidget(self.log_content)
        self.log_content.setVisible(False)
        layout.addWidget(log_container)

        # Goal Tracker container
        goal_container = QWidget()
        gc_layout = QVBoxLayout(goal_container)
        gc_layout.setContentsMargins(0, 0, 0, 0)
        gc_layout.setSpacing(4)
        
        self.goal_toggle_btn = QPushButton("▶ Target Goals")
        self.goal_toggle_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a;
                color: #FFC107;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                text-align: left;
                font-weight: bold;
            }
            QPushButton:hover { background: #252525; color: #FFE082; }
        """)
        self.goal_toggle_btn.clicked.connect(self._toggle_goal_ui)
        gc_layout.addWidget(self.goal_toggle_btn)

        self.goal_content = QWidget()
        goal_inner = QVBoxLayout(self.goal_content)
        goal_inner.setContentsMargins(0, 4, 0, 0)
        goal_inner.setSpacing(4)
        
        self.goal_list = QListWidget()
        self.goal_list.setFixedHeight(120)
        self.goal_list.setStyleSheet("""
            QListWidget {
                background: #161616;
                color: #ccc;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                font-size: 11px;
            }
            QListWidget::item { padding: 4px 6px; border-bottom: 1px solid #222; }
        """)
        goal_inner.addWidget(self.goal_list)
        
        gc_layout.addWidget(self.goal_content)
        self.goal_content.setVisible(False)
        layout.addWidget(goal_container)

        layout.addStretch(1)

        self.setStyleSheet("QWidget { background: #111; }")

    # ── Population ────────────────────────────────

    def _populate(self):
        current_name = None
        if self.tool_list.currentItem():
            current_name = self.tool_list.currentItem().data(Qt.UserRole)

        self.tool_list.blockSignals(True)
        self.tool_list.clear()

        item_to_select = None
        for name, tool in self.registry.get_all_tools().items():
            enabled = tool["enabled"]
            item    = QListWidgetItem(f"{'●' if enabled else '○'}  {name}")
            item.setData(Qt.UserRole, name)
            item.setForeground(QColor("#4CAF50" if enabled else "#555"))
            self.tool_list.addItem(item)
            if name == current_name:
                item_to_select = item

        self.tool_list.blockSignals(False)
        if item_to_select:
            self.tool_list.setCurrentItem(item_to_select)

    # ── Slots ─────────────────────────────────────

    @Slot()
    def _on_selected(self, current, previous):
        if not current:
            return
        name = current.data(Qt.UserRole)
        tools = self.registry.get_all_tools()
        if name in tools:
            code = self.registry.get_tool_code(name)
            self.code_editor.blockSignals(True)
            self.code_editor.setPlainText(code)
            self.code_editor.blockSignals(False)
            self.enabled_check.blockSignals(True)
            self.enabled_check.setChecked(tools[name]["enabled"])
            self.enabled_check.blockSignals(False)
            self.save_btn.setEnabled(False)

    def _toggle_enabled(self, state):
        item = self.tool_list.currentItem()
        if not item:
            return
        self.registry.set_enabled(item.data(Qt.UserRole), bool(state))
        self._populate()
        self.tool_changed.emit()

    def _save_tool(self):
        item = self.tool_list.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        code = self.code_editor.toPlainText()
        self.registry.save_tool_code(name, code)
        self.save_btn.setEnabled(False)
        self._populate()
        self.tool_changed.emit()

    def _add_tool(self):
        name, ok = QInputDialog.getText(self, "New Tool", "Tool name (snake_case):")
        if not (ok and name.strip()):
            return
        name = name.strip().lower().replace(" ", "_")
        code = NEW_TOOL_TEMPLATE.format(name=name)
        self.registry.create_tool(name, code)
        self._populate()
        # Select the new tool
        for i in range(self.tool_list.count()):
            it = self.tool_list.item(i)
            if it.data(Qt.UserRole) == name:
                self.tool_list.setCurrentItem(it)
                break
        self.tool_changed.emit()

    def _reload_all(self):
        self.registry.load_all()
        self._populate()
        self.tool_changed.emit()

    def _toggle_editor(self):
        visible = not self.editor_content.isVisible()
        self.editor_content.setVisible(visible)
        self.toggle_editor_btn.setText("▼ Tool Editor" if visible else "▶ Tool Editor")

    def _toggle_stream_ui(self):
        visible = not self.stream_content.isVisible()
        self.stream_content.setVisible(visible)
        self.stream_toggle_btn.setText("▼ Stream Viewer" if visible else "▶ Stream Viewer")

    def _toggle_goal_ui(self):
        visible = not self.goal_content.isVisible()
        self.goal_content.setVisible(visible)
        self.goal_toggle_btn.setText("▼ Target Goals" if visible else "▶ Target Goals")

    def _toggle_log_ui(self):
        visible = not self.log_content.isVisible()
        self.log_content.setVisible(visible)
        self.log_toggle_btn.setText("▼ Log Viewer" if visible else "▶ Log Viewer")

    @Slot(object)
    def on_goals_changed(self, goals: dict):
        self.goal_list.clear()
        if not goals:
            return
            
        # Priority 1: Finite
        for name, meta in goals.items():
            if meta.get("type") == "finite":
                item = QListWidgetItem(f"★ {name}\n  └ {meta.get('description')}")
                item.setForeground(QColor("#4CAF50")) # Bright green
                item.setBackground(QColor("#1e2e1e")) # Subtle green backing to highlight priority
                self.goal_list.addItem(item)
                
        # Priority 2: Continuous
        for name, meta in goals.items():
            if meta.get("type") == "continuous":
                item = QListWidgetItem(f"∞ {name}\n  └ {meta.get('description')}")
                item.setForeground(QColor("#546E7A")) # Subdued blue-grey
                self.goal_list.addItem(item)

    @Slot()
    def on_stream_started(self):
        self.stream_output.clear()
        
    @Slot(str)
    def on_stream_chunk(self, chunk: str):
        self.stream_output.moveCursor(QTextCursor.End)
        self.stream_output.insertPlainText(chunk)
        self.stream_output.moveCursor(QTextCursor.End)
