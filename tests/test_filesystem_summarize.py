"""
Tests for the `summarize` flag on filesystem:read (Phase 3, D-20260419-04).

Covers:
  - default False → plain read unchanged (no kernel call)
  - summarize=True happy path with mocked summarizer → wrapped envelope
  - summarize=True empty-kernel response → raw body with inline marker
  - summarize=True kernel exception → raw body with SUMMARIZER FAILED marker
  - summarize=True + block pagination → body summarized, footer preserved
  - summarize=True + max_lines → body is the truncated slice, footer preserved
  - TOOL_SCHEMA contract: `summarize` key present with boolean type

Run: pytest tests/test_filesystem_summarize.py -v
"""

import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import filesystem  # noqa: E402


class _FSRead(unittest.TestCase):
    """Base class that writes a scratch file under the project's `tests/` dir.

    The filesystem tool rejects absolute paths, so the scratch file must live
    INSIDE the project tree. We write under `tests/` and clean up after.
    """

    def setUp(self):
        self.tmpname = f"tests/_fs_summarize_scratch_{os.getpid()}.txt"
        self.abs_path = _ROOT / self.tmpname

    def tearDown(self):
        if self.abs_path.exists():
            self.abs_path.unlink()

    def _write(self, text: str):
        self.abs_path.parent.mkdir(parents=True, exist_ok=True)
        self.abs_path.write_text(text, encoding="utf-8")


class TestSummarizeDefault(_FSRead):
    """Default summarize=False must not touch the kernel or the body."""

    def test_default_returns_raw_body(self):
        self._write("hello\nworld\n")
        with patch("tools.summarizer.summarize") as mock_k:
            out = filesystem.execute("read", self.tmpname)
            mock_k.assert_not_called()
        self.assertEqual(out, "hello\nworld\n")

    def test_explicit_false_returns_raw_body(self):
        self._write("alpha\nbeta\n")
        with patch("tools.summarizer.summarize") as mock_k:
            out = filesystem.execute("read", self.tmpname, summarize=False)
            mock_k.assert_not_called()
        self.assertEqual(out, "alpha\nbeta\n")


class TestSummarizeHappyPath(_FSRead):
    """summarize=True wraps the kernel's output in [SUMMARY ...] markers."""

    def test_non_empty_kernel_produces_envelope(self):
        body = "line1\nline2\nline3\n"
        self._write(body)
        with patch("tools.summarizer.summarize",
                   return_value=("condensed view of three lines", "mock-model")) as mock_k:
            out = filesystem.execute("read", self.tmpname, summarize=True)
            mock_k.assert_called_once()
        # Envelope shape: header, summary text, footer marker.
        self.assertIn("[SUMMARY of ", out)
        self.assertIn(self.tmpname.replace("\\", "/"), out)
        self.assertIn("3 lines]", out)
        self.assertIn("condensed view of three lines", out)
        self.assertIn("[END SUMMARY]", out)
        # Raw body MUST NOT appear in the envelope — otherwise we pay the token
        # cost of both the summary and the verbatim file.
        self.assertNotIn("line1", out)

    def test_kernel_receives_full_body(self):
        """The kernel must see the file's bytes, not a truncated slice."""
        body = "a" * 200 + "\n" + "b" * 200 + "\n"
        self._write(body)
        captured = {}

        def fake(user_content, system_rules, **_kw):
            captured["content"] = user_content
            captured["rules"] = system_rules
            return ("ok", "mock-model")

        with patch("tools.summarizer.summarize", side_effect=fake):
            filesystem.execute("read", self.tmpname, summarize=True)

        self.assertEqual(captured["content"], body)
        self.assertTrue(captured["rules"], "system_rules must be non-empty")


class TestSummarizeEmptyKernel(_FSRead):
    """Empty kernel response falls back to the raw body with an inline marker."""

    def test_empty_string_response_returns_raw_with_marker(self):
        body = "keep this intact\n"
        self._write(body)
        with patch("tools.summarizer.summarize", return_value=("", "mock-model")):
            out = filesystem.execute("read", self.tmpname, summarize=True)
        self.assertIn("[SUMMARIZER RETURNED EMPTY", out)
        self.assertIn("keep this intact", out)
        # The raw body is preserved verbatim so the caller isn't left empty-handed.
        self.assertIn(body.strip(), out)


class TestSummarizeKernelException(_FSRead):
    """Kernel exception is caught and the read still returns something usable."""

    def test_exception_returns_raw_with_failed_marker(self):
        body = "still readable\n"
        self._write(body)
        with patch("tools.summarizer.summarize",
                   side_effect=RuntimeError("ollama down")):
            out = filesystem.execute("read", self.tmpname, summarize=True)
        self.assertIn("[SUMMARIZER FAILED", out)
        self.assertIn("ollama down", out)
        self.assertIn("still readable", out)


class TestSummarizeWithPagination(_FSRead):
    """Block pagination runs first; the summarizer sees the selected slice,
    and the [BLOCK N OF M] footer is appended AFTER the summary envelope so
    the model still gets the navigation hint."""

    def test_summarize_on_paginated_read_preserves_footer(self):
        # Write a file larger than _BLOCK_SIZE so pagination engages.
        body = ("x" * 100 + "\n") * 400  # ~40_400 chars
        self.assertGreater(len(body), filesystem._BLOCK_SIZE)
        self._write(body)

        captured = {}

        def fake(user_content, system_rules, **_kw):
            captured["content_len"] = len(user_content)
            return ("condensed-slice", "mock-model")

        with patch("tools.summarizer.summarize", side_effect=fake):
            out = filesystem.execute("read", self.tmpname, block=0, summarize=True)

        # The summarizer was handed exactly one block worth of content.
        self.assertEqual(captured["content_len"], filesystem._BLOCK_SIZE)
        # The envelope wrapped the slice, not the full file.
        self.assertIn("[SUMMARY of ", out)
        self.assertIn("condensed-slice", out)
        # The pagination footer survived intact.
        self.assertIn("[BLOCK 0 OF ", out)
        self.assertIn("block=1", out)


class TestSummarizeWithMaxLines(_FSRead):
    """max_lines is applied before summarization; the truncation footer
    survives alongside the summary envelope."""

    def test_summarize_on_max_lines_slice(self):
        body = "\n".join(f"line {i}" for i in range(100)) + "\n"
        self._write(body)

        captured = {}

        def fake(user_content, system_rules, **_kw):
            captured["content"] = user_content
            return ("condensed-head", "mock-model")

        with patch("tools.summarizer.summarize", side_effect=fake):
            out = filesystem.execute("read", self.tmpname,
                                     max_lines=10, summarize=True)

        # The summarizer saw exactly the first 10 lines, not the whole file.
        self.assertIn("line 0", captured["content"])
        self.assertIn("line 9", captured["content"])
        self.assertNotIn("line 10", captured["content"])
        # The envelope + truncation footer both land.
        self.assertIn("[SUMMARY of ", out)
        self.assertIn("condensed-head", out)
        self.assertIn("[Showing first 10 of 100 total lines]", out)


class TestSchemaContract(unittest.TestCase):
    """Tool-registry contract: summarize must appear as a boolean in TOOL_SCHEMA."""

    def test_schema_declares_summarize(self):
        schema = filesystem.TOOL_SCHEMA
        self.assertIn("summarize", schema)
        self.assertEqual(schema["summarize"]["type"], "boolean")
        self.assertIn("description", schema["summarize"])


if __name__ == "__main__":
    unittest.main()
