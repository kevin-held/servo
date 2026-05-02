# lx_cognates.py
#
# Phase C -- real Cognate bodies. UPGRADE_PLAN_2 sec 7 steps 2-8.
#
# Each Cognate returns a state-delta dict that lx_StateStore.apply_delta
# merges into the Sovereign Ledger. The delta MUST advance current_step
# (or set halt=True) or the loop stalls. Cognates access the active store
# via self.core._active_store, stashed there by ServoCore.run_cycle at
# loop start.
#
# Dispatch surface is restricted to the atomic primitives from D-20260421-14:
# file_read, file_write, file_list, file_manage, map_project, summarizer.
# The other TOOL_IS_SYSTEM tools (task, system_config, context_dump,
# memory_manager, memory_snapshot) are filtered out per D-20260422-05 and
# addressed in Phase D.
#
# D-20260423.

from __future__ import annotations

import ast
import hashlib
import json
import math
import random
import re
import time
from pathlib import Path
from typing import Optional

from core.lx_outcomes import ToolOutcome
from core.tool_call_parser import parse_tool_call, strip_tool_calls
from benchmark.criteria.lx_lexicon import FAIL_PATTERNS


# Atomic primitives the dispatch surface will actually run.
# Phase D (UPGRADE_PLAN_3 sec 2) expands this from six to eleven by bringing
# the TOOL_IS_SYSTEM tools under Cognate control. The rewire is safe
# because lx_loop_shim redirects legacy sqlite3 writes away from
# state/state.db into a Cognate-owned path, and LxLoopAdapter satisfies
# the _get_loop_ref surface system_config/context_dump read from.
# Kept as a tuple so accidental mutation is a type error, not a silent drift.
ATOMIC_PRIMITIVES = (
    # Phase C original six.
    "file_read", "file_write", "file_list", "file_manage",
    "map_project", "summarizer",
    # Phase D additions -- TOOL_IS_SYSTEM tools rewired via lx_loop_shim.
    "task", "system_config", "context_dump",
    "memory_manager", "memory_snapshot",
)


# Dispatch-level forbidden list. Empty under Phase D -- every tool the
# Cognate selects is either in ATOMIC_PRIMITIVES or gets skip()ed by
# the registry. Kept as a constant so a future Phase E gate has a
# single place to re-add exclusions.
_FORBIDDEN_TOOLS = frozenset()


# Phase E (UPGRADE_PLAN_4 sec 4 step 3) -- tools whose state.db I/O is
# rerouted via an injected conn_factory kwarg instead of the Phase D
# sqlite3.connect() monkey-patch. When lx_Act dispatches one of these,
# it builds a factory aimed at the Cognate-owned lx_memory.db and
# injects it into the tool_context.conn_factory field. Tools not in
# this set dispatch with their args unchanged.
_MEMORY_TOOLS = frozenset({
    "task", "memory_manager", "memory_snapshot", "context_dump",
})

# Phase F (UPGRADE_PLAN_5 sec 7) -- tools whose execute() signature
# accepts an optional `tool_context` kwarg. lx_Act builds a ToolContext
# per dispatch and injects it for any tool in this set so the legacy
# `_get_loop_ref` shim install can be retired in run_cycle. Adding a
# tool to this set requires that tool's execute() to declare
# `tool_context=None` as a keyword-only arg (see Phase F Step 2 work).
_CONTEXT_TOOLS = _MEMORY_TOOLS | frozenset({"system_config"})


# Phase G (UPGRADE_PLAN_6 sec 3e) -- the static cold-start lookup table
# (`_COLD_START_LOOKUP`) and the `_observation_signal` classifier that fed
# it have been deleted. They were a hand-tuned, three-branch heuristic
# that pre-Phase G stood in for the missing semantic memory of "what
# environment did I see last time, and what worked there?". Phase G
# delivers that memory directly via the env_snapshots ChromaDB
# collection (sec 3a-3b): on a procedural_wins miss, lx_Reason._exploit
# now queries env_snapshots for the closest historical environment audit
# and exploits the tool that won there. Double-miss (no procedural_wins,
# no env_snapshots neighbor) falls through to neutral epsilon-greedy
# exploration, which is a strictly better policy than committing to a
# hand-coded default tool. Removing the table also retires the heuristic
# branches it encoded (`empty_project`, `drift_detected`, `directory_scan`)
# -- those concepts no longer have a home in the runtime.


# e-greedy hyperparameters (UPGRADE_PLAN_2 sec 6, first-pass literals).
# Move to ConfigRegistry in Phase E; hardcoded here is intentional scope.
_EPSILON_0 = 0.3
_LAMBDA = 0.001


# Pre-compiled lexicon matcher. FAIL_PATTERNS is the single source of truth
# for prose-noise detection; importing it here rather than duplicating keeps
# the Cognate gate in lockstep with the Phase A audit signal.
_LEXICON_RE = re.compile("|".join(FAIL_PATTERNS), re.IGNORECASE)


class Cognate:
    """Polymorphic base for all Servo Cognates.

    Every concrete Cognate implements execute(state) and returns a dict
    delta. Cognates that need the active store access it via
    self.core._active_store (set by ServoCore.run_cycle for the duration
    of the loop).
    """

    def __init__(self, core):
        self.core = core

    def execute(self, state: dict) -> dict:
        raise NotImplementedError


# --- lx_Observe ------------------------------------------------

