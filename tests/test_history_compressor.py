"""
Tests for core/history_compressor.py + the conversation_summary table.

Covers (D-20260419-01, Phase 2 of the summarization rollout):
  - _should_compress predicate boundary cases (below 2×, at 2×, after
    failure backoff)
  - state.save_conversation_summary / get_latest_conversation_summary
    round trip (newest-wins)
  - state.count_conversation_turns_since / get_conversation_turns_range
  - state.clear_conversation also wipes conversation_summary
  - maybe_compress() happy path — trigger fires, kernel called, summary
    persisted, failure marker cleared
  - maybe_compress() empty response — no summary saved, failure marker
    set to current uncompressed count
  - maybe_compress() trigger no-op when threshold not reached
  - maybe_compress() absorbs prior summary into the new one
  - _build_messages filter — turns with id <= covers_to_id are dropped

Run: pytest tests/test_history_compressor.py -v
"""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── Stub heavyweight imports that the production modules require but
#    the test path does not. Specifically: PySide6 (core/loop.py imports
#    QThread/Signal at module scope) and core.ollama_client (imported by
#    loop.py and indirectly by summarizer via lazy import, but we patch
#    that elsewhere). This block must run BEFORE the first `import
#    core.loop` / `import core.history_compressor`.
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
    # core/state.py does `import chromadb` at module level. The test
    # never exercises vector memory, so a module-shaped stub is fine.
    _chromadb = types.ModuleType("chromadb")
    _chromadb.PersistentClient = MagicMock()
    sys.modules["chromadb"] = _chromadb


# ──────────────────────────────────────────────────────────
# _should_compress — pure predicate, no fixtures needed
# ──────────────────────────────────────────────────────────

class TestShouldCompress(unittest.TestCase):
    """Boundary cases for the trigger predicate."""

    def setUp(self):
        # Lazy import so test collection doesn't drag ChromaDB in.
        from core import history_compressor
        self.sc = history_compressor._should_compress

    def test_below_threshold_returns_false(self):
        # Cap=15, 2×=30. At 29 uncompressed we do NOT fire.
        self.assertFalse(self.sc(29, 15, last_failed_at=0))

    def test_at_threshold_returns_true(self):
        # Exactly 30 uncompressed — threshold met.
        self.assertTrue(self.sc(30, 15, last_failed_at=0))

    def test_above_threshold_returns_true(self):
        self.assertTrue(self.sc(100, 15, last_failed_at=0))

    def test_backoff_suppresses_retry(self):
        # Last failure at 30; backoff needs +15 → next attempt at 45.
        # At 30 (same count as failure) — suppressed.
        self.assertFalse(self.sc(30, 15, last_failed_at=30))
        # At 44 — still within backoff window.
        self.assertFalse(self.sc(44, 15, last_failed_at=30))
        # At 45 — backoff cleared.
        self.assertTrue(self.sc(45, 15, last_failed_at=30))

    def test_backoff_zero_means_no_backoff(self):
        # last_failed_at=0 (no prior failure) — threshold alone governs.
        self.assertTrue(self.sc(30, 15, last_failed_at=0))

    def test_tiny_cap_still_works(self):
        # Hardware throttle could push cap down to 3. 2×=6 is the threshold.
        self.assertFalse(self.sc(5, 3, last_failed_at=0))
        self.assertTrue(self.sc(6, 3, last_failed_at=0))


# ──────────────────────────────────────────────────────────
# State-store fixture — real SQLite but temp-dir-scoped
# ──────────────────────────────────────────────────────────

def _make_state():
    """Build a StateStore against a throwaway tempdir.

    Returns (state, cleanup_fn). Uses a stub Chroma client because the
    real one tries to hit disk in ways that make unit tests flaky.
    """
    from core import state as state_module

    tmp = tempfile.mkdtemp()
    db_path     = Path(tmp) / "state.db"
    chroma_path = Path(tmp) / "chroma"

    # Stub chromadb so tests don't need the package installed/loaded.
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

    return store, cleanup


# ──────────────────────────────────────────────────────────
# conversation_summary CRUD
# ──────────────────────────────────────────────────────────

