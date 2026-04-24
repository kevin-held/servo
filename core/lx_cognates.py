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
import math
import random
import re
import time
from pathlib import Path
from typing import Optional

from core.lx_outcomes import ToolOutcome
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


# Static cold-start lookup for lx_Reason. Used when procedural_wins has no
# history for the current observation signature. The keys are semantic
# signals derived from env_audit, not raw signature hashes, so the lookup
# does useful work across different observation hashes.
_COLD_START_LOOKUP = {
    "project_map_needed": ("map_project", {"path": ".", "depth": 2}),
    "directory_scan":     ("file_list",   {"path": ".", "recursive": False}),
    "manifest_read":      ("file_read",   {"path": "codex/manifest.json"}),
    "default":            ("file_list",   {"path": ".", "recursive": False}),
}


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

        return {
            "current_step": "REASON",
            "observation_signature": signature,
            "observation_embedding": embedding,
            "env_audit": env_snapshot,
            "last_trace": f"OBSERVE: env={len(env_snapshot)}keys sig={signature[:8]}",
        }

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
        for name in self._OBSERVE_ROOTS:
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
        store = getattr(self.core, "_active_store", None)
        obs_sig = state.get("observation_signature", "default")
        obs_emb = state.get("observation_embedding")  # Phase D (sec 6.4)

        # 1. Last-cycle outcome feedback.
        last_outcome = state.get("last_outcome") or {}
        stderr_flag = bool(last_outcome.get("stderr"))
        last_tool = last_outcome.get("tool_name")

        # 2. epsilon computation. Grows toward 0 as procedural_wins accumulates.
        wins_count = store.count_success_vectors() if store else 0
        epsilon = _EPSILON_0 * math.exp(-_LAMBDA * wins_count)
        explore = random.random() < epsilon

        # 3. Tool selection.
        if explore:
            tool_name, args = self._explore()
            decision_mode = "explore"
        else:
            tool_name, args = self._exploit(
                store, obs_sig, obs_emb, stderr_flag, last_tool
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
            "last_trace": f"REASON: {plan_text}",
        }

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

        Fall-through on empty history: the static cold-start lookup
        from a semantic signal derived from observation (not the hash).
        If the previous cycle failed (stderr present), the failing tool
        is removed from the candidate pool so we don't loop on a bad
        choice.
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

        # Cold start.
        signal = self._observation_signal()
        tool, args = _COLD_START_LOOKUP.get(signal, _COLD_START_LOOKUP["default"])
        return tool, args

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

    def _observation_signal(self) -> str:
        """Derive a semantic signal from the observation for cold-start lookup.

        First-pass: always request a directory_scan -- cheapest probe, and
        fastest path to accumulating reward data that the exploit branch
        can then consume. A richer signal (reading env_audit drift) is a
        Phase D concern.
        """
        return "directory_scan"


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
        if halt:
            delta["halt"] = True
            delta["halt_reason"] = "lexicon_violation"
        return delta

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
            # Phase D -- if a lx_loop_shim handle is active on the core,
            # patch this freshly-loaded registry's tool modules so the
            # sqlite3 proxy + _get_loop_ref adapter are installed on the
            # registry-owned module instances (which are NOT in sys.modules
            # because tool_registry uses spec_from_file_location).
            shim_handle = getattr(self.core, "_lx_shim_handle", None)
            if shim_handle is not None:
                try:
                    shim_handle.patch_registry(self._registry)
                except Exception:
                    # Patch failure is non-fatal; the registry still
                    # dispatches, the shim just doesn't intercept its
                    # modules on this run.
                    pass
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
        if store and outcome.get("tool_name"):
            committed = store.commit_success_vector(
                observation_signature=obs_sig,
                tool_name=outcome["tool_name"],
                reward=reward,
                outcome_snapshot=outcome,
                embedding=embedding,
            )

        return {
            "current_step": "OBSERVE",
            "last_reward": round(reward, 4),
            "last_committed": bool(committed),
            "integrated": True,
            "last_trace": f"INTEGRATE: R={reward:.3f} committed={committed}",
        }

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
ctional: the
        # store substitutes a _EMBED_DIM zero vector and tags the row
        # embed_source="zero" so downstream NN queries filter it out.
        embedding = state.get("observation_embedding")

        store = getattr(self.core, "_active_store", None)
        committed = False
        if store and outcome.get("tool_name"):
            committed = store.commit_success_vector(
                observation_signature=obs_sig,
                tool_name=outcome["tool_name"],
                reward=reward,
                outcome_snapshot=outcome,
                embedding=embedding,
            )

        return {
            "current_step": "OBSERVE",
            "last_reward": round(reward, 4),
            "last_committed": bool(committed),
            "integrated": True,
            "last_trace": f"INTEGRATE: R={reward:.3f} committed={committed}",
        }

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
