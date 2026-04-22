from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QScrollArea, QPushButton, QTextEdit, 
    QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor

from gui.components import CollapsibleSection

class ContextViewerWindow(QMainWindow):
    """Pop-out window for inspecting the agent's context and system state."""
    
    closed = Signal()

    def __init__(self, history: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Surgical Context Viewer")
        self.setMinimumSize(1000, 1000)
        
        self.history = history
        # Start at the latest snapshot (end of list)
        self.current_idx = len(history) - 1
        
        # Cyber-theme styling
        self.setStyleSheet("QMainWindow { background: #050505; }")

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # -- TITLE ROW --
        title_row = QHBoxLayout()
        icon_lbl = QLabel("👁️")
        icon_lbl.setStyleSheet("font-size: 24px;")
        name_lbl = QLabel("CONTEXT TELEMETRY")
        name_lbl.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 16px; letter-spacing: 4px;")
        title_row.addWidget(icon_lbl)
        title_row.addWidget(name_lbl)
        title_row.addStretch()
        
        self.ts_lbl = QLabel("")
        self.ts_lbl.setStyleSheet("color: #666; font-family: monospace; font-size: 10px;")
        title_row.addWidget(self.ts_lbl)
        layout.addLayout(title_row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: #222;")
        layout.addWidget(line)

        # -- NAVIGATION (v1.3.3) --
        nav_row = QHBoxLayout()
        self.prev_btn = QPushButton("◀  PREVIOUS")
        self.next_btn = QPushButton("NEXT  ▶")
        self.step_lbl = QLabel("Step 0 of 0")
        
        btn_style = """
            QPushButton { 
                background: #111; color: #00E5FF; border: 1px solid #333; border-radius: 4px; padding: 4px 12px; font-weight: bold; font-size: 10px;
            }
            QPushButton:hover { background: #1a1a1a; border-color: #00E5FF; }
            QPushButton:disabled { color: #444; border-color: #222; }
        """
        self.prev_btn.setStyleSheet(btn_style)
        self.next_btn.setStyleSheet(btn_style)
        self.step_lbl.setStyleSheet("color: #FF9800; font-family: monospace; font-size: 11px; font-weight: bold; padding: 0 10px;")
        
        nav_row.addWidget(self.prev_btn)
        nav_row.addStretch()
        nav_row.addWidget(self.step_lbl)
        nav_row.addStretch()
        nav_row.addWidget(self.next_btn)
        layout.addLayout(nav_row)

        self.prev_btn.clicked.connect(self._go_prev)
        self.next_btn.clicked.connect(self._go_next)

        # -- SCROLLABLE AREA --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.scroll_layout.setSpacing(15)

        # -- SECTIONS --

        # 1. System Prompt
        self.sec_prompt = CollapsibleSection("SYSTEM PROMPT", "#FF9800")
        self.scroll_layout.addWidget(self.sec_prompt, 1)
        
        # 2. Conversation History
        self.sec_history = CollapsibleSection("CONVERSATION HISTORY", "#2196F3")
        self.scroll_layout.addWidget(self.sec_history, 1)

        # 3. Active Tasks
        self.sec_tasks = CollapsibleSection("TASK LEDGER", "#9C27B0")
        self.scroll_layout.addWidget(self.sec_tasks, 1)

        # 4. System Sensors & Health
        self.sec_health = CollapsibleSection("SYSTEM TELEMETRY", "#4CAF50")
        self.scroll_layout.addWidget(self.sec_health, 1)

        # 5. Working Memory
        self.sec_memory = CollapsibleSection("WORKING MEMORY", "#F44336")
        self.scroll_layout.addWidget(self.sec_memory, 1)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # -- FOOTER ACTIONS --
        footer = QHBoxLayout()
        self.resume_btn = QPushButton("RESUME LOOP")
        self.resume_btn.setFixedHeight(40)
        self.resume_btn.setStyleSheet("""
            QPushButton {
                background: #00E5FF;
                color: black;
                font-weight: bold;
                font-size: 14px;
                letter-spacing: 2px;
                border-radius: 6px;
            }
            QPushButton:hover { background: #00B8D4; }
            QPushButton:pressed { background: #00838F; }
        """)
        footer.addWidget(self.resume_btn, 1)
        layout.addLayout(footer)

        # Populate
        self._update_display()

    def _go_prev(self):
        if self.current_idx > 0:
            self.current_idx -= 1
            self._update_display()

    def _go_next(self):
        if self.current_idx < len(self.history) - 1:
            self.current_idx += 1
            self._update_display()

    def _update_display(self):
        if not self.history:
            return
        
        data = self.history[self.current_idx]
        self._populate(data)
        
        # Navigation status
        total = len(self.history)
        current = self.current_idx + 1
        diff = total - current
        
        status = f"Step {current} of {total}"
        if diff > 0:
            status += f" (T-minus {diff})"
        else:
            status += " (LIVE)"
        
        self.step_lbl.setText(status)
        self.prev_btn.setEnabled(self.current_idx > 0)
        self.next_btn.setEnabled(self.current_idx < total - 1)
        
        ts = data.get("health_payload", {}).get("timestamp_utc", "Unknown")
        self.ts_lbl.setText(f"Snapshot: {ts[:19].replace('T', ' ')}")

    def _populate(self, data: dict):
        ctx = data.get("active_context", {})
        health = data.get("health_payload", {})
        
        import json
        
        # 1. System Prompt
        prompt = ctx.get("_rendered_system_prompt", "(System prompt not yet rendered for this turn)")
        self.sec_prompt.set_text(prompt)
        
        # 2. History (Rendered Messages)
        messages = ctx.get("_rendered_messages", [])
        hist_text = ""
        for m in messages:
            role = m.get('role', 'unknown').upper()
            content = m.get('content', '')
            hist_text += f"[{role}]\n{content}\n"
            hist_text += "-"*40 + "\n"
        
        if not hist_text:
            # Fallback to raw history if rendering failed
            hist = ctx.get("history", [])
            for t in hist:
                hist_text += f"[{t.get('role', 'unknown').upper()}] {t.get('content', '')}\n"
                hist_text += "-"*40 + "\n"

        self.sec_history.set_text(hist_text if hist_text else "(No history found)")

        # 3. Tasks
        tasks = ctx.get("tasks", [])
        tasks_text = json.dumps(tasks, indent=2) if tasks else "(No active tasks)"
        self.sec_tasks.set_text(tasks_text)

        # 4. Telemetry
        tele_text = json.dumps(health.get("system_health", {}), indent=2)
        self.sec_health.set_text(tele_text)

        # 5. Memory
        mem = health.get("working_memory_summary", "")
        self.sec_memory.set_text(mem if mem else "(Empty)")

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
