"""
Tests for default-on delta pre-summarization in tools/scholar_runner.py
(Phase 3, D-20260419-04).

Covers:
  - summarize_deltas=False → every entry is a plain path string (legacy shape)
  - summarize_deltas=True + small file → stays a plain string, increments
    files_skipped_small
  - summarize_deltas=True + large file → becomes {path, summary, raw_line_count,
    raw_bytes} dict with a wrapped summary envelope
  - Kernel exception on large file → falls back to plain string, increments
    files_summarize_failed
  - Empty kernel response on large file → falls back to plain string
  - summarization_stats always present with expected keys

These tests stub the summarizer kernel so no Ollama process is required.
They build scratch files under a controlled subdirectory and monkey-patch
scholar_runner's scan helpers to return a deterministic delta set.

Run: pytest tests/test_scholar_runner_summarize.py -v
"""

import sys
import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import scholar_runner  # noqa: E402


SCRATCH_REL_PREFIX = "tests/_scholar_scratch"


class _ScholarRunnerTest(unittest.TestCase):
    """Provides scratch-file helpers and a context manager that forces
    _run_scan to see a specific delta set without walking the whole project.
    """

    def setUp(self):
        self.scratch_dir = _ROOT / SCRATCH_REL_PREFIX
        if self.scratch_dir.exists():
            shutil.rmtree(self.scratch_dir)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.scratch_dir.exists():
            shutil.rmtree(self.scratch_dir, ignore_errors=True)

    def _write_lines(self, name: str, n_lines: int) -> str:
        """Create a scratch file with n_lines lines. Returns project-relative path."""
        rel = f"{SCRATCH_REL_PREFIX}/{name}"
        abs_p = _ROOT / rel
        abs_p.write_text("\n".join(f"line {i}" for i in range(n_lines)) + "\n",
                         encoding="utf-8")
        return rel

    def _run_with_deltas(self, delta_paths, summarize_deltas: bool,
                         kernel_return=("MOCK SUMMARY", "mock-model"),
                         kernel_side_effect=None):
        """Invoke _run_scan with os.walk patched to yield exactly the given
        delta paths. Mandatory ledgers are also added by _run_scan itself —
        tests must account for that by checking entries they care about
        rather than asserting on list length.
        """
        # We patch _find_latest_review / _find_highest_version so we don't
        # have to stand up a fake review file. The mandatory-files loop
        # inside _run_scan will still add codex/*.md; since those files
        # exist in the real project with varying sizes, tests keep their
        # assertions scoped to the scratch entries they created.
        def fake_walk(_root):
            yield (str(self.scratch_dir), [], [Path(p).name for p in delta_paths])

        kernel_patch_kwargs = {}
        if kernel_side_effect is not None:
            kernel_patch_kwargs["side_effect"] = kernel_side_effect
        else:
            kernel_patch_kwargs["return_value"] = kernel_return

        with patch("tools.scholar_runner.os.walk", side_effect=fake_walk), \
             patch("tools.scholar_runner._find_latest_review", return_value=None), \
             patch("tools.scholar_runner._find_highest_version", return_value=(0, None)), \
             patch("tools.summarizer.summarize", **kernel_patch_kwargs):
            return scholar_runner._run_scan(summarize_deltas=summarize_deltas)


class TestDisabled(_ScholarRunnerTest):
    """summarize_deltas=False keeps the legacy all-strings shape."""

    def test_disabled_returns_plain_strings_only(self):
        big_rel = self._write_lines("big.txt", 1000)
        with patch("tools.summarizer.summarize") as mock_k:
            result = self._run_with_deltas([big_rel], summarize_deltas=False)
            mock_k.assert_not_called()
        # Every delta entry is a string (mandatory ledgers + our scratch).
        for d in result["deltas"]:
            self.assertIsInstance(d, str)
        self.assertFalse(result["summarization_stats"]["enabled"])


class TestEnabledSmallFile(_ScholarRunnerTest):
    """Files ≤ threshold stay as plain path strings, kernel never called."""

    def test_small_file_stays_string(self):
        small_rel = self._write_lines("small.txt", 10)
        with patch("tools.summarizer.summarize") as mock_k:
            result = self._run_with_deltas([small_rel], summarize_deltas=True)
            # Kernel MAY be called for mandatory ledgers (if they're large), so
            # we can't universally assert not_called. Instead, check the
            # scratch file entry shape.
            _ = mock_k
        # Find our scratch entry.
        small_entry = next(
            (d for d in result["deltas"]
             if isinstance(d, str) and d.endswith("small.txt")),
            None,
        )
        self.assertIsNotNone(small_entry, "scratch small.txt missing from deltas")
        self.assertGreaterEqual(result["summarization_stats"]["files_skipped_small"], 1)


