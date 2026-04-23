# lx_cognates.py
#
# Phase C — real Cognate bodies. UPGRADE_PLAN_2 §7 steps 2-8.
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

import hashlib
import math
import random
import re
import time
from pathlib import Path
from typing import Optional

from core.lx_outcomes import ToolOutcome
from benchmark.criteria.lx_lexicon import FAIL_PATTERNS


# Atomic primitives the Phase C dispatch surface will actually run.
# Kept as a tuple so accidental mutation is a type error, not a silent drift.
ATOMIC_PRIMITIVES = (
    "file_read", "file_write", "file_list", "file_manage",
    "map_project", "summarizer",
)


# TOOL_IS_SYSTEM tools excluded from Phase C dispatch (D-20260422-05).
# 'summarizer' is NOT here despite being system-tagged because D-20260421-14
# promotes it to a first-class atomic primitive.
_FORBIDDEN_TOOLS = frozenset({
    "task", "system_config", "context_dump",
    "memory_manager", "memory_snapshot",
})


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


# ε-greedy hyperparameters (UPGRADE_PLAN_2 §6, first-pass literals).
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


# ─── lx_Observe ────────────────────────────────────────────

class lx_Observe(Cognate):
    """Sensor array — environment audit (UPGRADE_PLAN_2 §7 step 4).

    Ports the --chores structural-sweep pattern (D-20260422-06). Emits
    an observation_signature the downstream Cognates use as the key for
    procedural_wins lookups.
    """

    # Canonical root dirs covered by the --chores structural sweep.
    _OBSERVE_ROOTS = ("core", "gui", "tools", "codex")

    def execute(self, state: dict) -> dict:
        env_snapshot = self._snapshot_environment()

        # Stable signature: the hash depends only on snapshot contents, not
        # on dict iteration order. sorted() pins this regardless of Python
        # version. Keeping the truncation at 16 chars (64 bits) — collisions
        # across the modest observation surface are vanishingly rare.
        signature = hashlib.sha1(
            "|".join(f"{k}={v}" for k, v in sorted(env_snapshot.items())).encode()
        ).hexdigest()[:16]

        return {
            "current_step": "REASON",
            "observation_signature": signature,
            "env_audit": env_snapshot,
            "last_trace": f"OBSERVE: env={len(env_snapshot)}keys sig={signature[:8]}",
        }

    def _snapshot_environment(self) -> dict:
        """Count Python files per canonical root.

        Deterministic and cheap — the same project state yields the same
        signature across cycles, which is the property procedural_wins
        lookups need to hit a cache. Symbolic drift (new classes,
        new functions) is NOT captured here on purpose; that's a Phase D
        refinement once we have baseline data on reward volatility.
        """
        root = Path(__file__).parent.parent.resolve()
        snapshot = {}
        for name in self._OBSERVE_ROOTS:
            sub = root / name
            if not sub.exists():
                snapshot[name] = 0
                continue
            try:
                snapshot[name] = sum(1 for _ in sub.rglob("*.py"))
            except OSError:
                # Filesystem hiccup — record -1 as a sentinel rather than
                # opening the circuit. Signature will be unique for this
                # transient state, which is correct.
                snapshot[name] = -1
        return snapshot


# ─── lx_Reason ─────────────────────────────────────────────