class lx_Observe(Cognate):
    """Sensor array -- environment audit (UPGRADE_PLAN_2 sec 7 step 4 + Phase D sec 5).

    Ports the --chores structural-sweep pattern (D-20260422-06). Emits
    an observation_signature the downstream Cognates use as the key for
    procedural_wins lookups.

    Phase D refinement: per-root signal is a 5-tuple captured via ast.parse,
    not a bare file count. The signature now registers when a class or
    function is added/removed even if no new file was created, which gives
    the exploit branch a finer-grained signal to rank against. Parse
    results are cached on (path, mtime, size) so stable files cost ~0.
    """

    # Canonical root dirs covered by the --chores structural sweep.
    _OBSERVE_ROOTS = ("core", "gui", "tools", "codex")

    # Sentinel tuple for unreadable/broken files -- stable across cycles
    # so one broken file doesn't masquerade as new symbolic drift.
    _PARSE_SENTINEL = (-1, -1, -1, -1, -1)

    def __init__(self, core):
        super().__init__(core)
        # Cache: {absolute_file_path_str: ((mtime_ns, size), tuple5)}
        # Keyed per Cognate instance; survives across cycles in a single
        # ServoCore run. Rebuilt on a fresh Cognate (e.g. test tear-down).
        self._ast_cache: dict = {}

    def execute(self, state: dict) -> dict:
        # Phase F (UPGRADE_PLAN_5 sec 6) -- chat-as-perception gate.
        # OBSERVE consumes one perception event per cycle. Two kinds:
        #
        #   "tool_output"  - cross-cycle followup. ACT writes
        #                    state["pending_tool_output"] when a tool
        #                    dispatch lands; the next OBSERVE turns
        #                    that into a perception so REASON can see
        #                    "what the tool just did" as the input
        #                    text. We check this slot FIRST so a fresh
        #                    user input in the queue can't starve the
        #                    in-flight followup -- the cognate loop
        #                    must clear pending_tool_output before
        #                    OBSERVE will accept new chat.
        #
        #   "user_input"   - human talking. ServoCore.perception_queue
        #                    is fed by submit_perception; we pop the
        #                    head when the queue is non-empty. When
        #                    it's empty we PARK on perception_cond
        #                    until either a producer notifies or
        #                    halt_event is set. Parking with a timeout
        #                    keeps us responsive to halt without a
        #                    busy-loop.
        #
        # This replaces the Phase E behavior of running env_audit on
        # every tick regardless of whether anything happened. The
        # audit + signature + embedding still run every cycle (REASON
        # needs them), but they run AFTER we have a perception, so
        # the loop is genuinely event-driven.
        perception_event = None
        observation_kind = "user_input"
        perception_text = ""

        # 1. Cross-cycle tool followup wins. Reading via .get keeps us
        # tolerant of stores that don't pre-seed the slot.
        pending = state.get("pending_tool_output") if isinstance(state, dict) else None
        if pending:
            perception_event = dict(pending) if isinstance(pending, dict) else {
                "kind": "tool_output",
                "tool_result": str(pending),
            }
            perception_event.setdefault("kind", "tool_output")
            observation_kind = perception_event.get("kind", "tool_output")
            # Surface a human-readable text so REASON's user-message
            # builder has something concrete to render. The shape of
            # tool_result is the dict ACT writes (see lx_Act); we
            # serialize it to JSON for prompt insertion. Plain strings
            # pass through.
            tr = perception_event.get("tool_result", perception_event.get("text", ""))
            if isinstance(tr, (dict, list)):
                try:
                    perception_text = json.dumps(tr, default=str)
                except Exception:
                    perception_text = str(tr)
            else:
                perception_text = str(tr or "")

        # 2. Else park on the perception queue until a user input
        #    arrives or halt fires.
        if perception_event is None:
            queue = getattr(self.core, "perception_queue", None)
            cond = getattr(self.core, "perception_cond", None)
            halt = getattr(self.core, "halt_event", None)
            if queue is not None and cond is not None:
                with cond:
                    # Loop until we either pop a perception or see a
                    # halt. The 0.5s timeout is the wake-up budget --
                    # short enough that the run_cycle's halt-on-state
                    # watchdog stays responsive on stores that don't
                    # use halt_event, but long enough to keep the
                    # loop quiet when nothing's happening.
                    while not queue:
                        if halt is not None and halt.is_set():
                            break
                        cond.wait(timeout=0.5)
                        # Re-check halt right after wake so a Stop
                        # click while parked doesn't get swallowed.
                        if halt is not None and halt.is_set():
                            break
                    if queue:
                        perception_event = queue.popleft()
            # If the queue / condition aren't wired (legacy boot or
            # benchmark fixture that drives the cognates manually), we
            # fall through with perception_event = None so the
            # downstream code can synthesize a no-op observation. The
            # benchmark harness writes pending_tool_output explicitly,
            # so that path stays valid.

        # 3. If we woke for halt with nothing in hand, signal halt to
        # the caller via the delta so run_cycle breaks cleanly.
        halt_now = False
        halt = getattr(self.core, "halt_event", None)
        if perception_event is None and halt is not None and halt.is_set():
            halt_now = True

        # 4. For a user_input event, surface its text as the perception
        # string. tool_output text is already populated above.
        if perception_event is not None and observation_kind == "user_input":
            observation_kind = perception_event.get("kind", "user_input")
            if observation_kind == "user_input":
                perception_text = str(perception_event.get("text", "") or "")
            elif not perception_text:
                # Defensive: a producer queued a tool_output via
                # submit_perception. Treat it like the slot path.
                tr = perception_event.get("tool_result", perception_event.get("text", ""))
                if isinstance(tr, (dict, list)):
                    try:
                        perception_text = json.dumps(tr, default=str)
                    except Exception:
                        perception_text = str(tr)
                else:
                    perception_text = str(tr or "")

        # 5. Now run the existing env_audit + signature + embedding
        # work. REASON still wants these every cycle so drift detection
        # and the bandit's NN query stay accurate.
        env_snapshot = self._snapshot_environment()

        # Stable signature: the hash depends only on snapshot contents, not
        # on dict iteration order. sorted() pins this regardless of Python
        # version. 16 chars (64 bits) -- collisions across the modest
        # observation surface are vanishingly rare even with a 5-tuple.
        payload = "|".join(
            f"{k}={tuple(v) if isinstance(v, (list, tuple)) else v}"
            for k, v in sorted(env_snapshot.items())
        )
        signature = hashlib.sha1(payload.encode()).hexdigest()[:16]

        # Phase D (UPGRADE_PLAN_3 sec 6.4) -- compute the observation
        # embedding once per cycle and stash it in the delta. Downstream
        # consumers (lx_Reason._exploit for semantic NN, lx_Integrate for
        # the commit) pull from state["observation_embedding"] rather than
        # re-embedding, which halves per-cycle embed latency and guarantees
        # commit-vs-query consistency. We embed the `payload` string (the
        # rich pre-hash form) because the 16-char signature hash carries
        # no semantic structure -- two close observations hash to far-apart
        # strings and cosine NN would be useless.
        embedding = None
        ollama = getattr(self.core, "ollama", None)
        if ollama is not None:
            try:
                embedding = ollama.embed(payload)
            except Exception:
                embedding = None

        # Trace text changes shape based on what we observed. Keeping
        # the env=...keys sig=... suffix preserves the Phase E debug
        # convention so existing log readers still parse cleanly.
        if halt_now:
            trace = f"OBSERVE: halt; env={len(env_snapshot)}keys sig={signature[:8]}"
        elif perception_event is None:
            trace = f"OBSERVE: idle; env={len(env_snapshot)}keys sig={signature[:8]}"
        else:
            kind_short = observation_kind[:4]
            trace = (
                f"OBSERVE: {kind_short}+env={len(env_snapshot)}keys "
                f"sig={signature[:8]}"
            )

        # Phase G Context Restoration -- query lx_memory.db for tasks and memory, and turns
        active_tasks = []
        working_memory = ""
        recent_turns = []
        store = getattr(self.core, "_active_store", None)
        if store is not None:
            if hasattr(store, "query_turns"):
                # limit=15 to match the old default conversation_history
                recent_turns = store.query_turns(limit=15)
                recent_turns.reverse()  # Chronological order
            state_dir = getattr(store, "_state_dir", None)
            if state_dir is not None:
                import sqlite3
                try:
                    db_path = str((Path(str(state_dir)) / "_lx" / "lx_memory.db").resolve())
                    if Path(db_path).exists():
                        conn = sqlite3.connect(db_path, check_same_thread=False)
                        try:
                            try:
                                cur = conn.execute("SELECT id, description, status FROM tasks ORDER BY id ASC")
                                for row in cur.fetchall():
                                    active_tasks.append({"id": row[0], "description": row[1], "status": row[2]})
                            except sqlite3.Error:
                                pass
                            try:
                                cur = conn.execute("SELECT value FROM state WHERE key = 'working_memory'")
                                row = cur.fetchone()
                                if row:
                                    working_memory = row[0]
                            except sqlite3.Error:
                                pass
                        finally:
                            conn.close()
                except Exception:
                    pass

        delta = {
            "current_step": "REASON",
            "observation_signature": signature,
            "observation_embedding": embedding,
            "env_audit": env_snapshot,
            "perception_text": perception_text,
            "observation_kind": observation_kind,
            "perception_event": perception_event,
            "active_tasks": active_tasks,
            "working_memory": working_memory,
            "recent_turns": recent_turns,
            # Always clear the cross-cycle slot. ACT writes it on the
            # NEXT cycle if its dispatch lands; we never want a stale
            # tool_output to ride more than one OBSERVE.
            "pending_tool_output": None,
            "last_trace": trace,
        }
        if halt_now:
            delta["halt"] = True
        return delta

    def _snapshot_environment(self) -> dict:
        """Per-root 5-tuple: (file_count, total_symbols, classes, functions, imports).

        total_symbols = classes + functions (semantically meaningful surface).
        File-level AST parse is cached on (mtime_ns, size) so stable files
        cost ~0; the whole walk typically settles into tens of ms after the
        first cycle.

        Sentinel: if a root is unreadable, the tuple is (-1,-1,-1,-1,-1) --
        stable across cycles so a broken file doesn't register as drift.
        """
        root = Path(__file__).parent.parent.resolve()
        snapshot = {}
        # Phase E (UPGRADE_PLAN_4 sec 4): observe_roots is configurable via
        # ConfigRegistry. Legacy boot (no config on self.core) keeps the
        # Phase D literal tuple -- identical behavior, no regression risk.
        _cfg = getattr(self.core, "config", None)
        roots = tuple(_cfg.get("observe_roots")) if _cfg is not None else self._OBSERVE_ROOTS
        for name in roots:
            sub = root / name
            if not sub.exists():
                snapshot[name] = (0, 0, 0, 0, 0)
                continue
            try:
                agg = [0, 0, 0, 0, 0]  # files, symbols, classes, funcs, imports
                for py in sub.rglob("*.py"):
                    agg[0] += 1
                    c, f, i = self._file_symbols(py)
                    agg[2] += c
                    agg[3] += f
                    agg[4] += i
                agg[1] = agg[2] + agg[3]
                snapshot[name] = tuple(agg)
            except OSError:
                snapshot[name] = self._PARSE_SENTINEL
        return snapshot

    def _file_symbols(self, path: Path) -> tuple:
        """Return (classes, functions, imports) for a single .py file.

        Cached on (mtime_ns, size) -- any edit that changes either field
        invalidates. SyntaxError / OSError are swallowed into a sentinel
        tuple so one broken file can't open the circuit for the rest.
        """
        key = str(path)
        try:
            st = path.stat()
            fingerprint = (st.st_mtime_ns, st.st_size)
        except OSError:
            return (-1, -1, -1)

        cached = self._ast_cache.get(key)
        if cached and cached[0] == fingerprint:
            return cached[1]

        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=key)
        except (SyntaxError, OSError, ValueError):
            # ValueError catches null-bytes-in-source -- rare but real.
            result = (-1, -1, -1)
            self._ast_cache[key] = (fingerprint, result)
            return result

        classes = 0
        functions = 0
        imports = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imports += 1

        result = (classes, functions, imports)
        self._ast_cache[key] = (fingerprint, result)
        return result