class TestEnabledLargeFile(_ScholarRunnerTest):
    """Files > threshold are replaced by {path, summary, ...} dicts."""

    def test_large_file_becomes_dict(self):
        big_rel = self._write_lines("big.txt",
                                    scholar_runner._DELTA_SUMMARIZE_LINE_THRESHOLD + 50)

        def fake(user_content, system_rules, **_kw):
            return ("SUMMARY-BODY", "mock-model")

        with patch("tools.summarizer.summarize", side_effect=fake):
            result = scholar_runner._run_scan(summarize_deltas=True)
            # _run_scan walks the real project, so we can't assert the delta
            # list only contains our file. But our file IS a delta because
            # it was just written. Find it by path.
            big_entry = next(
                (d for d in result["deltas"]
                 if isinstance(d, dict) and d.get("path") == big_rel),
                None,
            )
        self.assertIsNotNone(big_entry,
                             "large scratch file should have been pre-summarized")
        self.assertIn("summary", big_entry)
        self.assertIn("[SUMMARY of", big_entry["summary"])
        self.assertIn("SUMMARY-BODY", big_entry["summary"])
        self.assertIn("[END SUMMARY]", big_entry["summary"])
        self.assertEqual(big_entry["raw_line_count"],
                         scholar_runner._DELTA_SUMMARIZE_LINE_THRESHOLD + 50)
        self.assertGreater(big_entry["raw_bytes"], 0)


class TestEnabledKernelException(_ScholarRunnerTest):
    """Kernel exception on a large file → fall back to plain string."""

    def test_kernel_exception_falls_back_to_string(self):
        big_rel = self._write_lines("big_err.txt",
                                    scholar_runner._DELTA_SUMMARIZE_LINE_THRESHOLD + 20)

        with patch("tools.summarizer.summarize",
                   side_effect=RuntimeError("boom")):
            result = scholar_runner._run_scan(summarize_deltas=True)

        # Our scratch file should appear as a plain string (not a dict) because
        # the kernel failed.
        scratch_entries = [
            d for d in result["deltas"]
            if (isinstance(d, str) and d == big_rel) or
               (isinstance(d, dict) and d.get("path") == big_rel)
        ]
        self.assertEqual(len(scratch_entries), 1)
        self.assertIsInstance(scratch_entries[0], str)
        self.assertGreaterEqual(
            result["summarization_stats"]["files_summarize_failed"], 1
        )


class TestEnabledKernelEmpty(_ScholarRunnerTest):
    """Empty kernel response on a large file → fall back to plain string."""

    def test_empty_kernel_falls_back_to_string(self):
        big_rel = self._write_lines("big_empty.txt",
                                    scholar_runner._DELTA_SUMMARIZE_LINE_THRESHOLD + 20)

        with patch("tools.summarizer.summarize",
                   return_value=("", "mock-model")):
            result = scholar_runner._run_scan(summarize_deltas=True)

        scratch_entries = [
            d for d in result["deltas"]
            if (isinstance(d, str) and d == big_rel) or
               (isinstance(d, dict) and d.get("path") == big_rel)
        ]
        self.assertEqual(len(scratch_entries), 1)
        self.assertIsInstance(scratch_entries[0], str)


class TestStatsShape(_ScholarRunnerTest):
    """summarization_stats block must always be present with expected keys."""

    def test_stats_keys_present(self):
        self._write_lines("tiny.txt", 5)
        with patch("tools.summarizer.summarize",
                   return_value=("MOCK", "mock-model")):
            result = scholar_runner._run_scan(summarize_deltas=True)
        stats = result["summarization_stats"]
        for key in ("files_summarized", "files_skipped_small",
                    "files_summarize_failed", "time_seconds", "enabled"):
            self.assertIn(key, stats, f"summarization_stats missing {key}")
        self.assertTrue(stats["enabled"])
        self.assertGreaterEqual(stats["time_seconds"], 0.0)


class TestSchemaContract(unittest.TestCase):
    """summarize_deltas must appear as a boolean in TOOL_SCHEMA."""

    def test_schema_declares_summarize_deltas(self):
        schema = scholar_runner.TOOL_SCHEMA
        self.assertIn("summarize_deltas", schema)
        self.assertEqual(schema["summarize_deltas"]["type"], "boolean")
        self.assertIn("description", schema["summarize_deltas"])


class TestExecuteWraps(_ScholarRunnerTest):
    """execute() forwards summarize_deltas and returns JSON-parseable output."""

    def test_execute_returns_valid_json_with_summarization_stats(self):
        self._write_lines("tiny2.txt", 5)
        out = scholar_runner.execute(summarize_deltas=False)
        self.assertIsInstance(out, str)
        parsed = json.loads(out)
        self.assertIn("summarization_stats", parsed)
        self.assertFalse(parsed["summarization_stats"]["enabled"])


if __name__ == "__main__":
    unittest.main()
