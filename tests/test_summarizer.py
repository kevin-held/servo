"""
Tests for tools/summarizer.py — the factored-out summarization kernel
(D-20260418-10, Phase 1 of the summarization rollout).

Covers the non-network paths:
  - detect_loaded_model() fallback when Ollama is unreachable or empty
  - summarize() ValueError on empty system_rules
  - summarize() empty-input passthrough (no client call)
  - summarize() tail-preserve trim on oversized input
  - summarize() happy path with a mocked OllamaClient (no real Ollama needed)
  - summarize() empty-response passthrough (client returns "" → kernel returns "")
  - summarize() explicit model= pin bypasses detect_loaded_model()

Run: pytest tests/test_summarizer.py -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path so `from tools.summarizer ...` resolves.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import summarizer  # noqa: E402


class TestDetectLoadedModel(unittest.TestCase):
    """detect_loaded_model() must degrade gracefully when Ollama is absent."""

    def test_fallback_on_connection_error(self):
        """Connection refused → fallback."""
        with patch("requests.get", side_effect=ConnectionError("nope")):
            name = summarizer.detect_loaded_model(fallback="my-fallback")
            self.assertEqual(name, "my-fallback")

    def test_fallback_on_timeout(self):
        """Probe timeout → fallback."""
        import requests
        with patch("requests.get", side_effect=requests.exceptions.Timeout()):
            name = summarizer.detect_loaded_model(fallback="my-fallback")
            self.assertEqual(name, "my-fallback")

    def test_fallback_on_empty_models_list(self):
        """Ollama up but no model loaded → fallback."""
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"models": []}
        with patch("requests.get", return_value=fake_resp):
            name = summarizer.detect_loaded_model(fallback="my-fallback")
            self.assertEqual(name, "my-fallback")

    def test_returns_loaded_model_name(self):
        """Ollama reports a loaded model → use its name."""
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"models": [{"name": "gemma4:26b"}]}
        with patch("requests.get", return_value=fake_resp):
            name = summarizer.detect_loaded_model(fallback="my-fallback")
            self.assertEqual(name, "gemma4:26b")

    def test_default_fallback_is_gemma(self):
        """When fallback arg is not passed, default is gemma4:26b."""
        with patch("requests.get", side_effect=ConnectionError("nope")):
            name = summarizer.detect_loaded_model()
            self.assertEqual(name, "gemma4:26b")


class TestSummarizeValidation(unittest.TestCase):
    """summarize() input validation happens before any network call."""

    def test_empty_system_rules_raises(self):
        """Empty system_rules is a wiring bug — refuse to proceed."""
        with self.assertRaises(ValueError):
            summarizer.summarize("some content", "")

    def test_none_system_rules_raises(self):
        """None system_rules is also a wiring bug."""
        with self.assertRaises(ValueError):
            summarizer.summarize("some content", None)  # type: ignore[arg-type]

    def test_empty_input_returns_empty_summary_and_model(self):
        """
        Empty user_content is a no-op — kernel returns ("", model_name)
        without making a network call. The model_name still reflects the
        auto-detect so the caller can log "summarizer returned nothing
        because input was empty" with an accurate model attribution.
        """
        with patch.object(summarizer, "detect_loaded_model",
                          return_value="some-model"):
            summary, model_used = summarizer.summarize("", "some rules")
            self.assertEqual(summary, "")
            self.assertEqual(model_used, "some-model")


class TestSummarizeHappyPath(unittest.TestCase):
    """summarize() with a mocked OllamaClient — no real Ollama needed."""

    def _patched_client(self, content="bullet summary"):
        """Build a fake OllamaClient whose .chat() returns a fixed response."""
        fake_client = MagicMock()
        fake_client.chat.return_value = (content, {"meta": "ignored"})

        fake_module = MagicMock()
        fake_module.OllamaClient = MagicMock(return_value=fake_client)
        return fake_client, fake_module

    def test_happy_path_returns_stripped_content(self):
        """A normal chat response is .strip()-ed and returned verbatim."""
        fake_client, fake_module = self._patched_client("  - bullet one\n- bullet two  \n")
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model",
                          return_value="gemma4:26b"):
            summary, model_used = summarizer.summarize(
                "some user content",
                "system rules here",
            )
            self.assertEqual(summary, "- bullet one\n- bullet two")
            self.assertEqual(model_used, "gemma4:26b")

    def test_empty_response_passthrough(self):
        """Model returning '' means kernel returns '' — caller decides if fatal."""
        fake_client, fake_module = self._patched_client("")
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model",
                          return_value="gemma4:26b"):
            summary, model_used = summarizer.summarize("content", "rules")
            self.assertEqual(summary, "")
            self.assertEqual(model_used, "gemma4:26b")

    def test_explicit_model_bypasses_detect(self):
        """
        model="foo:1b" passed in → detect_loaded_model must NOT be called.
        This is load-bearing for callers that want deterministic summarizer
        behavior regardless of what Ollama reports as loaded.
        """
        fake_client, fake_module = self._patched_client("ok")
        detect_spy = MagicMock(return_value="should-not-be-used")
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model", detect_spy):
            summary, model_used = summarizer.summarize(
                "content", "rules", model="foo:1b",
            )
            detect_spy.assert_not_called()
            self.assertEqual(model_used, "foo:1b")
            # Confirm the client was instantiated with the explicit model.
            fake_module.OllamaClient.assert_called_once_with(model="foo:1b")

    def test_oversized_input_is_tail_preserved(self):
        """
        When user_content > max_input_chars, the TAIL is kept. This is
        the last-resort trim; callers with priority-aware rules should
        trim before calling. Verify by inspecting what was sent to
        OllamaClient.chat.
        """
        fake_client, fake_module = self._patched_client("ok")
        big_input = ("head_" * 100) + ("tail_" * 100)  # 1000 chars
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model",
                          return_value="m"):
            summary, _ = summarizer.summarize(
                big_input, "rules", max_input_chars=500,
            )
            # Inspect the messages list sent into chat().
            args, kwargs = fake_client.chat.call_args
            # chat(system_prompt, messages, timeout=...) — positional
            system_prompt_sent = args[0]
            messages_sent      = args[1]
            self.assertEqual(system_prompt_sent, "rules")
            self.assertEqual(len(messages_sent), 1)
            self.assertEqual(messages_sent[0]["role"], "user")
            content_sent = messages_sent[0]["content"]
            # Trimmed to exactly 500 chars, and it's the TAIL of big_input.
            self.assertEqual(len(content_sent), 500)
            self.assertEqual(content_sent, big_input[-500:])
            # Tail marker "tail_" should dominate; "head_" should be absent.
            self.assertIn("tail_", content_sent)
            self.assertNotIn("head_", content_sent)

    def test_under_max_input_is_unmodified(self):
        """Inputs under the cap reach the model verbatim."""
        fake_client, fake_module = self._patched_client("ok")
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model", return_value="m"):
            summarizer.summarize("short input", "rules", max_input_chars=1000)
            args, _ = fake_client.chat.call_args
            messages_sent = args[1]
            self.assertEqual(messages_sent[0]["content"], "short input")

    def test_timeout_is_forwarded(self):
        """The timeout= kwarg reaches OllamaClient.chat unchanged."""
        fake_client, fake_module = self._patched_client("ok")
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model", return_value="m"):
            summarizer.summarize("content", "rules", timeout=42)
            _, kwargs = fake_client.chat.call_args
            self.assertEqual(kwargs.get("timeout"), 42)

    def test_default_timeout_is_300(self):
        """Unspecified timeout falls through to 300s default."""
        fake_client, fake_module = self._patched_client("ok")
        with patch.dict(sys.modules, {"core.ollama_client": fake_module}), \
             patch.object(summarizer, "detect_loaded_model", return_value="m"):
            summarizer.summarize("content", "rules")
            _, kwargs = fake_client.chat.call_args
            self.assertEqual(kwargs.get("timeout"), 300)


class TestLogSummarizerIntegration(unittest.TestCase):
    """log_summarizer._summarize must route through the kernel."""

    def test_log_summarizer_calls_kernel(self):
        """
        The refactored log_summarizer._summarize imports and calls
        tools.summarizer.summarize. Patch the kernel and verify the call
        shape.

        We also stub `core.ollama_client` in sys.modules up front. The
        kernel's happy-path uses a lazy import of OllamaClient that the
        patched kernel should never reach — but belt-and-suspenders: if
        a future refactor moves the import earlier, the stub guarantees
        the test does not accidentally start reaching for the real
        Ollama (or choking on a half-synced file from a dev's OneDrive
        mount).
        """
        from tools import log_summarizer

        fake_ollama_module = MagicMock()
        fake_entries = [
            {"level": "INFO", "component": "test", "message": "hello",
             "timestamp_utc": "2026-04-18T00:00:00Z", "context": {}},
        ]
        with patch.dict(sys.modules, {"core.ollama_client": fake_ollama_module}), \
             patch("tools.summarizer.summarize",
                   return_value=("digest", "gemma4:26b")) as kernel_spy:
            summary, model_used = log_summarizer._summarize(fake_entries)
            kernel_spy.assert_called_once()
            self.assertEqual(summary, "digest")
            self.assertEqual(model_used, "gemma4:26b")
            # The caller must pass (user_content, system_rules) positionally
            # in that order — confirm the contract.
            args, _ = kernel_spy.call_args
            self.assertEqual(len(args), 2)
            user_content, system_rules = args
            self.assertIn("INCIDENTS", user_content)
            self.assertIn("ROUTINE", user_content)
            # system_rules must contain the log-specific hard rules.
            self.assertIn("HARD RULES", system_rules)


if __name__ == "__main__":
    unittest.main()