# --- lx_Reason -------------------------------------------------

class lx_Reason(Cognate):
    """Planning node -- e-greedy tool selection (UPGRADE_PLAN_2 sec 7 steps 3, 7).

    Reads last cycle's ToolOutcome.stderr (if any) as a plan-adjustment
    signal, then chooses to explore (random primitive) or exploit
    (highest-R primitive for this observation signature) based on
    epsilon(t) = eps_0 * exp(-lambda * |procedural_wins|).
    """

    def execute(self, state: dict) -> dict:
        # Phase F (UPGRADE_PLAN_5 sec 4) -- REASON is now LLM-driven.
        # The bandit math from Phase C/D/E survives as a *hint feeder*:
        # _top_k_hints ranks the procedural_wins history the same way
        # _exploit did, but instead of picking one tool, returns the top
        # three names and drops them into the system prompt so the LLM
        # can use them as a suggestion list. The LLM is the actual
        # decision maker -- it may pick one of the hints, pick a
        # primitive that wasn't ranked (exploration moves to the model,
        # not a coin flip on epsilon), or emit prose only with no tool
        # call at all (the implicit-loop-control bit Kevin specified
        # D-20260425).
        #
        # ACT then sees `planned_tool` -> dispatch, or planned_tool=None
        # -> ToolOutcome.skip (Phase F section 6, "ACT shrinks").
        #
        # Fallback path: if no ollama client is reachable on self.core
        # (a Cognate built outside ServoCore, a benchmark run that
        # didn't wire StubOllama, etc.), we degrade to the Phase E
        # bandit pick so the loop still advances. The legacy explore/
        # exploit branch remains live behind that fallback.
        store = getattr(self.core, "_active_store", None)
        obs_sig = state.get("observation_signature", "default")
        obs_emb = state.get("observation_embedding")  # Phase D (sec 6.4)

        # 1. Last-cycle outcome feedback.
        last_outcome = state.get("last_outcome") or {}
        stderr_flag = bool(last_outcome.get("stderr"))
        last_tool = last_outcome.get("tool_name")

        # 2. Epsilon computation. Retained for telemetry and for the
        # Phase E bandit-pick fallback below; not consumed by the LLM
        # path itself, but the value is logged so a regression in the
        # decay curve is still observable.
        wins_count = store.count_success_vectors() if store else 0
        _cfg = getattr(self.core, "config", None)
        eps_0 = _cfg.get("epsilon_0") if _cfg is not None else _EPSILON_0
        lam = _cfg.get("lambda_decay") if _cfg is not None else _LAMBDA
        epsilon = eps_0 * math.exp(-lam * wins_count)

        # 3. Bandit top-k hint -- always computed so it can be fed
        # to either the LLM prompt or the fallback picker.
        top_k = self._top_k_hints(
            store, obs_sig, obs_emb, stderr_flag, last_tool, state, k=3,
        )

        # 4. LLM call. When ollama is reachable we ask the model to
        # pick a tool (or emit prose only); otherwise fall back to the
        # bandit's top-1.
        ollama = getattr(self.core, "ollama", None)
        if ollama is not None:
            system_prompt = self._build_system_prompt(top_k, state)
            user_message = self._build_user_message(state, last_outcome)
            try:
                response_text, _truncated = ollama.chat(
                    system_prompt, [{"role": "user", "content": user_message}],
                    timeout=60,
                )
            except Exception as e:
                response_text = ""
                llm_error = f"ollama.chat failed: {e}"
            else:
                llm_error = None
                
            # Phase F (UPGRADE_PLAN_5 sec 6) -- emit telemetry
            hook = getattr(self.core, "telemetry_hook", None)
            if callable(hook):
                try:
                    hook(ollama.total_tokens_used, ollama.num_ctx)
                except Exception:
                    pass

            parsed = parse_tool_call(response_text) if response_text else None
            prose = strip_tool_calls(response_text) if response_text else ""

            if parsed:
                tool_name = parsed.get("tool")
                args = parsed.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
                # Backfill safe defaults for an LLM that emitted a tool
                # name without an args block. Without this, ACT would
                # dispatch with {} and most primitives error on missing
                # required args.
                if not args:
                    args = self._default_args_for(tool_name) or {}
                decision_mode = "llm_tool"
                plan_text = f"dispatch {tool_name} (mode=llm_tool)"
            elif response_text:
                tool_name = None
                args = {}
                decision_mode = "llm_prose"
                plan_text = "no tool call (LLM emitted prose only)"
            else:
                # Empty or errored response -- surface the bandit pick
                # so the loop still advances. This is the same shape
                # as the no-ollama branch below.
                tool_name, args = self._fallback_pick(
                    store, obs_sig, obs_emb, stderr_flag, last_tool, state,
                )
                decision_mode = "llm_empty_fallback"
                plan_text = (
                    f"dispatch {tool_name} (mode=llm_empty_fallback"
                    + (f", err={llm_error}" if llm_error else "") + ")"
                )
                prose = ""

            return {
                "current_step": "ACT",
                "plan": plan_text,
                "planned_tool": tool_name,
                "planned_args": args,
                "decision_mode": decision_mode,
                "epsilon": round(epsilon, 4),
                "bandit_top_k": list(top_k),
                "response_text": prose,
                "reason_text": response_text,
                "last_trace": f"REASON: {plan_text}",
            }

        # 5. No-ollama fallback -- preserve the Phase E bandit behaviour
        # so a Cognate spun up outside ServoCore (or a benchmark that
        # didn't wire a StubOllama) still advances. The explore branch
        # is retained for parity with the legacy decision_mode field.
        explore = random.random() < epsilon
        if explore:
            tool_name, args = self._explore()
            decision_mode = "explore"
        else:
            tool_name, args = self._exploit(
                store, obs_sig, obs_emb, stderr_flag, last_tool, state,
            )
            decision_mode = "exploit"

        plan_text = f"dispatch {tool_name} (mode={decision_mode}, eps={epsilon:.3f})"
        return {
            "current_step": "ACT",
            "plan": plan_text,
            "planned_tool": tool_name,
            "planned_args": args,
            "decision_mode": decision_mode,
            "epsilon": round(epsilon, 4),
            "bandit_top_k": list(top_k),
            "response_text": "",
            "reason_text": "",
            "last_trace": f"REASON: {plan_text}",
        }

    # -- Phase F prompt builders --

    def _build_system_prompt(self, top_k: list, state: dict) -> str:
        """Construct the system prompt for the LLM-driven REASON call.

        Surfaces:
          - The atomic primitive surface (the eleven tools the dispatch
            registry will actually run).
          - The bandit top-k as a non-binding hint -- "these have done
            well on similar observations recently."
          - The fenced-JSON tool-call schema so parse_tool_call can
            extract a call from the response.
          - Permission to emit prose only when no action is needed.

        The top_k list is ordered most-to-least promising. An empty
        list means the bandit had no usable history; the prompt still
        lists the atomic surface so the LLM has a vocabulary to pick
        from.
        """
        primitives = ", ".join(ATOMIC_PRIMITIVES)
        if top_k:
            hint_lines = "\n".join(f"  - {t}" for t in top_k)
            hint_block = (
                "Based on recent successes for similar observations, "
                "these primitives have been most useful (in order):\n"
                f"{hint_lines}\n"
                "These are hints, not commands -- pick what the situation "
                "actually calls for."
            )
        else:
            hint_block = (
                "No prior procedural wins for this observation; you are "
                "free to pick any primitive."
            )
        active_tasks = state.get("active_tasks", [])
        tasks_block = ""
        if active_tasks:
            lines = []
            pending_seen = False
            for task in active_tasks:
                if task["status"] == "completed":
                    lines.append(f"  [x] #{task['id']}  {task['description']}")
                else:
                    marker = "▶" if not pending_seen else " "
                    pending_seen = True
                    lines.append(f"  {marker} [ ] #{task['id']}  {task['description']}")
            tasks_block = "\n[ACTIVE TASKS]\n" + "\n".join(lines) + "\n"

        working_memory = state.get("working_memory", "")
        memory_block = ""
        if working_memory:
            memory_block = f"\n[EPISODIC MEMORY]\n{working_memory}\n"

        return (
            "You are the REASON cognate of a Servo Core agent. Your job "
            "each cycle is to look at the current observation and decide "
            "whether to call a tool, respond with prose, or both.\n\n"
            f"Atomic primitive surface (these are the tools that will "
            f"actually dispatch): {primitives}.\n\n"
            f"{hint_block}\n"
            f"{tasks_block}"
            f"{memory_block}\n"
            "To call a tool, emit a fenced JSON block like:\n"
            "```json\n"
            '{\"tool\": \"<primitive>\", \"args\": {<arg>: <value>, ...}}\n'
            "```\n"
            "If you have nothing to do, emit prose only and no JSON "
            "block; the loop will park until new perception arrives. "
            "If you want to both speak to the user and call a tool, "
            "include both prose and the fenced JSON. Keep prose "
            "concise -- the lexicon gate rejects apologetic or filler "
            "phrasing."
        )

    def _build_user_message(self, state: dict, last_outcome: dict) -> str:
        """Render the perception payload as a user message.

        Phase F Step 5 (UPGRADE_PLAN_5 sec 6) -- OBSERVE now writes
        `perception_text` and `observation_kind` for every cycle, so
        the message structure is honest about what the model is
        seeing:
          - "user_input"  -> a [USER] block with the chat text.
          - "tool_output" -> a [TOOL_OUTPUT] block with the previous
                             tool's serialized result.
          - missing       -> [PERCEPTION] (empty -- first cycle).
        env_audit and observation_signature are appended on every
        cycle so REASON has a stable view of the world state. The
        `last_outcome` block is kept as a redundant cross-cycle tap
        for legacy assertions; it can be pruned in Phase G+ once
        REASON consistently reads tool_output from perception_text.
        """
        chunks = []
        
        # Phase G Context Restoration -- inject history
        recent_turns = state.get("recent_turns", [])
        if recent_turns:
            for turn in recent_turns:
                perc = turn.get("perception_text")
                if perc:
                    k = turn.get("observation_kind", "")
                    if k == "user_input":
                        chunks.append(f"[USER]\n{perc}")
                    elif k == "tool_output":
                        chunks.append(f"[TOOL_OUTPUT]\n{perc}")
                    else:
                        chunks.append(f"[PERCEPTION]\n{perc}")
                resp = turn.get("response_text")
                if resp:
                    chunks.append(f"[SERVO]\n{resp}")

        perception = state.get("perception_text")
        kind = state.get("observation_kind") or ""
        if perception:
            if kind == "user_input":
                chunks.append(f"[USER]\n{perception}")
            elif kind == "tool_output":
                chunks.append(f"[TOOL_OUTPUT]\n{perception}")
            else:
                chunks.append(f"[PERCEPTION]\n{perception}")
        env_audit = state.get("env_audit")
        if env_audit:
            chunks.append(f"[ENV_AUDIT]\n{env_audit}")
        sig = state.get("observation_signature")
        if sig:
            chunks.append(f"[OBSERVATION_SIGNATURE] {sig}")
        if last_outcome:
            tool = last_outcome.get("tool_name")
            status = last_outcome.get("status")
            summary = last_outcome.get("summary") or last_outcome.get("return_value")
            if tool:
                summary_block = f"[LAST_OUTCOME] tool={tool} status={status}"
                if summary:
                    summary_block += f"\n{summary}"
                chunks.append(summary_block)
        if not chunks:
            chunks.append("[PERCEPTION] (empty -- first cycle, nothing in state)")
        return "\n\n".join(chunks)

    def _top_k_hints(
        self,
        store,
        obs_sig: str,
        obs_emb: Optional[list],
        stderr_flag: bool,
        last_tool: Optional[str],
        state: dict,
        k: int = 3,
    ) -> list:
        """Return the top-k tool names ranked by procedural-win score.

        Same scoring as _exploit (reward * similarity, dedupe by tool,
        post-failure pivot drops the failing tool). Differs only in
        that we keep all entries instead of picking the max, then
        slice the top k. Empty list when the store has no usable
        history -- callers degrade gracefully.
        """
        if store is None:
            return []
        history = store.query_success_vectors(
            obs_sig, obs_embedding=obs_emb, limit=20,
        )
        best_by_tool: dict = {}
        for meta in history:
            t = meta.get("tool_name")
            r = float(meta.get("reward", 0.0) or 0.0)
            sim = meta.get("_similarity")
            score = r * (float(sim) if sim is not None else 1.0)
            if t and (t not in best_by_tool or score > best_by_tool[t]):
                best_by_tool[t] = score
        if stderr_flag and last_tool and last_tool in best_by_tool:
            best_by_tool.pop(last_tool, None)
        ranked = sorted(best_by_tool.items(), key=lambda kv: kv[1], reverse=True)
        return [t for t, _score in ranked[:k]]

    def _fallback_pick(
        self,
        store,
        obs_sig: str,
        obs_emb: Optional[list],
        stderr_flag: bool,
        last_tool: Optional[str],
        state: dict,
    ) -> tuple:
        """Bandit pick used when the LLM call returned nothing.

        Wraps _exploit so the empty-LLM branch advances the loop with
        the same logic the no-ollama fallback uses. Deliberately a thin
        wrapper rather than calling _exploit directly so future Phase G+
        work has a single seam if the empty-response policy diverges
        from the no-ollama policy.
        """
        return self._exploit(
            store, obs_sig, obs_emb, stderr_flag, last_tool, state,
        )

    # -- Internals --

    def _explore(self) -> tuple:
        """Uniform random over atomic primitives."""
        tool = random.choice(ATOMIC_PRIMITIVES)
        return tool, self._default_args_for(tool)

    def _exploit(
        self,
        store,
        obs_sig: str,
        obs_emb: Optional[list],
        stderr_flag: bool,
        last_tool: Optional[str],
        state: dict,
    ) -> tuple:
        """Exploit the highest-R tool for this observation signature.

        Phase D semantic path: when obs_emb is a real _EMBED_DIM vector,
        the store's semantic NN branch returns rows from neighbouring
        signatures (cosine similarity >= 0.7 floor) annotated with
        `_similarity`. The score for ranking is r * similarity so
        high-reward neighbours don't eclipse a perfectly-matching lower-
        reward local hit. On a miss (no obs_emb, Ollama down, fresh
        collection, etc.) the store falls back to exact-match on
        observation_signature and `_similarity` is absent; we score by
        raw reward and Phase C behaviour is preserved.

        Phase G (UPGRADE_PLAN_6 sec 3d) cold-start cascade. On a
        procedural_wins miss we no longer consult a hand-tuned signal
        table. Instead we query the new env_snapshots collection for
        the closest historical environment-audit fingerprint (cosine
        floor 0.6, looser than procedural_wins by design -- audit
        embeddings are coarser than prose embeddings). If any neighbor
        clears the floor, we rank tools by score = reward * similarity
        (same blend as procedural_wins) and exploit the winner. On a
        double-miss -- no procedural_wins history AND no env_snapshots
        neighbor -- we fall through to neutral epsilon-greedy
        exploration via _explore(). That's a strictly better policy
        than committing to a hand-coded default: it gives the bandit
        a chance to discover something the heuristic table never
        encoded, and it stops repeating a wrong default forever.

        Post-failure pivot is preserved across both branches so we
        never immediately repeat a tool whose last invocation produced
        stderr.
        """
        history = (
            store.query_success_vectors(obs_sig, obs_embedding=obs_emb, limit=20)
            if store else []
        )

        # Rank: score = reward * (similarity if present else 1.0). Dedupe
        # by tool, keeping the highest score seen. This blends Phase C's
        # pure-reward ranking with Phase D's NN neighbourhood, and
        # degrades to Phase C when _similarity is absent.
        best_by_tool: dict = {}
        for meta in history:
            t = meta.get("tool_name")
            r = float(meta.get("reward", 0.0) or 0.0)
            sim = meta.get("_similarity")
            score = r * (float(sim) if sim is not None else 1.0)
            if t and (t not in best_by_tool or score > best_by_tool[t]):
                best_by_tool[t] = score

        # Post-failure pivot: never immediately repeat the failed tool.
        if stderr_flag and last_tool and last_tool in best_by_tool:
            best_by_tool.pop(last_tool, None)

        if best_by_tool:
            tool = max(best_by_tool.items(), key=lambda kv: kv[1])[0]
            return tool, self._default_args_for(tool)

        # Phase G (UPGRADE_PLAN_6 sec 3d) -- procedural_wins miss.
        # Cascade to env_snapshots. The store hides the cosine kNN
        # behind query_env_snapshots; a degenerate query embedding
        # (None, wrong dim, or all-zero) returns []. Same per-tool
        # max-score aggregation as the procedural_wins branch keeps
        # the ranking semantics consistent.
        env_history = (
            store.query_env_snapshots(obs_embedding=obs_emb)
            if store and hasattr(store, "query_env_snapshots") else []
        )
        env_best: dict = {}
        for meta in env_history:
            t = meta.get("tool_name")
            r = float(meta.get("reward", 0.0) or 0.0)
            sim = meta.get("_similarity")
            score = r * (float(sim) if sim is not None else 1.0)
            if t and (t not in env_best or score > env_best[t]):
                env_best[t] = score

        # Same post-failure pivot guard. A tool that just produced
        # stderr should not be re-recommended even if env_snapshots
        # remembers it winning in some other environment.
        if stderr_flag and last_tool and last_tool in env_best:
            env_best.pop(last_tool, None)

        if env_best:
            tool = max(env_best.items(), key=lambda kv: kv[1])[0]
            return tool, self._default_args_for(tool)

        # Double-miss: no procedural_wins history and no env_snapshots
        # neighbor. Fall through to neutral epsilon-greedy exploration
        # rather than a hand-coded default. _explore picks a uniform-
        # random atomic primitive, which over many cycles will populate
        # both collections with real data the cascade can lean on next
        # time.
        return self._explore()

    def _default_args_for(self, tool: str) -> dict:
        """Safe, project-relative default args for each atomic primitive.

        Phase D expands the surface to 11 tools (UPGRADE_PLAN_3 sec 8 step 5).
        Every added default is read-only or idempotent so a bench run
        cannot inflict destructive side effects:

          - task(action="list")           -- reads the Cognate-owned ledger.
          - system_config(op="get", ...)  -- pure read, no writes.
          - context_dump(show_user=False, pause_loop=False) -- read-only.
          - memory_manager(action="append", content="probe")
              -- writes to lx_memory.db (shim-routed), never state.db.
          - memory_snapshot(label="lx_bench")
              -- writes a dated JSON file into workspace/<model>/. Safe:
                the file is namespaced, and the sandbox check in the tool
                guards against escaping the project root.

        These are verified against the live tool schemas as of the Phase D
        commit. Every tool's execute() signature accepts these shapes.
        """
        defaults = {
            # Phase C six.
            "file_read":   {"path": "codex/manifest.json", "max_lines": 30},
            "file_write":  {
                "path": "state/lx_bench_probe.txt",
                "content": "probe\n",
                "append": False,
            },
            "file_list":   {"path": ".", "recursive": False},
            "file_manage": {
                "operation": "delete",
                "path": "state/lx_bench_probe.txt",
            },
            "map_project": {"path": ".", "depth": 2},
            "summarizer":  {"content": "Sample text to summarize for probe."},
            # Phase D five -- all read-only or idempotent.
            "task":            {"action": "list"},
            "system_config":   {"operation": "get", "parameter": "model"},
            "context_dump":    {"show_user": False, "pause_loop": False},
            "memory_manager":  {"action": "append", "content": "lx_bench probe"},
            "memory_snapshot": {"label": "lx_bench"},
        }
        # dict() copy so callers mutating args don't corrupt the class-level
        # default dict.
        return dict(defaults.get(tool, {}))

    # Phase G (UPGRADE_PLAN_6 sec 3e) -- the `_observation_signal`
    # classifier (and its `_sum_total_symbols` / `_drift_percent`
    # helpers) have been deleted. They produced one of three string
    # signals -- `empty_project`, `drift_detected`, `directory_scan` --
    # which fed into the `_COLD_START_LOOKUP` table to pick a default
    # tool on a procedural_wins miss. That whole heuristic stack is
    # superseded by the env_snapshots ChromaDB collection: the cold-
    # start path in `_exploit` now asks "which historical environment
    # is closest to the current one?" via cosine kNN, rather than
    # bucketing into three hand-tuned categories. ServoCore still
    # writes `_prior_audit_snapshot` because lx_Integrate uses it for
    # diff-based logging; if no Phase H+ consumer materializes that
    # field can be retired in Phase H.