class TestConversationSummaryTable(unittest.TestCase):

    def setUp(self):
        self.state, self._cleanup = _make_state()

    def tearDown(self):
        self._cleanup()

    def test_latest_is_none_on_empty_table(self):
        self.assertIsNone(self.state.get_latest_conversation_summary())

    def test_save_and_get_roundtrip(self):
        sid = self.state.save_conversation_summary(
            "Kevin asked about X.", 1, 30, "gemma4:26b",
        )
        self.assertIsInstance(sid, int)
        row = self.state.get_latest_conversation_summary()
        self.assertIsNotNone(row)
        self.assertEqual(row["summary"],        "Kevin asked about X.")
        self.assertEqual(row["covers_from_id"], 1)
        self.assertEqual(row["covers_to_id"],   30)
        self.assertEqual(row["model_used"],     "gemma4:26b")
        self.assertGreater(row["created_at"],   0)

    def test_latest_wins_on_multiple_rows(self):
        self.state.save_conversation_summary("old", 1, 10, "m1")
        self.state.save_conversation_summary("new", 1, 20, "m2")
        row = self.state.get_latest_conversation_summary()
        self.assertEqual(row["summary"],      "new")
        self.assertEqual(row["covers_to_id"], 20)

    def test_count_conversation_turns_since(self):
        # Empty — 0.
        self.assertEqual(self.state.count_conversation_turns_since(0), 0)
        # Add 5 turns.
        for i in range(5):
            self.state.add_conversation_turn("user", f"msg {i}")
        self.assertEqual(self.state.count_conversation_turns_since(0), 5)
        # With a cutoff in the middle.
        newest = self.state.get_newest_conversation_id()
        self.assertEqual(self.state.count_conversation_turns_since(newest - 2), 2)

    def test_get_conversation_turns_range(self):
        for i in range(5):
            self.state.add_conversation_turn("user", f"msg {i}")
        newest = self.state.get_newest_conversation_id()
        rng = self.state.get_conversation_turns_range(newest - 4, newest - 2)
        self.assertEqual(len(rng), 3)
        # Oldest-first ordering.
        self.assertEqual(rng[0]["id"], newest - 4)
        self.assertEqual(rng[-1]["id"], newest - 2)

    def test_clear_conversation_also_wipes_summary(self):
        self.state.save_conversation_summary("live", 1, 10, "m1")
        self.assertIsNotNone(self.state.get_latest_conversation_summary())
        self.state.clear_conversation()
        self.assertIsNone(self.state.get_latest_conversation_summary())


# ──────────────────────────────────────────────────────────
# maybe_compress — end-to-end with kernel mocked
# ──────────────────────────────────────────────────────────

