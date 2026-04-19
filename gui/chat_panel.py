import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QHBoxLayout, QLabel,
    QFileDialog
)
from PySide6.QtCore import Qt, Signal, Slot, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QFont, QTextCursor, QImage

class ChatPanel(QWidget):

    input_submitted = Signal(str, str)

    # Role-based identity — maps the active role key to a role title + accent color
    # Role keys are set by the core loop based on which continuous goal is due.
    _ROLE_MAP = {
        "servo":        ("Servo",        "#2196F3"),
        "sentinel":     ("Sentinel",     "#FF5722"),
        "scholar":      ("Scholar",      "#9C27B0"),
        "architect":    ("Architect",    "#00BCD4"),
        "analyst":      ("Analyst",      "#E91E63"),
        "orchestrator": ("Orchestrator", "#FF9800"),
        "guardian":     ("Guardian",     "#4CAF50"),
    }
    _DEFAULT_ROLE = ("Servo", "#2196F3")

    def __init__(self):
        super().__init__()
        self._last_assistant_response = ""
        self._attached_image_b64 = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        lbl = QLabel("CONVERSATION")
        lbl.setStyleSheet(
            "color: #888; font-size: 10px; font-weight: bold; letter-spacing: 2px;"
        )
        layout.addWidget(lbl)

        # Output
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet("""
            QTextEdit {
                background: #161616;
                color: #ddd;
                border: none;
                border-radius: 6px;
                padding: 14px;
                font-size: 13px;
                line-height: 1.6;
            }
        """)
        self.output.setFont(QFont("Segoe UI", 12))
        layout.addWidget(self.output)

        # Input row
        row = QHBoxLayout()
        row.setSpacing(8)

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Message…")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background: #1a1a1a;
                color: #ddd;
                border: 1px solid #2a2a2a;
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 13px;
            }
            QLineEdit:focus { border-color: #4CAF50; }
        """)
        self.input_field.returnPressed.connect(self._submit)

        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedWidth(80)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover    { background: #43A047; }
            QPushButton:pressed  { background: #388E3C; }
            QPushButton:disabled { background: #1e1e1e; color: #444; }
        """)
        self.send_btn.clicked.connect(self._submit)

        self.chain_btn = QPushButton("↻")
        self.chain_btn.setFixedWidth(100)
        self.chain_btn.setEnabled(False)
        self.chain_btn.setToolTip("Submit the last Assistant response as the next input to forcefully chain a tool block.")
        self.chain_btn.setStyleSheet("""
            QPushButton {
                background: #1976D2;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover    { background: #1565C0; }
            QPushButton:pressed  { background: #0D47A1; }
            QPushButton:disabled { background: #1e1e1e; color: #444; }
        """)
        self.chain_btn.clicked.connect(self._force_chain)

        self.attach_btn = QPushButton("📎")
        self.attach_btn.setFixedWidth(40)
        self.attach_btn.setToolTip("Attach Image")
        self.attach_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: #aaa; border: none; border-radius: 6px; font-size: 16px;
            }
            QPushButton:hover { background: #333; }
        """)
        self.attach_btn.clicked.connect(self._attach_image)

        row.addWidget(self.attach_btn)
        row.addWidget(self.input_field)
        row.addWidget(self.chain_btn)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

        # Overlay indicator — shows which persona overlay is currently active.
        # Defaults to "servo" (the no-overlay identity) and updates on each
        # response or explicit active-role change.
        self.overlay_label = QLabel("● servo")
        self.overlay_label.setStyleSheet(
            "color: #2196F3; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; padding: 2px 0 0 4px;"
        )
        self.overlay_label.setToolTip(
            "Active persona overlay. Servo is the no-overlay default identity; "
            "other overlays modulate voice and emphasis for scheduled role tasks."
        )
        layout.addWidget(self.overlay_label)

        self.setStyleSheet("QWidget { background: #111; }")

    # ── Private ───────────────────────────────────

    def _attach_image(self):
        import base64
        path, _ = QFileDialog.getOpenFileName(self, "Attach Image", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return
            
        img = QImage(path)
        if img.isNull():
            return
            
        # Scale to max 1024x1024 to save memory/tokens
        if img.width() > 1024 or img.height() > 1024:
            img = img.scaled(1024, 1024, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPEG", 80)
        self._attached_image_b64 = base64.b64encode(ba.data()).decode('utf-8')
        
        self.attach_btn.setStyleSheet("""
            QPushButton {
                background: #4CAF50; color: white; border: none; border-radius: 6px; font-size: 16px;
            }
            QPushButton:hover { background: #43A047; }
        """)
        self.attach_btn.setText("🖼️")

    def _submit(self):
        text = self.input_field.text().strip()
        if not text and not self._attached_image_b64:
            return
            
        img_b64 = self._attached_image_b64
        self._attached_image_b64 = ""
        self.attach_btn.setText("📎")
        self.attach_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: #aaa; border: none; border-radius: 6px; font-size: 16px;
            }
            QPushButton:hover { background: #333; }
        """)
        
        display_text = text if text else "[Image Attached]"
        if img_b64 and text:
            display_text = f"[Image Attached] {text}"
            
        self._append("You", display_text, "#4CAF50")
        self.input_field.clear()
        self.send_btn.setEnabled(False)
        self.input_submitted.emit(text, img_b64)

    def _append(self, sender: str, text: str, color: str):
        ts = time.strftime("%H:%M:%S")
        # Escape HTML in text
        escaped = (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
        )
        html = f"""
        <div style="margin:10px 0 6px 0;">
          <span style="color:{color};font-weight:bold;">{sender}</span>
          <span style="color:#888;font-size:11px;margin-left:8px;">{ts}</span>
          <div style="color:#ccc;margin-top:6px;line-height:1.6;">{escaped}</div>
        </div>
        <div style="border-top:1px solid #1e1e1e;margin:6px 0;"></div>
        """
        self.output.append(html)
        self.output.moveCursor(QTextCursor.End)

    def _force_chain(self):
        if self._last_assistant_response:
            # We don't render it in the chat UI as a user message, we just silently trigger the engine!
            self.input_submitted.emit(self._last_assistant_response, "")
            self.send_btn.setEnabled(False)
            self.chain_btn.setEnabled(False)

    # ── Slots ─────────────────────────────────────

    @Slot(str, str)
    def on_response_ready(self, text: str, role_key: str = ""):
        self._last_assistant_response = text
        role_name, role_color = self._ROLE_MAP.get(role_key, self._DEFAULT_ROLE)
        self._append(role_name, text, role_color)
        # Update the overlay indicator too — empty role_key means the servo default
        self._update_overlay_label(role_key or "servo")
        self.send_btn.setEnabled(True)
        self.chain_btn.setEnabled(True)
        self.input_field.setFocus()

    @Slot(str)
    def on_active_role_changed(self, role_key: str):
        """External signal hook — updates the overlay label without rendering a chat entry."""
        self._update_overlay_label(role_key or "servo")

    def _update_overlay_label(self, role_key: str):
        name, color = self._ROLE_MAP.get(role_key, self._DEFAULT_ROLE)
        # Use lower-case role key for the dot label — mirrors manifest convention
        display_key = role_key.lower() if role_key else "servo"
        self.overlay_label.setText(f"● {display_key}")
        self.overlay_label.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; padding: 2px 0 0 4px;"
        )

    @Slot(str)
    def on_error(self, error: str):
        self._append("Error", error, "#F44336")
        self.send_btn.setEnabled(True)
