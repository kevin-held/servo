import unittest
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch
from core.state import StateStore

class TestStateMemory(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(self.tmp_dir, "db.sqlite")
        chroma_path = os.path.join(self.tmp_dir, "chroma")
        self.state = StateStore(db_path, chroma_path)

    def tearDown(self):
        try:
            self.state.conn.close()
        except: pass
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_and_search_memory(self):
        self.state.add_memory("The secret access code is XYZZY-99")
        results = self.state.get_relevant_memory("access code", limit=5)
        self.assertEqual(len(results), 1)
        self.assertIn("XYZZY-99", results[0]["content"])

    def test_search_empty_database_returns_empty_list(self):
        results = self.state.get_relevant_memory("anything")
        self.assertEqual(results, [])

    def test_get_recent_memory_fallback(self):
        self.state.add_memory("Recent item passed via text.")
        results = self.state.get_relevant_memory("")
        self.assertEqual(len(results), 1)
        self.assertIn("Recent item", results[0]["content"])

    def test_prune_memory_truncation(self):
        # We manually insert slightly more than the limit 
        # StateStore default limit is 1000, we'll patch it to be 10 for the test
        self.state._prune_memory = lambda limit=10: StateStore._prune_memory(self.state, limit=10)
        
        for i in range(15):
            self.state.add_memory(f"Dummy memory {i}")
            
        count = self.state.memory_collection.count()
        self.assertTrue(count < 15)

    def test_get_conversation_history(self):
        for i in range(5):
            self.state.add_conversation_turn("user" if i % 2 == 0 else "assistant", f"msg {i}")
        history = self.state.get_conversation_history(limit=3)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["content"], "msg 2")

    def test_add_trace_and_log_mirror(self):
        with patch("core.state.get_logger") as mock_get_logger:
            self.state.add_trace("STEP_X", "Doing something important")
            cur = self.state.conn.execute("SELECT step, message FROM trace")
            row = cur.fetchone()
            self.assertEqual(row[0], "STEP_X")
            mock_get_logger.return_value.log.assert_called_with("INFO", "loop.step_x", "Doing something important")

    def test_get_all_state(self):
        self.state.set("k1", "v1")
        all_state = self.state.get_all_state()
        self.assertEqual(all_state["k1"], "v1")

    def test_session_flags(self):
        self.state.set_session_flag("mode", "auto")
        self.assertEqual(self.state.get_session_flag("mode"), "auto")
        self.assertEqual(self.state.get("session_mode"), "auto")

    def test_backup_state_exception_swallowed(self):
        with patch("shutil.copy2", side_effect=IOError("Disk Full")):
            self.state._backup_state("some/path") # No raise

    def test_init_schema_upgrade_idempotent(self):
        self.state._init_schema() # No raise (column already exists)

    def test_prune_memory_exception_swallowed(self):
        self.state.memory_collection.count = MagicMock(side_effect=RuntimeError("Chroma Down"))
        self.state._prune_memory() # No raise

    def test_add_trace_exception_swallowed(self):
        with patch("core.state.get_logger", side_effect=RuntimeError("Log failed")):
            self.state.add_trace("STEP", "msg") # No raise

    def test_query_logs_delegation(self):
        """Line 296: Verify query_logs delegates to get_logger()."""
        with patch("core.state.get_logger") as mock_get:
            self.state.query_logs(level="ERROR")
            mock_get.return_value.query.assert_called_with(level="ERROR")

if __name__ == "__main__":
    unittest.main()