class lx_Reason(Cognate):
    """Planning node — ε-greedy tool selection (UPGRADE_PLAN_2 §7 steps 3, 7).

    Reads last cycle's ToolOutcome.stderr (if any) as a plan-adjustment
    signal, then chooses to explore (random primitive) or exploit
    (highest-R primitive for this observation signature) based on
    ε(t) = ε₀ · exp(-λ · |procedural_wins|).
    """

    def execute(self, state: dict) -> dict:
        store = getattr(self.core, "_active_store", None)
        obs_sig = state.get("observation_signature", "default")

        # 1. Last-cycle outcome feedback.
        last_outcome = state.get("last_outcome") or {}
        stderr_flag = bool(last_outcome.get("stderr"))
        last_tool = last_outcome.get("tool_name")

        # 2. ε computation. Grows toward 0 as procedural_wins accumulates.
        wins_count = store.count_success_vectors() if store else 0
        epsilon = _EPSILON_0 * math.exp(-_LAMBDA * wins_count)
        explore = random.random() < epsilon

        # 3. Tool selection.
        if explore:
            tool_name, args = self._explore()
            decision_mode = "explore"
        else:
            tool_name, args = self._exploit(store, obs_sig, stderr_flag, last_tool)
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

    # ── Internals ──

    def _explore(self) -> tuple:
        """Uniform random over atomic primitives."""
        tool = random.choice(ATOMIC_PRIMITIVES)
        return tool, self._default_args_for(tool)

    def _exploit(
        self,
        store,
        obs_sig: str,
        stderr_flag: bool,
        last_tool: Optional[str],
    ) -> tuple:
        """Exploit the highest-R tool for this observation signature.

        Fall-through on miss: the static cold-start lookup from a semantic
        signal derived from observation (not the hash). If the previous
        cycle failed (stderr present), the failing tool is removed from
        the candidate pool so we don't loop on a bad choice.
        """
        history = store.query_success_vectors(obs_sig, limit=20) if store else []

        # Rank by reward, dedupe by tool keeping the best seen.
        best_by_tool = {}
        for meta in history:
            t = meta.get("tool_name")
            r = meta.get("reward", 0.0)
            if t and (t not in best_by_tool or r > best_by_tool[t]):
                best_by_tool[t] = r

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

        These are verified against the live tool schemas as of commit
        ad2e20c7. Every tool's execute() signature accepts these shapes.
        """
        defaults = {
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
            "summarizer":  {"text": "Sample text to summarize for probe."},
        }
        # dict() copy so callers mutating args don't corrupt the class-level
        # default dict.
        return dict(defaults.get(tool, {}))

    def _observation_signal(self) -> str:
        """Derive a semantic signal from the observation for cold-start lookup.

        First-pass: always request a directory_scan — cheapest probe, and
        fastest path to accumulating reward data that the exploit branch
        can then consume. A richer signal (reading env_audit drift) is a
        Phase D concern.
        """
        return "directory_scan"


# ─── lx_Act ────────────────────────────────────────────────

class lx_Act(Cognate):
    """Execution circuit — atomic-primitive dispatch (UPGRADE_PLAN_2 §7 step 2).

    Pulls the plan's chosen tool + args, dispatches through a constrained
    ToolRegistry, wraps the result in a ToolOutcome, and runs the lexicon
    gate (§7 step 8). A lexicon violation sets halt=True in the delta.
    """

    def __init__(self, core):
        super().__init__(core)
        self._registry = None  # Lazy so module import stays cheap.

    def execute(self, state: dict) -> dict:
        tool = state.get("planned_tool")
        args = state.get("planned_args") or {}

        # Guard 1: no plan → skip, advance to INTEGRATE.
        if not tool:
            outcome = ToolOutcome.skip("<none>", "no plan from REASON")
            return self._wrap_delta(outcome, halt=False)

        # Guard 2: tool not in the Phase C dispatch surface → skip.
        if tool in _FORBIDDEN_TOOLS or tool not in ATOMIC_PRIMITIVES:
            outcome = ToolOutcome.skip(
                tool, f"tool '{tool}' not in atomic dispatch surface"
            )
            return self._wrap_delta(outcome, halt=False)

        # Guard 3: registry unavailable → skip (degraded but not broken).
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

        # Lexicon gate — hard-fails on prose noise per UPGRADE_PLAN_2 §7 step 8.
        # Scans the raw output (covers both stderr and return_value paths)
        # so a successful tool that returned apologetic text also trips.
        halt = bool(_LEXICON_RE.search(raw_output or ""))

        return self._wrap_delta(outcome, halt=halt)

    # ── Internals ──

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
        of CWD — tests chdir into the project root, but benchmarks run
        from the benchmark/ directory.
        """
        if self._registry is not None:
            return self._registry
        try:
            from core.tool_registry import ToolRegistry
            tools_dir = Path(__file__).parent.parent / "tools"
            self._registry = ToolRegistry(tools_dir=str(tools_dir))
            return self._registry
        except Exception:
            return None


# ─── lx_Integrate ──────────────────────────────────────────

class lx_Integrate(Cognate):
    """Memory processor — reward synthesis + procedural_wins commit.

    Computes R = Φ · (L · P) per UPGRADE_PLAN_2 §5 and commits to
    procedural_wins iff R >= 0.8 (gate lives in StateStore). Resets the
    cursor to OBSERVE to close the circuit.
    """

    def execute(self, state: dict) -> dict:
        outcome = state.get("last_outcome") or {}
        obs_sig = state.get("observation_signature", "default")

        reward = self._compute_reward(outcome)

        store = getattr(self.core, "_active_store", None)
        committed = False
        if store and outcome.get("tool_name"):
            committed = store.commit_success_vector(
                observation_signature=obs_sig,
                tool_name=outcome["tool_name"],
                reward=reward,
                outcome_snapshot=outcome,
            )

        return {
            "current_step": "OBSERVE",
            "last_reward": round(reward, 4),
            "last_committed": bool(committed),
            "integrated": True,
            "last_trace": f"INTEGRATE: R={reward:.3f} committed={committed}",
        }

    # ── Reward computation ──

    def _compute_reward(self, outcome: dict) -> float:
        """R = Φ · (L · P)

        Φ = 1.0 iff stderr+return_value are lexicon-clean (hard gate).
        L = 1 / (1 + latency_s).
        P = 1.0 (ok) / 0.3 (skip) / 0.0 (fail).

        The Φ scan covers BOTH channels — Gemini flagged in the handover
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
