"""
Tests for the v0.8.0 task ledger:

  - core/state.py: tasks table + create/complete/list/clear CRUD
  - tools/task.py: execute() dispatch on each action

Covers (D-20260419-12):
  - StateStore.create_task / create_tasks order + skipping blanks
  - mark_task_complete idempotence and unknown-id behavior
  - get_pending_tasks vs get_all_active_tasks (cursor source vs render
    source)
  - clear_tasks wipes the ledger but conversation_summary stays put
  - clear_conversation does NOT wipe tasks (sticky-ledger guarantee)
  - tools/task.py `create` batch and single forms
  - tools/task.py `create` cap rejection-as-teaching
  - tools/task.py `complete` flips status, second call is idempotent
  - tools/task.py `list` renders cursor on first pending
  - tools/task.py `clear` empties ledger
  - tools/task.py unknown action returns an error string

Run: pytest tests/test_task_tool.py -v
"""

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Path setup ──────────────────────────────────────
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Heavyweight stubs (same pattern as test_history_compressor.py) ──
if "chromadb" not in sys.modules:
    _chromadb = types.ModuleType("chromadb")
    _chromadb.PersistentClient = MagicMock()
    sys.modules["chromadb"] = _chromadb


def _make_state():
    """Build a StateStore against a throwaway tempdir."""
    from core import state as state_module

    tmp = tempfile.mkdtemp()
    db_path     = Path(tmp) / "state.db"
    chroma_path = Path(tmp) / "chroma"

    fake_chroma = MagicMock()
    fake_collection = MagicMock()
    fake_collection.count.return_value = 0
    fake_collection.query.return_value = {"documents": [[]], "metadatas": [[]]}
    fake_chroma.PersistentClient.return_value.get_or_create_collection.return_value = fake_collection

    with patch.object(state_module, "chromadb", fake_chroma):
        store = state_module.StateStore(
            db_path=str(db_path),
            chroma_path=str(chroma_path),
        )

    def cleanup():
        try:
            store.conn.close()
        except Exception:
            pass

    return store, cleanup, tmp