# Phase G sync touch -- D-20260427.

# --- lx_Act ----------------------------------------------------

class lx_Act(Cognate):
    """Execution circuit -- atomic-primitive dispatch (UPGRADE_PLAN_2 sec 7 step 2).

    Pulls the plan's chosen tool + args, dispatches through a constrained
    ToolRegistry, wraps the result in a ToolOutcome, and runs the lexicon
    gate (sec 7 step 8). A lexicon violation sets halt=True in the delta.
    """

    def __init__(self, core):
        super().__init__(core)
        self._registry = None  # Lazy so module import stays cheap.

    def execute(self, state: dict) -> dict:
        tool = state.get("planned_tool")
        args = state.get("planned_args") or {}

        # Guard 1: no plan -> skip, advance to INTEGRATE.
        if not tool:
            outcome = ToolOutcome.skip("<none>", "no plan from REASON")
            return self._wrap_delta(outcome, halt=False)

        # Guard 2: tool not in the Phase C dispatch surface -> skip.
        if tool in _FORBIDDEN_TOOLS or tool not in ATOMIC_PRIMITIVES:
            outcome = ToolOutcome.skip(
                tool, f"tool '{tool}' not in atomic dispatch surface"
            )
            return self._wrap_delta(outcome, halt=False)

        # Guard 3: registry unavailable -> skip (degraded but not broken).
        reg = self._get_registry()
        if reg is None:
            outcome = ToolOutcome.skip(tool, "tool registry unavailable")
            return self._wrap_delta(outcome, halt=False)

        # Phase F (UPGRADE_PLAN_5 sec 7) -- inject a ToolContext for the
        # five sys-tools that accept it. The context carries:
        #   - conn_factory     -> Cognate-owned lx_memory.db (Phase E
        #                         memory-routing surface, no longer
        #                         dependent on the shim's sqlite3
        #                         monkey-patch).
        #   - legacy_loop_ref  -> a LxLoopAdapter that satisfies the
        #                         `loop.state` / `loop.config` /
        #                         `loop.telemetry` reads system_config
        #                         and context_dump perform under
        #                         headless dispatch. This replaces the
        #                         shim's `_get_loop_ref` rewrite, which
        #                         is being retired in this step.
        #   - state, config, ollama -> direct handles for any future
        #                         tool that wants them without going
        #                         through the adapter.
        # `args` is a per-call dict, so mutation here doesn't pollute
        # the default-args dict on the class.
        if tool in _CONTEXT_TOOLS and "tool_context" not in args:
            ctx = self._build_tool_context()
            if ctx is not None:
                args = {**args, "tool_context": ctx}
                # Memory tools also accept a bare conn_factory kwarg
                # for Phase E back-compat. We keep injecting it so a
                # future cognate that bypasses tool_context (or a
                # standalone test that constructs args directly) still
                # gets DB routing for free. The tool resolution order
                # picks explicit conn_factory FIRST, then ctx.conn_factory.
                if tool in _MEMORY_TOOLS and "conn_factory" not in args:
                    if callable(ctx.conn_factory):
                        args = {**args, "conn_factory": ctx.conn_factory}

        # Dispatch with latency measurement.
        t0 = time.perf_counter()
        try:
            raw_output = reg.execute(tool, args)
        except Exception as e:
            # The registry already wraps exceptions into "Error in <tool>:"
            # strings, but a defensive except here covers import-time and
            # dispatch-layer bugs that never reach the tool's own error path.
            raw_output = f"Error in {tool}: {e}"
        latency_ms = (time.perf_counter() - t0) * 1000.0

        outcome = ToolOutcome.from_tool_output(tool, args, raw_output, latency_ms)

        # Lexicon gate -- hard-fails on prose noise per UPGRADE_PLAN_2 sec 7 step 8.
        # Scans the raw output (covers both stderr and return_value paths)
        # so a successful tool that returned apologetic text also trips.
        halt = bool(_LEXICON_RE.search(raw_output or ""))

        return self._wrap_delta(outcome, halt=halt)

    # -- Internals --

    def _wrap_delta(self, outcome: ToolOutcome, halt: bool) -> dict:
        delta = {
            "current_step": "INTEGRATE",
            "last_outcome": outcome.to_dict(),
            "last_trace": (
                f"ACT: {outcome.tool_name} -> {outcome.status} "
                f"({outcome.latency_ms:.1f}ms)"
            ),
        }
        # Phase F (UPGRADE_PLAN_5 sec 6) -- write pending_tool_output so
        # the NEXT OBSERVE turns this dispatch result into a perception
        # of kind="tool_output". Without this slot OBSERVE would see no
        # perception and park indefinitely on the user-input queue,
        # which would make the loop unable to read its own tool output
        # back. We skip the slot for skip-status outcomes coming from
        # the "no plan from REASON" guard -- there's nothing useful to
        # feed back. Halt-on-lexicon also skips, since run_cycle is
        # about to break anyway.
        skip_followup = (
            halt
            or (outcome.status == "skip" and outcome.tool_name in ("<none>", None, ""))
        )
        if not skip_followup:
            tool_result = outcome.to_dict()
            delta["pending_tool_output"] = {
                "kind": "tool_output",
                "tool_result": tool_result,
                "tool_name": outcome.tool_name,
                "status": outcome.status,
                "timestamp": time.time(),
            }
        if halt:
            delta["halt"] = True
            delta["halt_reason"] = "lexicon_violation"
        return delta

    def _build_conn_factory(self):
        """Build a zero-arg callable that returns a sqlite3 connection
        to the Cognate-owned lx_memory.db.

        Phase E (UPGRADE_PLAN_4 sec 4 step 3) replaces the Phase D shim
        path (sqlite3.connect monkey-patch redirecting calls on
        state/state.db to lx_memory.db) with explicit injection. The
        factory is handed to the four memory-owning tools as a
        `conn_factory` kwarg; they call it, use the connection, and
        close it.

        Phase F (UPGRADE_PLAN_5 sec 7) -- this helper is also called
        by `_build_tool_context` to seed the context's `conn_factory`
        field. Both call sites accept None as "use the legacy literal
        path"; the helper itself does not change shape.

        Returns None when no _active_store is attached -- defensive
        guard so a Cognate invoked outside run_cycle doesn't crash. A
        None factory causes the tools to fall through to their Phase D
        literal path, which is the same fallback the shim provided.
        """
        import sqlite3 as _sqlite3
        store = getattr(self.core, "_active_store", None)
        if store is None:
            return None
        state_dir = getattr(store, "_state_dir", None)
        if state_dir is None:
            return None
        try:
            cognate_dir = Path(str(state_dir)) / "_lx"
            cognate_dir.mkdir(parents=True, exist_ok=True)
            redirect_path = str((cognate_dir / "lx_memory.db").resolve())
        except Exception:
            return None

        def _factory(_path=redirect_path):
            return _sqlite3.connect(_path, check_same_thread=False)

        return _factory

    def _build_tool_context(self):
        """Build a per-dispatch ToolContext for sys-tools.

        Phase F (UPGRADE_PLAN_5 sec 7) replaced the lx_loop_shim
        install path that ServoCore.run_cycle previously triggered.
        The shim's job was to swap `_get_loop_ref` inside system_config
        and context_dump for an adapter-returning callable; with
        tool_context.legacy_loop_ref carrying the same adapter, the
        tools resolve the loop reference directly off the context and
        no monkey-patch is necessary.

        Phase G (UPGRADE_PLAN_6 sec 1, D-20260427-01) -- the adapter
        moved out of the deleted `core/lx_loop_shim.py` and now lives
        in `core/lx_legacy_adapter.py`. Same class, same surface.

        Returns None when there's no active store (Cognate dispatched
        outside run_cycle, e.g. a test that builds lx_Act with no
        store). A None context causes the dispatch path to leave args
        unchanged, and the tool falls through to its legacy path.
        """
        store = getattr(self.core, "_active_store", None)
        if store is None:
            return None
        try:
            from core.tool_context import ToolContext
            from core.lx_legacy_adapter import LxLoopAdapter
        except Exception:
            return None
        try:
            adapter = LxLoopAdapter(self.core, store, ollama_client=getattr(self.core, "ollama", None))
        except Exception:
            adapter = None
        return ToolContext(
            state=store,
            config=getattr(self.core, "config", None),
            telemetry=adapter,  # adapter exposes the counter attributes
            conn_factory=self._build_conn_factory(),
            ollama=getattr(self.core, "ollama", None),
            legacy_loop_ref=adapter,
        )

    def _get_registry(self):
        """Lazy-load a ToolRegistry rooted at the project's tools/ dir.

        Uses an absolute path so the registry loads correctly regardless
        of CWD -- tests chdir into the project root, but benchmarks run
        from the benchmark/ directory.
        """
        if self._registry is not None:
            return self._registry
        try:
            from core.tool_registry import ToolRegistry
            tools_dir = Path(__file__).parent.parent / "tools"
            self._registry = ToolRegistry(tools_dir=str(tools_dir))
            # Phase G (UPGRADE_PLAN_6 sec 1, D-20260427-01) -- the
            # `_lx_shim_handle.patch_registry(...)` post-load patch
            # was retired here when `core/lx_loop_shim.py` was
            # deleted. The shim's job was already split between (a)
            # the loop-ref adapter, which now flows to sys-tools via
            # `tool_context.legacy_loop_ref` (Phase F, D-20260426-01)
            # and (b) the sqlite3 proxy, retired in Phase E
            # (D-20260424-01) when the four memory tools learned the
            # `conn_factory` kwarg. Nothing on the registry surface
            # needs touching after a fresh load anymore.
            return self._registry
        except Exception:
            return None


