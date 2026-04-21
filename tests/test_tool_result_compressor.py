"""
Tests for core/tool_result_compressor.py (D-20260420-01).

Covers:
  - Below-threshold input → (None, None), kernel NOT called, no log noise.
  - Above-threshold input, kernel success → (wrapped_text, report) with
    the `Tool result (<tool>, compressed N→M chars):\n` prefix.
  - Above-threshold input, kernel returns empty → (None, None), fallback
    to raw.
  - Above-threshold input, kernel raises → (None, None), fallback to raw,
    never re-raises.
  - Wrapped text includes the tool name, both byte counts, and the
    summary body exactly as returned.
  - System rules name the tool and preserve the TAIL-of-pagination rule
    (`[BLOCK N OF M]` footers must survive).
  - User content embeds tool name, args (json.dumps'd), and raw payload.

Run: pytest tests/test_tool_result_compressor.py -v
"""

import sys
import os
import types
import unittest
from pathlib import Path

from unittest.mock import patch, MagicMock


_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Stub heavyweight deps so the module imports cleanly. ──
if "core.ollama_client" not in sys.modules:
    _oc = types.ModuleType("core.ollama_client")
    class ChatCancelled(Exception): pass
    class OllamaClient:
        def __init__(self, *a, **k): pass
        def chat(self, *a, **k): return ("", {})
    _oc.ChatCancelled = ChatCancelled
    _oc.OllamaClient  = OllamaClient
    sys.modules["core.ollama_client"] = _oc


@patch.dict(os.environ, {"SENTINEL_SILENT": "True"})
class TestBelowThreshold(unittest.TestCase):
    """Short tool results must pass through untouched — no kernel call."""

    def test_empty_result_returns_none(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize") as mock_k:
            wrapped, report = maybe_compress_tool_result("filesystem", {}, "")
            self.assertIsNone(wrapped)
            self.assertIsNone(report)
            mock_k.assert_not_called()

    def test_short_result_returns_none(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize") as mock_k:
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {"path": "."}, "short result"
            )
            self.assertIsNone(wrapped)
            self.assertIsNone(report)
            mock_k.assert_not_called()

    def test_none_result_returns_none(self):
        # Defensive: if a tool returned None for some reason, we must
        # not trip str() on it and we must not call the kernel.
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize") as mock_k:
            wrapped, report = maybe_compress_tool_result("x", {}, None)
            self.assertIsNone(wrapped)
            self.assertIsNone(report)
            mock_k.assert_not_called()

    def test_at_threshold_boundary_returns_none(self):
        # Guard exactly at the threshold: `len(...) <= threshold_chars`
        # means the boundary value itself passes through raw.
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize") as mock_k:
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {}, "x" * 100, threshold_chars=100,
            )
            self.assertIsNone(wrapped)
            self.assertIsNone(report)
            mock_k.assert_not_called()

    def test_just_over_threshold_triggers(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize",
                   return_value=("recap", "test-model")) as mock_k:
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {}, "x" * 101, threshold_chars=100,
            )
            self.assertIsNotNone(wrapped)
            self.assertIsNotNone(report)
            mock_k.assert_called_once()


