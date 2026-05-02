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

# Phase E (UPGRADE_PLAN_4 sec 6.2) -- read the eleven Phase D atomic
# primitives directly off ServoCore as a public frozenset. Iteration
# order is not part of the contract; we only test membership. Imported
# at module load so the badge logic in `_populate` doesn't pay an
# import cost per row.
try:
    from core.core import ServoCore as _ServoCore
    _ATOMIC_PRIMITIVES: frozenset = frozenset(getattr(_ServoCore, "ATOMIC_PRIMITIVES", ()))
except Exception:
    # Defensive: if core.core fails to import (e.g. partial install),
    # fall through to an empty set so the panel still renders.
    _ATOMIC_PRIMITIVES = frozenset()


# Phase G (UPGRADE_PLAN_6 sec 2.b, D-20260427-02) -- arrow glyphs used
# for the InstalledTools / Stream / Log toggle buttons. Defined as
# module-level literals so they don't need to be re-encoded inside the
# f-strings that build button labels (Python 3.10 disallows backslash
# escapes inside f-string expressions).
_ARROW_DOWN = "\u25BC"
_ARROW_RIGHT = "\u25B6"
_DOT_FILLED = "\u25CF"
_DOT_HOLLOW = "\u25CB"
_RELOAD_GLYPH = "\u21BA"
_FOLD_GLYPH = "\u00BB"


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

        reload_btn = QPushButton(_RELOAD_GLYPH)
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

        self.fold_btn = QPushButton(_FOLD_GLYPH)
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

        # Phase G (UPGRADE_PLAN_6 sec 2.b, D-20260427-02) -- INSTALLED
        # TOOLS now uses the same QPushButton + arrow toggle idiom as
        # Stream Viewer / Log Viewer below, replacing the heavier
        # `CollapsibleSection` wrapper. Color #4CAF50 (green) matches
        # the standalone-tool foreground in `_populate`, so the section
        # header reads as the same family as its contents.
        tools_container = QWidget()
        tc_layout = QVBoxLayout(tools_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(4)

        self.tools_toggle_btn = QPushButton(f"{_ARROW_DOWN} INSTALLED TOOLS")
        self.tools_toggle_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a;
                color: #4CAF50;
                border: 1px solid #2a2a2a;
                border-radius: 4px;
                padding: 6px;
                font-size: 11px;
                text-align: left;
                font-weight: bold;
                letter-spacing: 1px;
            }
            QPushButton:hover { background: #252525; color: #81C784; }
        """)
        self.tools_toggle_btn.clicked.connect(self._toggle_tools_ui)
        tc_layout.addWidget(self.tools_toggle_btn)

        self.tools_content = QWidget()
        tools_inner = QVBoxLayout(self.tools_content)
        tools_inner.setContentsMargins(0, 4, 0, 0)
        tools_inner.setSpacing(0)
        tools_inner.addWidget(self.tool_list)

        tc_layout.addWidget(self.tools_content)
        layout.addWidget(tools_container, 1)


        # Stream container
        stream_container = QWidget()
        sc_layout = QVBoxLayout(stream_container)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(4)

        self.stream_toggle_btn = QPushButton(f"{_ARROW_RIGHT} Stream Viewer")
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

        self.log_toggle_btn = QPushButton(f"{_ARROW_RIGHT} Log Viewer")
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

    # ---- Population --------------------------

    def _populate(self):
        current_name = None
        if self.tool_list.currentItem():
            current_name = self.tool_list.currentItem().data(Qt.UserRole)

        self.tool_list.blockSignals(True)
        self.tool_list.clear()

        item_to_select = None
        for name, tool in self.registry.get_all_tools().items():
            enabled   = tool["enabled"]
            is_system = tool.get("is_system", False)

            # Color logic (D-20260421-22): Yellow for System, Green for Standalone
            if not enabled:
                color = "#555"
            elif is_system:
                color = "#FFD600"  # High-visibility Yellow
            else:
                color = "#4CAF50"  # Standard Green

            # Phase E (UPGRADE_PLAN_4 sec 6.2) -- mark rows whose tool
            # name is in ServoCore.ATOMIC_PRIMITIVES with a leading
            # "[A]" badge so the dispatch surface is visible at a
            # glance. Eleven rows under default Phase D registry.
            atomic_badge = "[A] " if name in _ATOMIC_PRIMITIVES else "    "
            dot = _DOT_FILLED if enabled else _DOT_HOLLOW
            item = QListWidgetItem(f"{dot}  {atomic_badge}{name}")
            item.setData(Qt.UserRole, name)
            item.setForeground(QColor(color))

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

    # ---- Slots --------------------------

    @Slot(QListWidgetItem)
    def _on_item_clicked(self, item):
        if not item:
            return
        name = item.data(Qt.UserRole)

        # 1. Diagnostic Quick-Actions
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

    def _toggle_tools_ui(self):
        visible = not self.tools_content.isVisible()
        self.tools_content.setVisible(visible)
        arrow = _ARROW_DOWN if visible else _ARROW_RIGHT
        self.tools_toggle_btn.setText(f"{arrow} INSTALLED TOOLS")

    def _toggle_stream_ui(self):
        visible = not self.stream_content.isVisible()
        self.stream_content.setVisible(visible)
        arrow = _ARROW_DOWN if visible else _ARROW_RIGHT
        self.stream_toggle_btn.setText(f"{arrow} Stream Viewer")

    def _toggle_log_ui(self):
        visible = not self.log_content.isVisible()
        self.log_content.setVisible(visible)
        arrow = _ARROW_DOWN if visible else _ARROW_RIGHT
        self.log_toggle_btn.setText(f"{arrow} Log Viewer")

    # Listener for `ServoCoreThread.tool_dispatched(tool_name)`.
    # Highlights the matching row in `tool_list` so the user sees
    # which atomic primitive lx_Act just selected.
    @Slot(str)
    def on_tool_dispatched(self, tool_name: str):
        if not tool_name:
            return
        try:
            for i in range(self.tool_list.count()):
                item = self.tool_list.item(i)
                if item is None:
                    continue
                if str(item.data(Qt.UserRole) or "") == str(tool_name):
                    self.tool_list.setCurrentItem(item)
                    break
        except Exception:
            # Row highlight is purely cosmetic -- a failure here must
            # not propagate into the Servo dispatch path.
            pass



    @Slot()
    def on_stream_started(self):
        self.stream_output.clear()

    @Slot(str)
    def on_stream_chunk(self, chunk: str):
        self.stream_output.moveCursor(QTextCursor.End)
        self.stream_output.insertPlainText(chunk)
        self.stream_output.moveCursor(QTextCursor.End)
