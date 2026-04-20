"""
Tests for CoreLoop._render_active_tasks_block — the [ACTIVE TASKS]
system-prompt block rendered from the task ledger (v0.8.0, D-20260419-12).

Covers:
  - empty ledger renders as empty string (no decorative placeholder)
  - all-pending renders header + cursor on first row + all rows as "[ ]"
  - completed rows render with "[x]" and DO NOT carry the cursor
  - mixed ledger keeps cursor on the FIRST pending row (not the first row)
  - all-completed renders rows without any cursor
  - rendered block ends with newline so it splices cleanly into the
    f-string between [PATH DISCIPLINE] and AVAILABLE TOOLS

Run: pytest tests/test_task_block_render.py -v
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock


_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Stub PySide6 + chromadb + ollama_client so core.loop imports cleanly.
if "PySide6" not in sys.modules:
    _pyside = types.ModuleType("PySide6")
    _pyside_core = types.ModuleType("PySide6.QtCore")
    class _StubSignal:
        def __init__(self, *a, **k): pass
        def emit(self, *a, **k): pass
        def connect(self, *a, **k): pass
    class _StubQThread:
        def __init__(self, *a, **k): pass
    _pyside_core.QThread = _StubQThread
    _pyside_core.Signal  = _StubSignal
    _pyside.QtCore       = _pyside_core
    sys.modules["PySide6"]        = _pyside
    sys.modules["PySide6.QtCore"] = _pyside_core

if "core.ollama_client" not in sys.modules:
    _oc = types.ModuleType("core.ollama_client")
    class ChatCancelled(Exception): pass
    class OllamaClient:
        def __init__(self, *a, **k): pass
        def chat(self, *a, **k): return ("", {})
    _oc.ChatCancelled = ChatCancelled
    _oc.OllamaClient  = OllamaClient
    sys.modules["core.ollama_client"] = _oc

if "chromadb" not in sys.modules:
    _chromadb = types.ModuleType("chromadb")
    _chromadb.PersistentClient = MagicMock()
    sys.modules["chromadb"] = _chromadb


def _task(tid: int, desc: str, status: str = "pending") -> dict:
    """Shape-match what StateStore.get_all_active_tasks() emits."""
    return {
        "id":           tid,
        "description":  desc,
        "status":       status,
        "created_at":   0.0,
        "completed_at": None if status == "pending" else 1.0,
    }


class TestActiveTasksRender(unittest.TestCase):
    """Renderer is a pure method — we call it unbound with a stub `self`."""

    def setUp(self):
        from core.loop import CoreLoop
        self._render = CoreLoop._render_active_tasks_block
        self._self   = object()  # renderer never touches self

    def test_empty_ledger_renders_empty_string(self):
        # Matters because an empty [ACTIVE TASKS] block with header-only
        # would still bloat the prompt for runs where nobody used the
        # task tool.
        self.assertEqual(self._render(self._self, []), "")
        self.assertEqual(self._render(self._self, None) or "", "")

    def test_header_present_when_tasks_exist(self):
        out = self._render(self._self, [_task(1, "A")])
        self.assertIn("[ACTIVE TASKS]", out)

    def test_single_pending_carries_cursor(self):
        out = self._render(self._self, [_task(7, "Read manifest")])
        # Exactly one cursor, on the only row.
        self.assertEqual(out.count("▶"), 1)
        self.assertIn("#7", out)
        self.assertIn("Read manifest", out)
        self.assertIn("[ ]", out)

    def test_all_pending_cursor_on_first_only(self):
        tasks = [_task(1, "A"), _task(2, "B"), _task(3, "C")]
        out = self._render(self._self, tasks)
        self.assertEqual(out.count("▶"), 1)
        first_line = next(ln for ln in out.splitlines() if "A" in ln and "#1" in ln)
        self.assertIn("▶", first_line)
        # Subsequent pending rows should NOT carry the cursor.
        b_line = next(ln for ln in out.splitlines() if "#2" in ln)
        self.assertNotIn("▶", b_line)

    def test_completed_rows_use_check_and_no_cursor(self):
        tasks = [_task(1, "A", status="completed"), _task(2, "B")]
        out = self._render(self._self, tasks)
        a_line = next(ln for ln in out.splitlines() if "#1" in ln)
        b_line = next(ln for ln in out.splitlines() if "#2" in ln)
        self.assertIn("[x]", a_line)
        self.assertNotIn("▶", a_line)
        # Cursor jumps past completed rows to the first pending.
        self.assertIn("▶", b_line)
        self.assertIn("[ ]", b_line)

    def test_cursor_skips_leading_completed(self):
        # Two completed, then two pending. Cursor should sit on the first
        # pending (not on the first row in the list).
        tasks = [
            _task(1, "A", status="completed"),
            _task(2, "B", status="completed"),
            _task(3, "C"),
            _task(4, "D"),
        ]
        out = self._render(self._self, tasks)
        self.assertEqual(out.count("▶"), 1)
        c_line = next(ln for ln in out.splitlines() if "#3" in ln)
        self.assertIn("▶", c_line)

    def test_all_completed_no_cursor(self):
        # Plan finished — nothing to point at. Don't render a stray cursor.
        tasks = [
            _task(1, "A", status="completed"),
            _task(2, "B", status="completed"),
        ]
        out = self._render(self._self, tasks)
        self.assertNotIn("▶", out)
        self.assertEqual(out.count("[x]"), 2)

    def test_output_ends_with_newline(self):
        # Block gets spliced into the f-string template literally;
        # trailing newline keeps AVAILABLE TOOLS on its own line.
        out = self._render(self._self, [_task(1, "A")])
        self.assertTrue(out.endswith("\n"))

    def test_teaching_line_mentions_complete_action(self):
        # The model needs to know how to retire a row.
        out = self._render(self._self, [_task(1, "A")])
        self.assertIn("task", out.lower())
        self.assertIn("complete", out.lower())


if __name__ == "__main__":
    unittest.main()