@patch.dict(os.environ, {"SENTINEL_SILENT": "True"})
class TestSuccessfulCompression(unittest.TestCase):
    """Happy path: large result, kernel returns non-empty, wrapper intact."""

    def test_wrapped_text_prefix_shape(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        raw = "x" * 5000
        with patch("core.tool_result_compressor._kernel_summarize",
                   return_value=("listed 47 files under workspace/ (SUCCESS)",
                                 "test-model")):
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {"operation": "list", "path": "workspace"}, raw,
            )
        self.assertIn("Tool result (filesystem, compressed", wrapped)
        self.assertIn("5000→", wrapped)
        # The new-chars count must match the mock summary's actual length
        # — compute it rather than hardcoding to avoid off-by-one drift.
        expected_len = len("listed 47 files under workspace/ (SUCCESS)")
        self.assertIn(f"→{expected_len} chars)", wrapped)
        # The summary body itself is appended after a newline.
        self.assertTrue(wrapped.endswith("listed 47 files under workspace/ (SUCCESS)"))

    def test_report_contents(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        raw = "a" * 5000
        with patch("core.tool_result_compressor._kernel_summarize",
                   return_value=("recap text", "gemma4:26b")):
            _, report = maybe_compress_tool_result(
                "youtube_transcript", {"url": "https://x"}, raw,
            )
        self.assertEqual(report["tool_name"],  "youtube_transcript")
        self.assertEqual(report["orig_chars"], 5000)
        self.assertEqual(report["new_chars"],  10)
        self.assertEqual(report["model_used"], "gemma4:26b")

    def test_non_string_result_stringified(self):
        # Some tools return dicts or lists. The compressor must str()
        # them before length-checking so big structured payloads get
        # compressed just like big string payloads.
        from core.tool_result_compressor import maybe_compress_tool_result
        big_list = ["row-" + "x" * 100 for _ in range(100)]  # >4k when str()'d
        with patch("core.tool_result_compressor._kernel_summarize",
                   return_value=("list recap", "test-model")) as mock_k:
            wrapped, report = maybe_compress_tool_result("x", {}, big_list)
        self.assertIsNotNone(wrapped)
        self.assertIsNotNone(report)
        mock_k.assert_called_once()
        # The kernel received the stringified list, not the raw list object.
        user_content_arg = mock_k.call_args[0][0]
        self.assertIsInstance(user_content_arg, str)


@patch.dict(os.environ, {"SENTINEL_SILENT": "True"})
class TestFailureFallbacks(unittest.TestCase):
    """Compressor must never crash the loop. Both failure modes → raw."""

    def test_empty_kernel_response_returns_none(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize",
                   return_value=("", "test-model")):
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {}, "x" * 5000,
            )
        self.assertIsNone(wrapped)
        self.assertIsNone(report)

    def test_kernel_exception_returns_none(self):
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize",
                   side_effect=RuntimeError("kernel went poof")):
            # Must NOT re-raise — caller relies on the compressor being
            # safe to call inside the hot loop.
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {}, "x" * 5000,
            )
        self.assertIsNone(wrapped)
        self.assertIsNone(report)

    def test_kernel_value_error_on_empty_rules_does_not_escape(self):
        # ValueError is the specific error the kernel raises on empty
        # system_rules. We always pass non-empty rules, but if the code
        # ever drifted, the caller should still be protected.
        from core.tool_result_compressor import maybe_compress_tool_result
        with patch("core.tool_result_compressor._kernel_summarize",
                   side_effect=ValueError("empty rules")):
            wrapped, report = maybe_compress_tool_result(
                "filesystem", {}, "x" * 5000,
            )
        self.assertIsNone(wrapped)
        self.assertIsNone(report)


@patch.dict(os.environ, {"SENTINEL_SILENT": "True"})
class TestPromptShape(unittest.TestCase):
    """Inspect the strings sent to the kernel — they're the actual contract."""

    def test_system_rules_names_tool(self):
        from core.tool_result_compressor import _build_system_rules
        rules = _build_system_rules("youtube_transcript")
        self.assertIn("youtube_transcript", rules)
        # "HARD RULES:" anchors the structured section the model keys on.
        self.assertIn("HARD RULES", rules)

    def test_system_rules_preserves_pagination_tail(self):
        # Rule #4 is load-bearing: paginated tools depend on `[BLOCK N
        # OF M]` footers to know whether to keep reading. The rule body
        # must name that marker explicitly so the summarizer doesn't
        # strip it.
        from core.tool_result_compressor import _build_system_rules
        rules = _build_system_rules("filesystem")
        self.assertIn("BLOCK N OF M", rules)

    def test_system_rules_preserves_error_messages_verbatim(self):
        from core.tool_result_compressor import _build_system_rules
        rules = _build_system_rules("filesystem")
        self.assertIn("VERBATIM", rules)

    def test_user_content_embeds_tool_name_args_and_payload(self):
        from core.tool_result_compressor import _build_user_content
        raw = "line1\nline2\nline3"
        body = _build_user_content("filesystem",
                                   {"operation": "read", "path": "/tmp/x"},
                                   raw)
        self.assertIn("tool: filesystem", body)
        self.assertIn('"operation": "read"', body)
        self.assertIn('"path": "/tmp/x"', body)
        self.assertIn(raw, body)
        # Raw char-count is exposed so the model has a size signal.
        self.assertIn(f"{len(raw)} chars", body)

    def test_user_content_handles_non_json_args(self):
        # Args that json.dumps can't serialize (e.g. a set) should fall
        # back to repr() rather than raising.
        from core.tool_result_compressor import _build_user_content
        body = _build_user_content("x", {"bad": {1, 2, 3}}, "payload")
        # Either json.dumps(default=str) coerced to string, or repr
        # fallback — both are acceptable; what matters is no crash.
        self.assertIn("tool: x", body)
        self.assertIn("payload", body)


if __name__ == "__main__":
    unittest.main()