class TestMaybeCompress(unittest.TestCase):

    def setUp(self):
        self.state, self._cleanup = _make_state()
        # Seed: 35 user turns → over the 2×15 threshold.
        for i in range(35):
            self.state.add_conversation_turn("user", f"msg {i}")
        from core import history_compressor
        self.hc = history_compressor

    def tearDown(self):
        self._cleanup()

    def _patch_kernel(self, returns=("compressed summary", "gemma4:26b")):
        return patch.object(self.hc, "_kernel_summarize", return_value=returns)

    def test_threshold_not_met_returns_none(self):
        # Wipe and reseed with only 29 turns.
        self.state.clear_conversation()
        for i in range(29):
            self.state.add_conversation_turn("user", f"msg {i}")
        with self._patch_kernel() as spy:
            report = self.hc.maybe_compress(self.state, history_cap=15)
        self.assertIsNone(report)
        spy.assert_not_called()

    def test_happy_path_persists_summary(self):
        with self._patch_kernel(("a tight paragraph", "m1")) as spy:
            report = self.hc.maybe_compress(self.state, history_cap=15)
        self.assertIsNotNone(report)
        spy.assert_called_once()
        self.assertEqual(report["turns_compressed"], 20)  # 35 - 15
        self.assertEqual(report["covers_from_id"],   1)
        self.assertEqual(report["covers_to_id"],     20)
        self.assertEqual(report["model_used"],       "m1")

        # Persisted row matches.
        row = self.state.get_latest_conversation_summary()
        self.assertEqual(row["summary"],      "a tight paragraph")
        self.assertEqual(row["covers_to_id"], 20)
        # Failure marker cleared.
        self.assertEqual(self.state.get(self.hc._FAILURE_STATE_KEY), "0")

    def test_empty_response_sets_failure_marker_no_save(self):
        with self._patch_kernel(("", "m1")):
            report = self.hc.maybe_compress(self.state, history_cap=15)
        self.assertIsNone(report)
        # No summary persisted.
        self.assertIsNone(self.state.get_latest_conversation_summary())
        # Failure marker reflects current uncompressed count.
        self.assertEqual(self.state.get(self.hc._FAILURE_STATE_KEY), "35")

    def test_backoff_suppresses_immediate_retry(self):
        # Simulate a prior failure at 35.
        self.state.set(self.hc._FAILURE_STATE_KEY, "35")
        with self._patch_kernel() as spy:
            report = self.hc.maybe_compress(self.state, history_cap=15)
        self.assertIsNone(report)
        spy.assert_not_called()

    def test_absorbs_prior_summary(self):
        # Seed a prior summary covering ids 1..10.
        self.state.save_conversation_summary("prior recap", 1, 10, "m0")
        # Uncompressed now = 25 (ids 11..35). Not yet 2×15=30, so push it up.
        for i in range(5):
            self.state.add_conversation_turn("user", f"extra {i}")
        # Now uncompressed = 30. Should fire.

        captured = {}

        def _spy(user_content, system_rules, **_kwargs):
            captured["user_content"] = user_content
            captured["system_rules"] = system_rules
            return ("merged summary", "m1")

        with patch.object(self.hc, "_kernel_summarize", side_effect=_spy):
            report = self.hc.maybe_compress(self.state, history_cap=15)

        self.assertIsNotNone(report)
        # Prior summary text must have been sent into the kernel.
        self.assertIn("PRIOR SUMMARY", captured["user_content"])
        self.assertIn("prior recap",   captured["user_content"])
        # covers_from_id should reflect the absorbed prior range (1), not
        # the new starting cutoff (11).
        self.assertEqual(report["covers_from_id"], 1)
        # covers_to_id is newest_id - history_cap = 40 - 15 = 25.
        self.assertEqual(report["covers_to_id"], 25)

    def test_kernel_exception_is_swallowed(self):
        with patch.object(self.hc, "_kernel_summarize",
                          side_effect=RuntimeError("kernel blew up")):
            report = self.hc.maybe_compress(self.state, history_cap=15)
        self.assertIsNone(report)
        # Failure marker set so we back off before retry.
        self.assertEqual(self.state.get(self.hc._FAILURE_STATE_KEY), "35")


# ──────────────────────────────────────────────────────────
# _build_messages filter — turns covered by summary are dropped
# ──────────────────────────────────────────────────────────

class TestBuildMessagesFilter(unittest.TestCase):
    """
    The filter lives on the CortexLoop instance. We instantiate the
    bound method by hand rather than spinning up the whole loop.
    """

    def _call_build_messages(self, context):
        from core.loop import CoreLoop
        # The method does not use self, it only reads from context.
        # Bind-via-descriptor is fine for unit test.
        return CoreLoop._build_messages(MagicMock(), context)

    def test_no_summary_passes_all_turns(self):
        ctx = {
            "input": "new question",
            "history": [
                {"id": 1, "role": "user",      "content": "hi"},
                {"id": 2, "role": "assistant", "content": "hello"},
            ],
        }
        msgs = self._call_build_messages(ctx)
        # Two history + one user input = 3.
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["content"], "hi")
        self.assertEqual(msgs[-1]["content"], "new question")

    def test_summary_filters_covered_turns(self):
        ctx = {
            "input": "new question",
            "history_summary": {"covers_to_id": 10, "summary": "prior"},
            "history": [
                {"id": 9,  "role": "user",      "content": "old — drop"},
                {"id": 10, "role": "assistant", "content": "also drop"},
                {"id": 11, "role": "user",      "content": "keep me"},
                {"id": 12, "role": "assistant", "content": "and me"},
            ],
        }
        msgs = self._call_build_messages(ctx)
        # 2 surviving history turns + 1 user input.
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["content"], "keep me")
        self.assertEqual(msgs[1]["content"], "and me")
        self.assertEqual(msgs[-1]["content"], "new question")

    def test_turns_without_id_are_kept(self):
        # Legacy rows (pre-Phase-2) have no id field — filter must not
        # drop them.
        ctx = {
            "input": "new question",
            "history_summary": {"covers_to_id": 10, "summary": "prior"},
            "history": [
                {"role": "user", "content": "legacy row"},
                {"id": 11, "role": "user", "content": "keep me"},
            ],
        }
        msgs = self._call_build_messages(ctx)
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["content"], "legacy row")
        self.assertEqual(msgs[1]["content"], "keep me")


if __name__ == "__main__":
    unittest.main()
