import unittest
import os
import sqlite3
import json
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on the path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import tools.memory_manager as memory_manager

class TestMemoryManager(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "state.db")
        
        # Patch os.path.join INSIDE the module to steer it to our temp DB
        self._patcher_os = patch("tools.memory_manager.os.path.join", return_value=self._db_path)
        self._patcher_os.start()

    def tearDown(self):
        self._patcher_os.stop()
        if os.path.exists(self._db_path):
            try: os.remove(self._db_path)
            except: pass
        os.rmdir(self._temp_dir)

    def test_overwrite_action(self):
        resp = memory_manager.execute("overwrite", "Initial logic")
        self.assertIn("Successfully OVERWRITTEN", resp)
        
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute("SELECT value FROM state WHERE key='working_memory'")
        self.assertEqual(cur.fetchone()[0], "Initial logic")
        conn.close()

    def test_append_action(self):
        memory_manager.execute("overwrite", "Line 1")
        resp = memory_manager.execute("append", "Line 2")
        self.assertIn("Successfully appended", resp)
        
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute("SELECT value FROM state WHERE key='working_memory'")
        self.assertEqual(cur.fetchone()[0], "Line 1\nLine 2")
        conn.close()

    def test_clear_action(self):
        memory_manager.execute("overwrite", "Something")
        resp = memory_manager.execute("clear")
        self.assertIn("Working memory cleared", resp)
        
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute("SELECT value FROM state WHERE key='working_memory'")
        self.assertEqual(cur.fetchone()[0], "")
        conn.close()

    @patch("core.sentinel_logger.get_logger")
    def test_snapshot_captured(self, mock_get_logger):
        mock_logger = mock_get_logger.return_value
        memory_manager.execute("overwrite", "Snapshot test")
        mock_logger.log.assert_called()

    @patch("core.ollama_client.OllamaClient")
    @patch("requests.get")
    def test_auto_summarize_trigger(self, mock_get, mock_ollama_class):
        mock_client = mock_ollama_class.return_value
        mock_client.chat.return_value = ("Extremely compressed logic.", {})
        mock_get.return_value.json.return_value = {"models": [{"name": "test-model:latest"}]}
        
        large_content = "X" * 1600
        resp = memory_manager.execute("append", large_content)
        self.assertIn("auto-summarized", resp)
        
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute("SELECT value FROM state WHERE key='working_memory'")
        self.assertEqual(cur.fetchone()[0], "Extremely compressed logic.")
        conn.close()

    def test_database_error_handling(self):
        # Force a database error by patching connect to fail within the module's context
        import sqlite3 as real_sqlite3
        with patch("tools.memory_manager.sqlite3.connect", side_effect=real_sqlite3.Error("Mock Pool Error")):
            resp = memory_manager.execute("clear")
            self.assertIn("Database Error", resp)

    def test_auto_summarize_exception_handling(self):
        """Line 60-62: Verify summarization exceptions are swallowed and appended normally."""
        # Patch core.ollama_client.OllamaClient directly since the tool imports it locally
        with patch("core.ollama_client.OllamaClient", side_effect=RuntimeError("GPU missing")):
             large_content = "X" * 1600
             resp = memory_manager.execute("append", large_content)
             self.assertIn("summarization bypassed", resp)

if __name__ == "__main__":
    unittest.main()
