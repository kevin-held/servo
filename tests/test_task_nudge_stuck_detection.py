"""
Tests for the v0.8.0 task-ledger stuck-detection nudge in
CoreLoop._run_cycle (D-20260419-12).

Covers:
  - Pending ledger + no chained_call + not coming_from_task_nudge
    → returns action="task_nudge" with `_task_nudge`/`_transient` flags.
  - Empty ledger → nudge does NOT fire (no spurious action).
  - `_task_nudge: True` inbound payload → nudge does NOT fire twice in
    a row (prevents runaway self-loop).
  - `autonomous_loop_limit` + loop_index at cap → nudge suppressed,
    falls through to done.
  - Nudge fires even when continuous_mode=False (ungated behavior).
  - Chained call takes precedence over nudge.
  - Nudge message names the cursor task id + description.

Run: pytest tests/test_task_nudge_stuck_detection.py -v
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock


_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Stub heavyweight deps so core.loop imports cleanly. ──
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


def _build_loop(pending_tasks: list,
                reason_response: str = "I'll wait.",
                tool_used=None,
                autonomous_loop_limit: int = 1):
    """Construct a CoreLoop with every IO stubbed out.

    The only real logic exercised is the `_run_cycle` decision tree
    between PERCEIVE and the final directive return. We replace the
    per-step methods with fixed returns so each test targets one branch.
    """
    from core.loop import CoreLoop

    state = MagicMock()
    state.get_conversation_history.return_value = []
    state.get_latest_conversation_summary.return_value = None
    state.get_recent_memory.return_value = []
    state.get_relevant_memory.return_value = []
    state.get_all_active_tasks.return_value = [
        {"id": t["id"], "description": t["description"],
         "status": "pending", "created_at": 0.0, "completed_at": None}
        for t in pending_tasks
    ]
    state.get_pending_tasks.return_value = [
        {"id": t["id"], "description": t["description"],
         "status": "pending", "created_at": 0.0, "completed_at": None}
        for t in pending_tasks
    ]
    state.add_trace = MagicMock()
    state.add_conversation_turn = MagicMock()
    
    # v1.0.0 (D-20260421-16): Ensure state.get returns None so ConfigRegistry 
    # falls back to real JSON values instead of MagicMocks.
    state.get.return_value = None
    state.get_session_flag.return_value = "False"

    ollama = MagicMock()
    ollama.model = "test-model"
    ollama.temperature = 0.7
    ollama.num_predict = 4096
    ollama.last_eval_duration = 0.0
    ollama.last_load_duration = 0.0

    tools = MagicMock()
    tools.get_tool_descriptions.return_value = []

    loop = CoreLoop(state, ollama, tools)
    loop.autonomous_loop_limit = autonomous_loop_limit

    # Stub the per-step helpers so _run_cycle's branch logic runs in
    # isolation. _perceive just needs to hand something to _contextualize
    # that has raw_input/image keys; _reason and _act are short-circuited
    # with canned returns.
    loop._perceive = lambda t, i: {"raw_input": t, "image": i, "type": "user_message", "timestamp": 0.0}
    loop._reason   = lambda ctx, current_loop=0: {"raw_response": reason_response, "tool_plan": None}
    loop._act      = lambda reasoning, current_loop=0: {
        "raw_response": reason_response,
        "response":     reason_response,
        "tool_used":    tool_used,
    }
    loop._integrate = MagicMock()
    loop._trace     = MagicMock()
    loop._set_step  = MagicMock()
    # Swallow the signal emissions — they're Qt-backed stubs anyway.
    loop.response_ready = MagicMock()
    loop.error_occurred = MagicMock()

    return loop


class TestTaskNudgeStuckDetection(unittest.TestCase):

    def test_nudge_fires_when_pending_and_no_chain(self):
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "Read manifest"}],
            reason_response="Let me think...",  # no fenced JSON → no chain
            tool_used=None,
        )
        directive = loop._run_cycle({"text": "hi", "image": ""})
        self.assertEqual(directive["action"], "task_nudge")
        self.assertTrue(directive["payload"]["_task_nudge"])
        self.assertTrue(directive["payload"]["_transient"])
        # Nudge message should name the cursor row so the model doesn't
        # have to parse the render block to know what's next.
        self.assertIn("Read manifest", directive["payload"]["text"])
        self.assertIn("#1", directive["payload"]["text"])

    def test_no_nudge_when_ledger_empty(self):
        loop = _build_loop(
            pending_tasks=[],
            reason_response="Done.",
            tool_used=None,
        )
        directive = loop._run_cycle({"text": "hi", "image": ""})
        # Empty ledger + not continuous_mode + no chain → done.
        self.assertEqual(directive["action"], "done")

    def test_no_nudge_when_coming_from_nudge(self):
        # Non-continuous mode: second cycle in a row sees the
        # `_task_nudge` marker and must NOT re-fire — we prod once, then
        # halt so the operator isn't stuck in a runaway nudge loop when
        # the model goes permanently quiet. (D-20260419-14 refinement.)
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response="Hmm.",
            tool_used=None,
            autonomous_loop_limit=1,
        )
        directive = loop._run_cycle(
            {"text": "", "image": "", "_task_nudge": True, "_transient": True}
        )
        self.assertEqual(directive["action"], "done")

    def test_nudge_re_fires_in_continuous_mode(self):
        # Continuous mode: `_task_nudge` on the inbound payload does NOT
        # suppress a second nudge. The whole point of continuous mode is
        # to persevere on a multi-step plan. Bound comes from
        # autonomous_loop_limit instead, not a single-fire marker.
        # (D-20260419-14 — fix for mid-plan halt bug in continuous mode.)
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response="Hmm.",
            tool_used=None,
            autonomous_loop_limit=2,
        )
        directive = loop._run_cycle(
            {"text": "", "image": "", "_task_nudge": True, "_transient": True}
        )
        self.assertEqual(directive["action"], "task_nudge")
        self.assertTrue(directive["payload"]["_task_nudge"])

    def test_continuous_nudge_still_respects_auto_cap(self):
        # Continuous mode + autonomous_loop_limit=2 + loop_index=1:
        # loop_index >= limit-1 → cap hit → nudge suppressed even though
        # continuous mode would otherwise re-fire. Bounded perseverance.
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response="Hmm.",
            tool_used=None,
            autonomous_loop_limit=2,
        )
        directive = loop._run_cycle(
            {"text": "", "image": "", "_task_nudge": True, "_transient": True},
            loop_index=1,
        )
        # Cap suppresses the nudge. In continuous mode with no tool used,
        # the loop lands on done (not another nudge).
        self.assertNotEqual(directive["action"], "task_nudge")

    def test_nudge_suppressed_when_autonomous_loop_cap_hit(self):
        # autonomous_loop_limit=3, loop_index=2 → loop_index >= limit-1
        # (i.e., next re-entry would be the 4th which exceeds cap).
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response="Hmm.",
            tool_used=None,
            autonomous_loop_limit=3,
        )
        directive = loop._run_cycle({"text": "hi", "image": ""}, loop_index=2)
        # Safety Valve (D-20260421-02): Exactly one nudge is allowed even at cap
        # if a plan is active and this is the first nudge.
        self.assertEqual(directive["action"], "task_nudge")

    def test_nudge_fires_under_cap(self):
        # Same limit=3, but loop_index=0 → plenty of room, nudge fires.
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response="Hmm.",
            tool_used=None,
            autonomous_loop_limit=3,
        )
        directive = loop._run_cycle({"text": "hi", "image": ""}, loop_index=0)
        self.assertEqual(directive["action"], "task_nudge")

    def test_nudge_fires_when_continuous_mode_off(self):
        # The whole point of the nudge: it's UNGATED from continuous_mode.
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response="Hmm.",
            tool_used=None,
            autonomous_loop_limit=1,
        )
        directive = loop._run_cycle({"text": "hi", "image": ""})
        self.assertEqual(directive["action"], "task_nudge")

    def test_chain_takes_precedence_over_nudge(self):
        # If the model DID emit a tool call, let the chain branch run
        # even though the ledger has pending rows — the model is doing
        # the work, no nudge needed.
        chain_response = (
            "Working on it.\n"
            "```json\n"
            "{\"tool\": \"filesystem\", \"args\": {\"operation\": \"list\", \"path\": \".\"}}\n"
            "```"
        )
        loop = _build_loop(
            pending_tasks=[{"id": 1, "description": "A"}],
            reason_response=chain_response,
            tool_used=None,
        )
        # loop_index=0 with default chain_limit=3 → chain branch is allowed.
        directive = loop._run_cycle({"text": "hi", "image": ""}, loop_index=0)
        self.assertEqual(directive["action"], "chain")

    def test_nudge_message_counts_remaining(self):
        loop = _build_loop(
            pending_tasks=[
                {"id": 1, "description": "A"},
                {"id": 2, "description": "B"},
                {"id": 3, "description": "C"},
            ],
            reason_response="Hmm.",
            tool_used=None,
        )
        directive = loop._run_cycle({"text": "hi", "image": ""})
        # Remaining count should appear in the nudge so the model has a
        # proximate progress signal.
        self.assertIn("3", directive["payload"]["text"])


if __name__ == "__main__":
    unittest.main()