def _load_task_tool_against_db(db_path: str):
    """Load tools/task.py as a fresh module bound to a specific db file.

    The tool resolves its DB path via `_db_path()` (project-relative);
    in tests we want it to point at the temp DB the StateStore created.
    Patching the helper inside a fresh module copy keeps each test
    isolated.
    """
    spec = importlib.util.spec_from_file_location(
        "tools_task_under_test",
        str(_ROOT / "tools" / "task.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._db_path = lambda: db_path
    return mod


# ──────────────────────────────────────────────────────────
# StateStore CRUD
# ──────────────────────────────────────────────────────────

class TestStateTaskCRUD(unittest.TestCase):

    def setUp(self):
        self.state, self._cleanup, self._tmp = _make_state()

    def tearDown(self):
        self._cleanup()

    def test_empty_ledger_returns_empty_lists(self):
        self.assertEqual(self.state.get_pending_tasks(), [])
        self.assertEqual(self.state.get_all_active_tasks(), [])

    def test_create_task_returns_int_id(self):
        tid = self.state.create_task("Read manifest.json")
        self.assertIsInstance(tid, int)
        self.assertEqual(len(self.state.get_pending_tasks()), 1)

    def test_create_tasks_preserves_order(self):
        ids = self.state.create_tasks(["A", "B", "C"])
        self.assertEqual(len(ids), 3)
        descs = [t["description"] for t in self.state.get_pending_tasks()]
        self.assertEqual(descs, ["A", "B", "C"])

    def test_create_tasks_skips_blank_entries(self):
        ids = self.state.create_tasks(["A", "", "  ", "B"])
        self.assertEqual(len(ids), 2)
        descs = [t["description"] for t in self.state.get_pending_tasks()]
        self.assertEqual(descs, ["A", "B"])

    def test_mark_task_complete_returns_true_first_time(self):
        tid = self.state.create_task("only task")
        self.assertTrue(self.state.mark_task_complete(tid))
        # Pending ledger now empty, but full ledger still has the row.
        self.assertEqual(self.state.get_pending_tasks(), [])
        full = self.state.get_all_active_tasks()
        self.assertEqual(len(full), 1)
        self.assertEqual(full[0]["status"], "completed")
        self.assertIsNotNone(full[0]["completed_at"])

    def test_mark_task_complete_is_idempotent(self):
        tid = self.state.create_task("task")
        self.state.mark_task_complete(tid)
        # Second call: already completed → returns False, raises nothing.
        self.assertFalse(self.state.mark_task_complete(tid))

    def test_mark_task_complete_unknown_id_returns_false(self):
        self.assertFalse(self.state.mark_task_complete(999999))

    def test_get_pending_tasks_excludes_completed(self):
        a, b, c = self.state.create_tasks(["A", "B", "C"])
        self.state.mark_task_complete(b)
        pending = self.state.get_pending_tasks()
        self.assertEqual([t["id"] for t in pending], [a, c])

    def test_get_all_active_tasks_includes_completed(self):
        a, b = self.state.create_tasks(["A", "B"])
        self.state.mark_task_complete(a)
        full = self.state.get_all_active_tasks()
        self.assertEqual([t["id"] for t in full], [a, b])
        statuses = [t["status"] for t in full]
        self.assertEqual(statuses, ["completed", "pending"])

    def test_clear_tasks_wipes_everything(self):
        self.state.create_tasks(["A", "B", "C"])
        self.state.clear_tasks()
        self.assertEqual(self.state.get_all_active_tasks(), [])

    def test_clear_conversation_does_not_wipe_tasks(self):
        # Sticky-ledger guarantee — tasks persist across /reset.
        self.state.create_tasks(["A", "B"])
        self.state.add_conversation_turn("user", "hello")
        self.state.clear_conversation()
        self.assertEqual(len(self.state.get_pending_tasks()), 2)


# ──────────────────────────────────────────────────────────
# tools/task.py execute() dispatch
# ──────────────────────────────────────────────────────────

class TestTaskTool(unittest.TestCase):

    def setUp(self):
        self.state, self._cleanup, self._tmp = _make_state()
        # The tool reads the same SQLite file the StateStore wrote, so we
        # bind it to the same db_path.
        self.tool = _load_task_tool_against_db(
            os.path.join(self._tmp, "state.db")
        )

    def tearDown(self):
        self._cleanup()

    # ── action: create ──

    def test_create_batch_registers_all(self):
        out = self.tool.execute(action="create", tasks=["A", "B", "C"])
        self.assertIn("Registered 3 task(s)", out)
        self.assertEqual(len(self.state.get_pending_tasks()), 3)

    def test_create_single_via_description(self):
        out = self.tool.execute(action="create", description="Solo")
        self.assertIn("Registered 1 task(s)", out)
        self.assertEqual(self.state.get_pending_tasks()[0]["description"], "Solo")

    def test_create_batch_wins_over_description_when_both_given(self):
        out = self.tool.execute(
            action="create", tasks=["A"], description="ignored"
        )
        descs = [t["description"] for t in self.state.get_pending_tasks()]
        self.assertEqual(descs, ["A"])
        self.assertNotIn("ignored", out)

    def test_create_with_no_payload_is_an_error(self):
        out = self.tool.execute(action="create")
        self.assertTrue(out.lower().startswith("error"))

    def test_create_oversized_batch_is_rejected(self):
        oversized = [f"task {i}" for i in range(self.tool._DEFAULT_MAX_TASKS + 5)]
        out = self.tool.execute(action="create", tasks=oversized)
        self.assertIn("exceeds cap", out)
        # And nothing should be persisted.
        self.assertEqual(self.state.get_pending_tasks(), [])

    def test_create_at_cap_succeeds(self):
        right_at_cap = [f"task {i}" for i in range(self.tool._DEFAULT_MAX_TASKS)]
        out = self.tool.execute(action="create", tasks=right_at_cap)
        self.assertIn(f"Registered {self.tool._DEFAULT_MAX_TASKS} task(s)", out)

    # ── action: complete ──

    def test_complete_marks_done(self):
        ids = self.state.create_tasks(["A", "B"])
        out = self.tool.execute(action="complete", task_id=ids[0])
        self.assertIn(f"Completed #{ids[0]}", out)
        self.assertEqual(len(self.state.get_pending_tasks()), 1)

    def test_complete_twice_is_idempotent(self):
        tid = self.state.create_task("A")
        self.tool.execute(action="complete", task_id=tid)
        out2 = self.tool.execute(action="complete", task_id=tid)
        self.assertIn("already completed", out2.lower())

    def test_complete_unknown_id(self):
        out = self.tool.execute(action="complete", task_id=999)
        self.assertTrue(out.lower().startswith("error"))

    def test_complete_missing_task_id(self):
        out = self.tool.execute(action="complete")
        self.assertTrue(out.lower().startswith("error"))

    def test_complete_non_integer_task_id(self):
        out = self.tool.execute(action="complete", task_id="abc")
        self.assertTrue(out.lower().startswith("error"))

    # ── action: list ──

    def test_list_empty(self):
        out = self.tool.execute(action="list")
        self.assertIn("No active tasks", out)

    def test_list_renders_cursor_on_first_pending(self):
        ids = self.state.create_tasks(["First", "Second", "Third"])
        out = self.tool.execute(action="list")
        # Cursor (▶) should appear exactly once, on First.
        self.assertEqual(out.count("▶"), 1)
        # First pending row should carry the cursor.
        first_line = next(line for line in out.splitlines() if "First" in line)
        self.assertIn("▶", first_line)

    def test_list_completed_rows_render_with_check(self):
        a, b = self.state.create_tasks(["Done", "Todo"])
        self.state.mark_task_complete(a)
        out = self.tool.execute(action="list")
        self.assertIn("[x]", out)
        # Cursor moves to the still-pending row.
        todo_line = next(line for line in out.splitlines() if "Todo" in line)
        self.assertIn("▶", todo_line)

    # ── action: clear ──

    def test_clear_empties_ledger(self):
        self.state.create_tasks(["A", "B"])
        out = self.tool.execute(action="clear")
        self.assertIn("Cleared 2 task row(s)", out)
        self.assertEqual(self.state.get_pending_tasks(), [])

    # ── error paths ──

    def test_unknown_action_returns_error(self):
        out = self.tool.execute(action="frob")
        self.assertTrue(out.lower().startswith("error"))

    def test_missing_action_returns_error(self):
        out = self.tool.execute()
        self.assertTrue(out.lower().startswith("error"))


if __name__ == "__main__":
    unittest.main()
