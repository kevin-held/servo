from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QTextEdit, 
    QSizePolicy
)
from PySide6.QtCore import Qt

class CollapsibleSection(QWidget):
    """A reusable collapsible panel for the Servo GUI."""
    def __init__(self, title: str, color: str = "#00E5FF", parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 8)
        self.layout.setSpacing(0)

        # Header Button
        self.toggle_btn = QPushButton(f"▼  {title}")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: #1a1a1a;
                color: {color};
                border: 1px solid #333;
                border-radius: 4px;
                padding: 10px;
                text-align: left;
                font-weight: bold;
                font-size: 12px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{ background: #222; border-color: {color}; }}
            QPushButton:checked {{ background: #111; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }}
        """)
        self.toggle_btn.clicked.connect(self._toggle)

        # Content Area
        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        # We allow adding any widget to the content, but default to QTextEdit if set_text is used
        self.text_edit = None
        
        self.layout.addWidget(self.toggle_btn)
        self.layout.addWidget(self.content_widget)
        
        # Set size policy to allow expansion
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def set_widget(self, widget: QWidget):
        """Replaces the content area with a custom widget."""
        # Clear existing
        for i in reversed(range(self.content_layout.count())): 
            self.content_layout.itemAt(i).widget().setParent(None)
        self.content_layout.addWidget(widget)

    def set_text(self, text: str):
        """Default mode: uses a QTextEdit for display."""
        if self.text_edit is None:
            self.text_edit = QTextEdit()
            self.text_edit.setReadOnly(True)
            self.text_edit.setMinimumHeight(100)
            self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.text_edit.setStyleSheet("""
                QTextEdit {
                    background: #0d0d0d;
                    color: #ddd;
                    border: 1px solid #333;
                    border-top: none;
                    border-bottom-left-radius: 4px;
                    border-bottom-right-radius: 4px;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                    padding: 8px;
                }
            """)
            self.set_widget(self.text_edit)
        self.text_edit.setPlainText(str(text))

    def _toggle(self):
        visible = self.toggle_btn.isChecked()
        self.content_widget.setVisible(visible)
        self.toggle_btn.setText(f"{'▼' if visible else '▶'}  {self.toggle_btn.text()[3:]}")
        
        # Adjust size policy to help parent layouts
        if visible:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        else:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        
        # Trigger layout update in parent
        self.updateGeometry()
        if self.parentWidget() and self.parentWidget().layout():
            self.parentWidget().layout().activate()
