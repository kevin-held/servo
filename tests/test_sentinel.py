"""
Unit tests for the SentinelLogger and log_query tool.
"""

import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestSentinelLogger(unittest.TestCase):
    """Tests for core.sentinel_logger.SentinelLogger"""

    def setUp(self):
        """Create a fresh temp directory and re-initialize the logger for isolation."""
        self._temp_dir = tempfile.mkdtemp(prefix="sentinel_test_")
        self._log_dir = Path(self._temp_dir) / "logs"
        self._archive_dir = self._log_dir / "archive"
        self._active_log = self._log_dir / "sentinel.jsonl"

        # Patch module-level constants so the logger writes to our temp dir
        import core.sentinel_logger as sl_mod
        self._orig_log_dir = sl_mod._LOG_DIR
        self._orig_archive_dir = sl_mod._ARCHIVE_DIR
        self._orig_active_log = sl_mod._ACTIVE_LOG

        sl_mod._LOG_DIR = self._log_dir
        sl_mod._ARCHIVE_DIR = self._archive_dir
        sl_mod._ACTIVE_LOG = self._active_log

        # Force re-create the singleton
        sl_mod.SentinelLogger._instance = None
        sl_mod._logger = None

        from core.sentinel_logger import get_logger
        self.logger = get_logger()

    def tearDown(self):
        """Clean up temp dir and restore module constants."""
        self.logger.shutdown()

        import core.sentinel_logger as sl_mod
        sl_mod._LOG_DIR = self._orig_log_dir
        sl_mod._ARCHIVE_DIR = self._orig_archive_dir
        sl_mod._ACTIVE_LOG = self._orig_active_log
        sl_mod.SentinelLogger._instance = None
        sl_mod._logger = None

        shutil.rmtree(self._temp_dir, ignore_errors=True)

    # ── Format Tests ──────────────────────────────────

    def test_log_entry_has_required_fields(self):
        """Each log entry must have timestamp_utc, level, component, message."""
        self.logger.log("INFO", "test_comp", "hello world")

        with open(self._active_log, "r") as f:
            entry = json.loads(f.readline())

        self.assertIn("timestamp_utc", entry)
        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["component"], "test_comp")
        self.assertEqual(entry["message"], "hello world")

    def test_log_entry_with_context(self):
        """Optional context dict is preserved."""
        ctx = {"file_path": "/test/file.py", "error_code": 42}
        self.logger.log("ERROR", "filesystem", "File not found", ctx)

        with open(self._active_log, "r") as f:
            entry = json.loads(f.readline())

        self.assertEqual(entry["context"]["file_path"], "/test/file.py")
        self.assertEqual(entry["context"]["error_code"], 42)

    def test_invalid_level_defaults_to_info(self):
        """Invalid level strings are normalized to INFO."""
        self.logger.log("BANANA", "test", "bad level")

        with open(self._active_log, "r") as f:
            entry = json.loads(f.readline())

        self.assertEqual(entry["level"], "INFO")

    def test_jsonl_format_one_object_per_line(self):
        """Multiple entries produce one valid JSON object per line."""
        for i in range(5):
            self.logger.log("INFO", "test", f"msg {i}")

        with open(self._active_log, "r") as f:
            lines = [l.strip() for l in f if l.strip()]

        self.assertEqual(len(lines), 5)
        for line in lines:
            entry = json.loads(line)  # should not raise
            self.assertIn("message", entry)

    # ── Rotation Tests ────────────────────────────────

    def test_rotation_creates_archive(self):
        """When the active log exceeds the threshold, an archive .gz is created."""
        import core.sentinel_logger as sl_mod
        orig_threshold = sl_mod._ROTATION_BYTES
        sl_mod._ROTATION_BYTES = 500  # tiny threshold for testing

        try:
            for i in range(100):
                self.logger.log("INFO", "test", f"padding message number {i} " + "x" * 50)

            archives = list(self._archive_dir.glob("log_*.json.gz"))
            self.assertGreater(len(archives), 0, "At least one archive should have been created")

            # Verify archive is valid gzip
            with gzip.open(archives[0], "rt") as f:
                content = f.read()
                self.assertIn("padding message", content)
        finally:
            sl_mod._ROTATION_BYTES = orig_threshold

    # ── Query Tests ───────────────────────────────────

    def test_query_by_level(self):
        """Querying by level returns only matching entries."""
        self.logger.log("INFO", "test", "info msg")
        self.logger.log("ERROR", "test", "error msg")
        self.logger.log("DEBUG", "test", "debug msg")

        results = self.logger.query(level="ERROR")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["message"], "error msg")

    def test_query_by_search_term_in_message(self):
        """search_term matches within the message field."""
        self.logger.log("INFO", "test", "the quick brown fox")
        self.logger.log("INFO", "test", "lazy dog")

        results = self.logger.query(search_term="fox")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["message"], "the quick brown fox")

    def test_query_by_search_term_in_context(self):
        """search_term matches within the context dict."""
        self.logger.log("INFO", "test", "event", {"path": "/important/file.txt"})
        self.logger.log("INFO", "test", "other event")

        results = self.logger.query(search_term="important")
        self.assertEqual(len(results), 1)

    def test_query_tail_returns_most_recent(self):
        """Tail mode returns the N most recent matching entries."""
        for i in range(20):
            self.logger.log("INFO", "test", f"msg {i}")

        results = self.logger.query(tail=True, limit=5)
        self.assertEqual(len(results), 5)
        self.assertEqual(results[-1]["message"], "msg 19")

    def test_query_limit(self):
        """Limit restricts the number of returned results."""
        for i in range(20):
            self.logger.log("INFO", "test", f"msg {i}")

        results = self.logger.query(limit=3)
        self.assertEqual(len(results), 3)

    def test_query_empty_log(self):
        """Querying an empty log returns an empty list."""
        results = self.logger.query()
        self.assertEqual(results, [])

    # ── Thread Safety Test ────────────────────────────

    def test_concurrent_writes(self):
        """Multiple threads writing simultaneously should not corrupt the log."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(50):
                    self.logger.log("INFO", f"thread_{thread_id}", f"msg {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent write errors: {errors}")

        # Verify all entries are valid JSON
        with open(self._active_log, "r") as f:
            count = 0
            for line in f:
                line = line.strip()
                if line:
                    json.loads(line)  # should not raise
                    count += 1

        self.assertEqual(count, 200)  # 4 threads × 50 messages

    # ── Error Counts Test ─────────────────────────────

    def test_get_error_counts(self):
        """get_error_counts returns bucketed data."""
        self.logger.log("ERROR", "test", "err1")
        self.logger.log("CRITICAL", "test", "crit1")
        self.logger.log("INFO", "test", "not an error")

        data = self.logger.get_error_counts(minutes=60, bucket_minutes=5)
        self.assertEqual(len(data), 12)  # 60/5 = 12 buckets
        total_errors = sum(d["count"] for d in data)
        self.assertEqual(total_errors, 2)

    def test_get_recent_errors(self):
        """get_recent_errors returns only ERROR/CRITICAL entries."""
        self.logger.log("INFO", "test", "info")
        self.logger.log("ERROR", "test", "err1")
        self.logger.log("WARNING", "test", "warn")
        self.logger.log("CRITICAL", "test", "crit1")

        errors = self.logger.get_recent_errors(limit=10)
        self.assertEqual(len(errors), 2)
        levels = [e["level"] for e in errors]
        self.assertNotIn("INFO", levels)
        self.assertNotIn("WARNING", levels)


class TestLogQueryTool(unittest.TestCase):
    """Tests for tools.log_query"""

    def setUp(self):
        """Set up temp log dir with test data."""
        self._temp_dir = tempfile.mkdtemp(prefix="logquery_test_")
        self._log_dir = Path(self._temp_dir) / "logs"
        self._archive_dir = self._log_dir / "archive"
        self._active_log = self._log_dir / "sentinel.jsonl"

        import core.sentinel_logger as sl_mod
        self._orig_log_dir = sl_mod._LOG_DIR
        self._orig_archive_dir = sl_mod._ARCHIVE_DIR
        self._orig_active_log = sl_mod._ACTIVE_LOG

        sl_mod._LOG_DIR = self._log_dir
        sl_mod._ARCHIVE_DIR = self._archive_dir
        sl_mod._ACTIVE_LOG = self._active_log

        sl_mod.SentinelLogger._instance = None
        sl_mod._logger = None

        from core.sentinel_logger import get_logger
        self.logger = get_logger()

        # Seed some test data
        self.logger.log("INFO", "test", "info message")
        self.logger.log("ERROR", "test", "error message")
        self.logger.log("WARNING", "test", "warning message")

    def tearDown(self):
        self.logger.shutdown()

        import core.sentinel_logger as sl_mod
        sl_mod._LOG_DIR = self._orig_log_dir
        sl_mod._ARCHIVE_DIR = self._orig_archive_dir
        sl_mod._ACTIVE_LOG = self._orig_active_log
        sl_mod.SentinelLogger._instance = None
        sl_mod._logger = None

        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_execute_returns_json(self):
        """execute() with no filters returns valid JSON."""
        from tools.log_query import execute
        result = execute()
        data = json.loads(result)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)

    def test_execute_level_filter(self):
        """execute() with level filter returns only matching entries."""
        from tools.log_query import execute
        result = execute(level="ERROR")
        data = json.loads(result)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["level"], "ERROR")

    def test_execute_search_term(self):
        """execute() with search_term filters by message content."""
        from tools.log_query import execute
        result = execute(search_term="warning")
        data = json.loads(result)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["level"], "WARNING")

    def test_execute_empty_results(self):
        """execute() returns a message when no entries match."""
        from tools.log_query import execute
        result = execute(level="CRITICAL")
        self.assertIn("No log entries", result)


if __name__ == "__main__":
    unittest.main()
