"""
Log Panel — Real-time Log Viewer with Live Stream, Error Analytics, and Interactive Filters.

Three sub-components:
  1. Live Stream Console — tails sentinel.jsonl, color-coded by level
  2. Error Analytics — sparkline chart + recent failures list
  3. Interactive Filter Toolbar — toggle visibility per log level
"""

import json
import time
from collections import deque
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QCheckBox, QListWidget, QListWidgetItem,
    QDialog, QDialogButtonBox, QSizePolicy, QPushButton,
)
from PySide6.QtCore import Qt, Slot, QTimer, QFileSystemWatcher
from PySide6.QtGui import QColor, QFont, QTextCursor, QPainter, QPen, QBrush


# ── Constants ────────────────────────────────────────

_LOG_FILE = Path(__file__).parent.parent / "logs" / "sentinel.jsonl"

LEVEL_COLORS = {
    "CRITICAL": "#E53935",
    "ERROR":    "#F44336",
    "WARNING":  "#FF9800",
    "INFO":     "#4CAF50",
    "DEBUG":    "#546E7A",
}

LEVEL_ORDER = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


# ── Sparkline Widget ─────────────────────────────────

class ErrorSparkline(QWidget):
    """Mini bar chart showing ERROR+CRITICAL counts per 5-minute bucket over the last hour."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._data = []   # list of {"bucket": "HH:MM", "count": N}

    def set_data(self, data: list):
        self._data = data
        self.update()

    def paintEvent(self, event):
        if not self._data:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        n = len(self._data)
        if n == 0:
            return

        max_count = max((d["count"] for d in self._data), default=1) or 1
        bar_width = max(2, (w - 4) // n - 2)
        spacing = max(1, ((w - 4) - bar_width * n) // max(n - 1, 1))

        # Background
        painter.fillRect(0, 0, w, h, QColor("#161616"))

        # Draw bars
        x = 2
        for d in self._data:
            count = d["count"]
            bar_h = max(1, int((count / max_count) * (h - 14))) if count > 0 else 0

            if count > 0:
                color = QColor("#F44336") if count >= 3 else QColor("#FF9800") if count >= 1 else QColor("#546E7A")
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(x, h - 10 - bar_h, bar_width, bar_h, 1, 1)

            x += bar_width + spacing

        # Bottom labels (only first and last)
        painter.setPen(QPen(QColor("#555")))
        painter.setFont(QFont("Consolas", 7))
        if self._data:
            painter.drawText(2, h - 1, self._data[0]["bucket"])
            last_label = self._data[-1]["bucket"]
            fm = painter.fontMetrics()
            painter.drawText(w - fm.horizontalAdvance(last_label) - 2, h - 1, last_label)

        painter.end()


# ── Error Detail Dialog ──────────────────────────────

class ErrorDetailDialog(QDialog):
    """Popup showing full JSON context of a log entry."""

    def __init__(self, entry: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Log Entry — {entry.get('level', 'UNKNOWN')}")
        self.setMinimumSize(500, 350)
        self.setStyleSheet("""
            QDialog { background: #1a1a1a; }
            QPlainTextEdit {
                background: #111;
                color: #ddd;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 10px;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
            QPushButton {
                background: #2a2a2a; color: #ccc; border: 1px solid #333;
                border-radius: 4px; padding: 6px 16px;
            }
            QPushButton:hover { background: #333; }
        """)

        layout = QVBoxLayout(self)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(entry, indent=2, ensure_ascii=False))
        layout.addWidget(text)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.close)
        layout.addWidget(btns)


# ── Main Log Panel ───────────────────────────────────

class LogPanel(QWidget):
    """
    Embeddable log viewer widget with three sections:
    Live Stream, Error Analytics, Interactive Filters.
    """

    def __init__(self):
        super().__init__()
        self._auto_scroll = True
        self._level_filters = {level: (level != "DEBUG") for level in LEVEL_ORDER}
        self._buffer = deque(maxlen=500)  # ring buffer of parsed entries
        self._last_file_size = 0

        # Dedupe tracker for the dual-ingress problem.
        # Every event that goes through core.loop._slog lands in this panel
        # twice — once via the CoreLoop.log_event Qt signal, and a second time
        # when QFileSystemWatcher notices sentinel.jsonl grew. Same story for
        # state.add_trace's INFO mirror (no signal, but the file watcher still
        # fires). The file on disk has one line per event; the widget was
        # rendering each of them twice. We can't drop the file watcher (INFO
        # entries from state.add_trace have no direct signal path) and we
        # can't drop the signal (lower latency, survives watcher drops), so
        # we dedupe at render time by (level, component, message) within a
        # short recency window. Identical events more than 2s apart are
        # allowed through on the theory that a real duplicate that far apart
        # is two distinct occurrences, not the dual-ingress echo.
        self._recent_renders: deque = deque(maxlen=64)  # (key, monotonic_time)

        self._build_ui()
        self._setup_watchers()

    # ── Dedupe ────────────────────────────────────────

    def _is_duplicate(self, level: str, component: str, message: str) -> bool:
        """True if an identical entry was rendered in the last 2s."""
        key = (level, component, message)
        now = time.monotonic()
        # Prune entries older than the dedupe window.
        while self._recent_renders and now - self._recent_renders[0][1] > 2.0:
            self._recent_renders.popleft()
        for k, _ts in self._recent_renders:
            if k == key:
                return True
        self._recent_renders.append((key, now))
        return False

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Filter Toolbar ────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        filter_row.setContentsMargins(0, 0, 0, 0)

        for level in LEVEL_ORDER:
            cb = QCheckBox(level)
            cb.setChecked(self._level_filters[level])
            color = LEVEL_COLORS[level]
            cb.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")
            cb.toggled.connect(lambda checked, lv=level: self._on_filter_changed(lv, checked))
            filter_row.addWidget(cb)

        filter_row.addStretch()

        self.auto_scroll_check = QCheckBox("Auto-scroll")
        self.auto_scroll_check.setChecked(True)
        self.auto_scroll_check.setStyleSheet("color: #666; font-size: 10px;")
        self.auto_scroll_check.toggled.connect(lambda c: setattr(self, '_auto_scroll', c))
        filter_row.addWidget(self.auto_scroll_check)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(48)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: #1a1a1a; color: #666; border: 1px solid #333;
                border-radius: 3px; font-size: 9px; padding: 2px 6px;
            }
            QPushButton:hover { background: #2a1a1a; color: #F44336; border-color: #F44336; }
        """)
        clear_btn.clicked.connect(self._on_clear_log)
        filter_row.addWidget(clear_btn)

        layout.addLayout(filter_row)

        # ── Live Stream Console ───────────────────────
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(500)
        self.console.setStyleSheet("""
            QPlainTextEdit {
                background: #0d0d0d;
                color: #aaa;
                border: 1px solid #1e1e1e;
                border-radius: 4px;
                padding: 6px;
                font-family: Consolas, monospace;
                font-size: 10px;
            }
        """)
        self.console.setFixedHeight(150)
        layout.addWidget(self.console)

        # ── Error Analytics ───────────────────────────
        analytics_label = QLabel("ERROR FREQUENCY (last hour)")
        analytics_label.setStyleSheet(
            "color: #555; font-size: 9px; font-weight: bold; letter-spacing: 1px;"
        )
        layout.addWidget(analytics_label)

        self.sparkline = ErrorSparkline()
        layout.addWidget(self.sparkline)

        failures_label = QLabel("RECENT FAILURES")
        failures_label.setStyleSheet(
            "color: #555; font-size: 9px; font-weight: bold; letter-spacing: 1px;"
        )
        layout.addWidget(failures_label)

        self.failures_list = QListWidget()
        self.failures_list.setFixedHeight(100)
        self.failures_list.setStyleSheet("""
            QListWidget {
                background: #111;
                color: #F44336;
                border: 1px solid #1e1e1e;
                border-radius: 4px;
                font-size: 10px;
                font-family: Consolas, monospace;
            }
            QListWidget::item { padding: 3px 6px; border-bottom: 1px solid #1a1a1a; }
            QListWidget::item:hover { background: #1e1e1e; }
            QListWidget::item:selected { background: #2a1a1a; }
        """)
        self.failures_list.itemDoubleClicked.connect(self._on_failure_clicked)
        layout.addWidget(self.failures_list)

    def _setup_watchers(self):
        """Set up file watcher and periodic refresh timers."""
        # File watcher for live tail
        self._watcher = QFileSystemWatcher()
        if _LOG_FILE.exists():
            self._watcher.addPath(str(_LOG_FILE))
            self._last_file_size = _LOG_FILE.stat().st_size
        else:
            # Watch the parent dir so we detect when the file is first created
            log_dir = str(_LOG_FILE.parent)
            if Path(log_dir).exists():
                self._watcher.addPath(log_dir)

        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

        # Periodic refresh for error analytics (every 30s)
        self._analytics_timer = QTimer(self)
        self._analytics_timer.timeout.connect(self._refresh_analytics)
        self._analytics_timer.start(30_000)

        # Initial load
        QTimer.singleShot(500, self._initial_load)

    # ── Data Loading ──────────────────────────────────

    def _initial_load(self):
        """Load the tail of the existing log file on startup."""
        if not _LOG_FILE.exists():
            return

        try:
            entries = deque(maxlen=200)
            with open(_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            for entry in entries:
                self._buffer.append(entry)
                self._render_entry(entry)

            self._last_file_size = _LOG_FILE.stat().st_size
        except Exception:
            pass

        self._refresh_analytics()

    def _on_file_changed(self, path: str):
        """Incrementally read new lines appended to the log file."""
        if not _LOG_FILE.exists():
            return

        try:
            current_size = _LOG_FILE.stat().st_size

            # Handle rotation (file got smaller)
            if current_size < self._last_file_size:
                self._last_file_size = 0

            if current_size <= self._last_file_size:
                return

            with open(_LOG_FILE, "r", encoding="utf-8") as f:
                f.seek(self._last_file_size)
                new_data = f.read()

            self._last_file_size = current_size

            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    self._buffer.append(entry)
                    self._render_entry(entry)
                except json.JSONDecodeError:
                    continue

        except Exception:
            pass

        # Re-add the path (QFileSystemWatcher can drop it after changes)
        if str(_LOG_FILE) not in self._watcher.files():
            if _LOG_FILE.exists():
                self._watcher.addPath(str(_LOG_FILE))

    def _on_dir_changed(self, path: str):
        """Detect when sentinel.jsonl is first created."""
        if _LOG_FILE.exists() and str(_LOG_FILE) not in self._watcher.files():
            self._watcher.addPath(str(_LOG_FILE))
            self._last_file_size = 0
            self._initial_load()

    # ── Rendering ─────────────────────────────────────

    def _render_entry(self, entry: dict):
        """Render a single log entry to the console if it passes filters."""
        level = entry.get("level", "INFO")

        if not self._level_filters.get(level, True):
            return

        component = entry.get("component", "?")
        message = entry.get("message", "")

        # Dedupe: the signal and file-watcher ingress paths both deliver the
        # same event. SentinelLogger is a singleton with a single file
        # handle, so sentinel.jsonl has one line per event — any dupe in the
        # widget comes from double-rendering. Skip if we already rendered an
        # identical (level, component, message) within the last 2s.
        if self._is_duplicate(level, component, message):
            return

        color = LEVEL_COLORS.get(level, "#888")

        # Format: [HH:MM:SS] [LEVEL] [component] message
        ts_raw = entry.get("timestamp_utc", "")
        try:
            # Extract time portion from ISO timestamp
            ts_display = ts_raw[11:19] if len(ts_raw) >= 19 else ts_raw
        except Exception:
            ts_display = "??:??:??"

        formatted = f"[{ts_display}] [{level:<8}] [{component}] {message}"

        # Use HTML for color coding
        html = f'<span style="color:{color};font-family:Consolas,monospace;font-size:10px;">{self._escape_html(formatted)}</span>'
        self.console.appendHtml(html)

        if self._auto_scroll:
            self.console.moveCursor(QTextCursor.End)

    def _refresh_display(self):
        """Re-render all buffered entries (used when filters change)."""
        self.console.clear()
        # Clear dedupe tracker so re-rendered buffer entries aren't self-dropped.
        # The buffer may legitimately contain back-to-back identical entries
        # from different moments in the session; dedupe is for dual-ingress,
        # not for the historical stream.
        self._recent_renders.clear()
        for entry in self._buffer:
            self._render_entry(entry)

    def _refresh_analytics(self):
        """Update the sparkline and recent failures list."""
        try:
            from core.sentinel_logger import get_logger
            logger = get_logger()

            # Sparkline data
            self.sparkline.set_data(logger.get_error_counts(minutes=60, bucket_minutes=5))

            # Recent failures
            errors = logger.get_recent_errors(limit=10)
            self.failures_list.clear()
            self._recent_errors = errors

            for entry in reversed(errors):
                ts = entry.get("timestamp_utc", "")[:19]
                comp = entry.get("component", "?")
                msg = entry.get("message", "")[:80]
                level = entry.get("level", "ERROR")

                text = f"[{ts}] [{comp}] {msg}"
                item = QListWidgetItem(text)
                color = "#E53935" if level == "CRITICAL" else "#F44336"
                item.setForeground(QColor(color))
                item.setData(Qt.UserRole, entry)
                self.failures_list.addItem(item)

        except Exception:
            pass

    # ── Slots ─────────────────────────────────────────

    @Slot(str, str, str, str)
    def on_log_event(self, level: str, component: str, message: str, context_json: str):
        """
        Direct signal handler from CoreLoop.log_event — renders immediately
        without waiting for the file watcher (lower latency).
        """
        try:
            context = json.loads(context_json) if context_json else {}
        except json.JSONDecodeError:
            context = {}

        entry = {
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            "level": level,
            "component": component,
            "message": message,
        }
        if context:
            entry["context"] = context

        self._buffer.append(entry)
        self._render_entry(entry)

    def _on_filter_changed(self, level: str, checked: bool):
        self._level_filters[level] = checked
        self._refresh_display()

    def _on_failure_clicked(self, item):
        entry = item.data(Qt.UserRole)
        if entry:
            dlg = ErrorDetailDialog(entry, self)
            dlg.exec()

    def _on_clear_log(self):
        """Truncate the log file via the logger singleton, then clear the UI."""
        try:
            from core.sentinel_logger import get_logger
            get_logger().clear()
            self._last_file_size = 0
        except Exception:
            pass

        # Clear in-memory state
        self._buffer.clear()
        self.console.clear()
        self.failures_list.clear()
        self.sparkline.set_data([])

    # ── Helpers ───────────────────────────────────────

    @staticmethod
    def _escape_html(text: str) -> str:
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