# --- lx_Integrate ----------------------------------------------

class lx_Integrate(Cognate):
    """Memory processor -- reward synthesis + procedural_wins commit.

    Computes R = phi * (L * P) per UPGRADE_PLAN_2 sec 5 and commits to
    procedural_wins iff R >= 0.8 (gate lives in StateStore). Resets the
    cursor to OBSERVE to close the circuit.
    """

    def execute(self, state: dict) -> dict:
        outcome = state.get("last_outcome") or {}
        obs_sig = state.get("observation_signature", "default")

        reward = self._compute_reward(outcome)

        # Phase D (Step 7 refinement) -- reuse the observation embedding
        # computed by lx_Observe rather than embedding obs_sig here. The
        # signature is a 16-char hash with no semantic structure, so
        # embedding it would store zero-information vectors in chroma and
        # break NN search. lx_Observe embeds the rich pre-hash payload;
        # we pick that up via state["observation_embedding"].
        #
        # Falling back when the key is absent (e.g. in direct unit tests
        # that bypass lx_Observe) keeps the commit path functional: the
        # store substitutes a _EMBED_DIM zero vector and tags the row
        # embed_source="zero" so downstream NN queries filter it out.
        embedding = state.get("observation_embedding")

        store = getattr(self.core, "_active_store", None)
        committed = False
        env_committed = False
        if store and outcome.get("tool_name"):
            committed = store.commit_success_vector(
                observation_signature=obs_sig,
                tool_name=outcome["tool_name"],
                reward=reward,
                outcome_snapshot=outcome,
                embedding=embedding,
            )
            # Phase G (UPGRADE_PLAN_6 sec 3c) -- env_snapshots commit.
            # Mirror the procedural_wins commit on the env_snapshots
            # collection. The store-side commit_env_snapshot enforces
            # the same reward >= commit_threshold gate, so a low-reward
            # cycle still short-circuits inside the store. The env_audit
            # dict is the document; the same observation_embedding feeds
            # the vector. We guard with hasattr so an older store (e.g.
            # a test double from before Phase G) doesn't crash the loop.
            env_audit_for_commit = state.get("env_audit") or {}
            if env_audit_for_commit and hasattr(store, "commit_env_snapshot"):
                try:
                    env_committed = store.commit_env_snapshot(
                        env_audit=env_audit_for_commit,
                        embedding=embedding,
                        tool_name=outcome["tool_name"],
                        reward=reward,
                    )
                except Exception:
                    # Best-effort: a chromadb hiccup on the env_snapshots
                    # branch must not block procedural_wins persistence
                    # or the rest of INTEGRATE. The cognate loop keeps
                    # running; the next successful cycle will retry.
                    env_committed = False

        # Phase E (UPGRADE_PLAN_4 sec 7) -- cache the env_audit snapshot
        # that drove this cycle so the next OBSERVE -> REASON pass can
        # diff against it for drift detection. Only cache non-empty
        # snapshots; an empty audit dict (rare, but possible if every
        # root errored) would teach the next cycle's drift check that
        # "empty" is the prior, which is not useful.
        env_audit = state.get("env_audit") or {}
        if env_audit:
            try:
                self.core._prior_audit_snapshot = env_audit
            except Exception:
                # Defensive: a non-standard core (e.g. a test double)
                # that rejects setattr should not break the cycle.
                pass

        # Phase F (UPGRADE_PLAN_5 sec 6) -- surface REASON's prose to
        # the chat layer. lx_Reason writes `response_text` whenever the
        # LLM emitted prose alongside (or instead of) a tool call. The
        # GUI binds a hook on ServoCore that emits the response_ready
        # Qt signal. We fire only when prose is non-empty so the chat
        # log doesn't gain blank rows on tool-only cycles.
        response_text = state.get("response_text") or ""
        if response_text.strip():
            self._fire_response_ready(response_text)

        # Phase F (UPGRADE_PLAN_5 sec 6) -- persist a conversation turn
        # so the chat history survives across cycles + sessions. We
        # delegate to the active store if it exposes `record_turn`
        # (added by Phase F's StateStore extension); otherwise this is
        # a quiet best-effort no-op so older stores don't crash.
        self._persist_turn(state, outcome, response_text)

        return {
            "current_step": "OBSERVE",
            "last_reward": round(reward, 4),
            "last_committed": bool(committed),
            "last_env_committed": bool(env_committed),
            "integrated": True,
            "last_trace": (
                f"INTEGRATE: R={reward:.3f} "
                f"committed={committed} env_committed={env_committed}"
            ),
        }

    # -- Phase F surfaces (UPGRADE_PLAN_5 sec 6) -----------------------

    def _fire_response_ready(self, response_text: str) -> None:
        """Call the ServoCore response_ready hook if one is registered.

        The GUI sets `core.response_ready_hook = lambda text, image:
        self.response_ready.emit(text, image)`. Headless callers leave
        the attribute unset and we silently skip emission. The second
        positional is image_b64 mirroring CoreLoop.response_ready --
        always empty under Phase F since REASON doesn't emit images.
        Errors inside the hook are swallowed: the cognate loop must
        not be killed by a downstream Qt connection bug.
        """
        hook = getattr(self.core, "response_ready_hook", None)
        if not callable(hook):
            return
        try:
            hook(response_text, "")
        except Exception:
            pass

    def _persist_turn(self, state: dict, outcome: dict, response_text: str) -> None:
        """Best-effort persistence of one user-turn / model-turn pair.

        Phase F places the persistence seam on the active store. A store
        that doesn't expose `record_turn` is treated as legacy -- we
        skip silently. The recorded fields are intentionally minimal so
        the schema stays small:
          - perception_text  : the user input (or tool_output) we saw
          - observation_kind : "user_input" | "tool_output"
          - response_text    : REASON's prose, possibly empty
          - tool_name        : the dispatched tool, possibly empty
          - status           : the dispatch status (ok/skip/fail/None)
          - timestamp        : float seconds since epoch
        Phase G+ may extend this with reasoning trace, embedding, etc.
        """
        store = getattr(self.core, "_active_store", None)
        if store is None:
            return
        record_turn = getattr(store, "record_turn", None)
        if not callable(record_turn):
            return
        try:
            record_turn(
                perception_text=str(state.get("perception_text") or ""),
                observation_kind=str(state.get("observation_kind") or ""),
                response_text=str(response_text or ""),
                tool_name=str((outcome or {}).get("tool_name") or ""),
                status=str((outcome or {}).get("status") or ""),
                timestamp=time.time(),
            )
        except Exception:
            # Persistence is best-effort -- a schema mismatch on an
            # older store should not break the cognate loop. The
            # commit_success_vector path remains the source of truth
            # for procedural learning.
            pass


    # -- Reward computation --

    def _compute_reward(self, outcome: dict) -> float:
        """R = phi * (L * P)

        phi = 1.0 iff stderr+return_value are lexicon-clean (hard gate).
        L = 1 / (1 + latency_s).
        P = 1.0 (ok) / 0.3 (skip) / 0.0 (fail).

        The phi scan covers BOTH channels -- Gemini flagged in the handover
        that an "ok" tool can still emit prose noise, so we belt-and-
        suspenders the check rather than trusting status alone.
        """
        status = outcome.get("status")

        haystack = (
            str(outcome.get("stderr") or "")
            + "\n"
            + str(outcome.get("return_value") or "")
        )
        phi = 0.0 if _LEXICON_RE.search(haystack) else 1.0

        latency_s = float(outcome.get("latency_ms") or 0.0) / 1000.0
        L = 1.0 / (1.0 + latency_s)

        P = {"ok": 1.0, "skip": 0.3, "fail": 0.0}.get(status, 0.0)

        return phi * (L * P)
