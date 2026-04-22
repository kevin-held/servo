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
from gui.components import CollapsibleSection




class ToolPanel(QWidget):

    tool_changed = Signal()             # emitted when tools are modified / reloaded
    fold_requested = Signal()           # emitted when fold button is clicked
    tool_execute_requested = Signal(str, dict) # name, args

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

        reload_btn = QPushButton("↺")
        reload_btn.setFixedWidth(28)
        reload_btn.setToolTip("Reload all tools from disk")
        reload_btn.setStyleSheet("""
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
        reload_btn.clicked.connect(self._reload_all)
        header.addWidget(reload_btn)

        self.fold_btn = QPushButton("»")
        self.fold_btn.setFixedWidth(28)
        self.fold_btn.setToolTip("Collapse Tool Panel")
        self.fold_btn.setStyleSheet("""
            QPushButton {
                background: #1e1e1e;
                color: #00E5FF;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background: #252525; border-color: #00E5FF; }
        """)
        self.fold_btn.clicked.connect(lambda: self.fold_requested.emit())
        header.addWidget(self.fold_btn)

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
        self.tool_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tool_list.itemClicked.connect(self._on_item_clicked)
        
        self.sec_tools = CollapsibleSection("INSTALLED TOOLS", "#888")
        self.sec_tools.set_widget(self.tool_list)
        layout.addWidget(self.sec_tools, 1)


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
            
            if name in ("context_dump", "system_config"):
                item.setToolTip(f"Click to run default {name} call")
                # Visual cue for interactivity
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            
            self.tool_list.addItem(item)
            if name == current_name:
                item_to_select = item

        self.tool_list.blockSignals(False)
        if item_to_select:
            self.tool_list.setCurrentItem(item_to_select)

    # ── Slots ─────────────────────────────────────

    @Slot(QListWidgetItem)
    def _on_item_clicked(self, item):
        if not item:
            return
        name = item.data(Qt.UserRole)
        
        # 1. Surgical Quick-Actions
        if name == "context_dump":
            # show_user=true, pause_loop=false
            self.tool_execute_requested.emit(name, {"show_user": True, "pause_loop": False})
        elif name == "system_config":
            # default empty args runs a dump
            self.tool_execute_requested.emit(name, {})
        
        # 2. General selection behavior
        self._on_selected(item, None)

    @Slot()
    def _on_selected(self, current, previous):
        if not current:
            return
        name = current.data(Qt.UserRole)
        # In observation mode: only update internal state if needed
        # (Future: could update a Tool Info view here)


    def _reload_all(self):
        self.registry.load_all()
        self._populate()
        self.tool_changed.emit()

    def _toggle_stream_ui(self):
        visible = not self.stream_content.isVisible()
        self.stream_content.setVisible(visible)
        self.stream_toggle_btn.setText("▼ Stream Viewer" if visible else "▶ Stream Viewer")



    def _toggle_log_ui(self):
        visible = not self.log_content.isVisible()
        self.log_content.setVisible(visible)
        self.log_toggle_btn.setText("▼ Log Viewer" if visible else "▶ Log Viewer")



    @Slot()
    def on_stream_started(self):
        self.stream_output.clear()
        
    @Slot(str)
    def on_stream_chunk(self, chunk: str):
        self.stream_output.moveCursor(QTextCursor.End)
        self.stream_output.insertPlainText(chunk)
        self.stream_output.moveCursor(QTextCursor.End)
