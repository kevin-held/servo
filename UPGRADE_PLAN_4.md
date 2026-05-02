# UPGRADE_PLAN_4.md
**Phase:** E — ConfigRegistry Migration + Tool Context-Injection + GUI Rewire + Cold-Start Enrichment
**Status:** DRAFT — PENDING APPROVAL | **Priority:** HIGH
**Author:** Servo (Claude, in cooperation with Kevin)
**Date:** D-20260424
**Supersedes Scope-Of:** `UPGRADE_PLAN_3.md` (closed, Phase D landed as v1.5.0)
**Synced Commit:** post-D-20260423-02 (Phase D ADR accepted)

---

## 1. Objective

Phase D widened the dispatch surface, added real 768-dim embeddings, and wired semantic NN into the exploit branch. The circuit is closed and sharper, but the scaffolding holding it up carries four debts Phase C and D deliberately deferred:

1. **(a) Configuration debt** — six hardcoded tunables (`_EPSILON_0`, `_LAMBDA`, `_EMBED_DIM`, `_COMMIT_THRESHOLD`, `similarity_floor`, `embed_model`) live as module literals across `lx_cognates.py`, `lx_state.py`, and `ollama_client.py`. A live-tune loop cannot touch them without editing source.
2. **(b) Monkey-patch debt** — `core/lx_loop_shim.py` reroutes `memory_manager` and `memory_snapshot` via `sqlite3.connect` interception. The shim is reversible and well-contained, but it's a smell. Phase D's own plan (UPGRADE_PLAN_3 §10 Q4) flagged it: "Phase E may refactor memory_manager to accept a `conn_factory` kwarg for testability."
3. **(c) GUI-imports-loop debt** — `gui/main_window.py` constructs `CoreLoop`, `gui/loop_panel.py` imports `core.loop.LoopStep`. Neither sees `ServoCore` or the Cognates. A user running the GUI is still running the legacy circuit.
4. **(d) Cold-start signal debt** — `lx_Reason._observation_signal()` hardcodes `return "directly_scan"`. The env_audit payload already in `state["env_audit"]` carries symbol/class/function counts per root; we just don't read them for signal derivation.

Phase E is **plumbing, not cognition**. The Cognate contract stays frozen. The reward formula stays frozen. `procedural_wins` schema stays frozen. `loop.py` stays untouched at the source level (constraint confirmed during plan drafting).

---

## 2. Scope

**In-Scope:**
- **ConfigRegistry** — a new `core/config_registry.py` module exposing a single `ConfigRegistry` class backed by `codex/manifests/config.json`. Seven tunables migrate on first pass:
  - `epsilon_0` (was `_EPSILON_0 = 0.3`)
  - `lambda_decay` (was `_LAMBDA = 0.001`)
  - `embed_dim` (was `_EMBED_DIM = 768`)
  - `commit_threshold` (was `_COMMIT_THRESHOLD = 0.8`)
  - `nn_similarity_floor` (was `similarity_floor = 0.7`)
  - `embed_model` (was `"nomic-embed-text"` in `OllamaClient.__init__`)
  - `observe_roots` (was `("core", "gui", "tools", "codex")` in `lx_Observe._OBSERVE_ROOTS`)
- **Tool context-injection** — `tools/memory_manager.py` and `tools/memory_snapshot.py` gain an optional `conn_factory: Callable[[], sqlite3.Connection]` kwarg. When present, it overrides the hardcoded `sqlite3.connect(db_path, check_same_thread=False)` call. Default remains the legacy path.
- **Loop-ref shim retirement** — with `conn_factory` in place, `core/lx_loop_shim.py`'s `sqlite3.connect` interception for the memory tools becomes dead code. The shim's `LxLoopAdapter` (the `loop.state/config/telemetry` facade for `system_config`, `context_dump`) stays. Only the memory-routing branch retires.
- **GUI rewire** — `gui/main_window.py` constructs `ServoCore` instead of (or alongside, per §4.3) `CoreLoop`. `gui/loop_panel.py` replaces `core.loop.LoopStep` with a Cognate-sourced step enum. `gui/tool_panel.py` yellow-highlight semantics stay (TOOL_IS_SYSTEM is still a display flag, per Phase D §3) but the panel reads the dispatch surface from `ServoCore._ATOMIC_PRIMITIVES` rather than the legacy registry.
- **Cold-start signal enrichment** — `lx_Reason._observation_signal()` reads `state["env_audit"]` and returns one of three signals driven by the symbolic topology:
  - `"empty_project"` when `total_symbols ≤ 5` across all roots
  - `"drift_detected"` when current 5-tuple differs from the most recent cached observation by ≥10% in `total_symbols`
  - `"directory_scan"` (the default, preserving Phase D behavior)
- **Config reload hook** — `ConfigRegistry.reload()` re-reads `config.json`. Called once at `ServoCore.__init__`; Phase F wires a live-tune hot-reload path.

**Stub-Only / Deferred to Phase F+:**
- Hot-reload on `config.json` mtime change — Phase E ships cold-reload only; live-tune is Phase F.
- Migration of `core/loop.py`'s own hardcoded literals — loop.py stays No-Write.
- `gui/log_panel.py` Qt-signal rewire (`CoreLoop.log_event` → Cognate log channel) — Phase F.
- Retirement of `core/loop.py` itself — Phase G or later, with its own deprecation ADR.
- Curiosity bonus (deferred from Phase D §2).
- Telemetry-driven tuning of `nn_similarity_floor` — Phase F (requires the hot-reload path).

---

## 3. Constraints Inherited from Prior Decisions

- **No-Write on `core/loop.py`** (confirmed for Phase E by explicit user choice during plan drafting) — remains active. `loop.py` boots with its original signature. Any GUI migration routes through `ServoCore` + adapters, never through editing `loop.py`.
- **Reference preservation of `loop.py`** (Phase C) — unchanged. Import chain from `loop.py` stays walkable.
- **Atomic-primitive contract** (D-20260421-14, extended D-20260423-02) — unchanged. The eleven Phase D primitives keep their `execute` signature and `ToolOutcome` wrapper.
- **No-Write on legacy SQLite `state/state.db`** (Phase C, refined Phase D) — unchanged. The acceptance gate re-runs the sha256-identical check (Phase D Step 8 pattern) to confirm conn_factory routing preserves zero-writes.
- **Lexicon compliance gate** (Phase C) — unchanged.
- **Polymorphic contract `OBSERVE → REASON → ACT → INTEGRATE`** — frozen. Cold-start enrichment reads a different input in `_observation_signal` but preserves the method's return contract (string key into `_COLD_START_LOOKUP`).
- **`lx_StateStore` public API** — frozen through Phase E except for `__init__` gaining `config: ConfigRegistry | None = None` as a keyword argument (backward-compatible; existing callers pass nothing).
- **ConfigRegistry is cold-reload only on first pass** — literals migrate, but live-tune is Phase F. A `ConfigRegistry` miss falls back to the same literal the code currently hardcodes, so `config.json` absent is not a regression.

---

## 4. ConfigRegistry (Architecture)

### 4.1 Module

```python
# core/config_registry.py (new)
from pathlib import Path
import json

class ConfigRegistry:
    """Cold-reload tunables store. Reads codex/manifests/config.json once
    at instantiation. Phase F adds mtime-driven hot reload; Phase E is
    cold-reload-only.

    Missing keys fall back to code-level defaults so a deleted config.json
    is never a regression -- it's equivalent to running Phase D literals.
    """

    _DEFAULTS = {
        "epsilon_0":           0.3,
        "lambda_decay":        0.001,
        "embed_dim":           768,
        "commit_threshold":    0.8,
        "nn_similarity_floor": 0.7,
        "embed_model":         "nomic-embed-text",
        "observe_roots":       ["core", "gui", "tools", "codex"],
    }

    def __init__(self, path: Path | None = None):
        self._path = path or Path("codex/manifests/config.json")
        self._values: dict = dict(self._DEFAULTS)
        self.reload()

    def reload(self) -> None:
        try:
            if self._path.exists():
                overlay = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(overlay, dict):
                    self._values.update(overlay)
        except Exception:
            # Never raise on bad config -- degrade to defaults.
            pass

    def get(self, key: str, default=None):
        return self._values.get(key, default if default is not None
                                else self._DEFAULTS.get(key))
```

### 4.2 Consumers

- `lx_cognates.py`: `_EPSILON_0` and `_LAMBDA` become `self.core.config.get("epsilon_0")` / `self.core.config.get("lambda_decay")` inside `lx_Reason._epsilon_t`. `lx_Observe._OBSERVE_ROOTS` becomes `tuple(self.core.config.get("observe_roots"))`.
- `lx_state.py`: `_EMBED_DIM` and `_COMMIT_THRESHOLD` become `self._config.get("embed_dim")` / `self._config.get("commit_threshold")`. `similarity_floor` default in `query_success_vectors` signature becomes `self._config.get("nn_similarity_floor")`.
- `core/ollama_client.py`: `embed_model` default in `__init__` becomes `config.get("embed_model")` when a registry is passed; literal `"nomic-embed-text"` fallback preserves backward-compat for direct `OllamaClient()` callers.
- `ServoCore.__init__` instantiates the registry once and passes it to each Cognate and to `lx_StateStore`.

### 4.3 `config.json` shape

Empty file (or missing) is valid — all defaults apply. Populated example:

```json
{
  "epsilon_0": 0.25,
  "nn_similarity_floor": 0.65,
  "embed_model": "mxbai-embed-large"
}
```

### 4.4 Migration safety

Every call site gains a `getattr(self.core, "config", None)` check, and when `config is None` (legacy boot, no ServoCore) the code path falls through to the Phase D literal. This means loop.py's imports don't break — they get the literal value they always had.

---

## 5. Tool Context-Injection (Architecture)

### 5.1 Current pattern (Phase D)

Three tool files open their own SQLite connection:

```python
# tools/memory_manager.py:20
conn = sqlite3.connect(db_path, check_same_thread=False)

# tools/memory_snapshot.py:43 and :62
conn = sqlite3.connect(str(db_path), check_same_thread=False)

# tools/context_dump.py:40
conn = sqlite3.connect(str(db_path), check_same_thread=False)

# tools/task.py:129
conn = sqlite3.connect(path, check_same_thread=False)
```

Under Phase D, the loop-ref shim intercepts these calls via `sqlite3.connect` patch to reroute `memory_manager` and `memory_snapshot` away from `state/state.db`.

### 5.2 Phase E refactor

Each memory tool gains an optional `conn_factory` kwarg:

```python
# tools/memory_manager.py (after refactor)
def execute(action, content=None, *, conn_factory=None, **kwargs):
    if conn_factory is not None:
        conn = conn_factory()
    else:
        conn = sqlite3.connect(db_path, check_same_thread=False)
    # ... rest unchanged ...
```

`tools/task.py` and `tools/context_dump.py` get the same treatment in Phase E for consistency, even though the shim doesn't currently reroute them — the goal is a uniform tool-context contract.

### 5.3 Shim simplification

`core/lx_loop_shim.py` currently does three things: (a) `sqlite3.connect` interception for memory tools, (b) `_get_loop_ref` monkey-patch for sys-tools, (c) `LxLoopAdapter` facade. Phase E retires (a). (b) and (c) stay — `system_config` and `context_dump` still reach for `loop.state` / `loop.config`, and rewiring those requires the same conn_factory pattern applied to a broader surface (Phase F).

`ServoCore.run_cycle` under Phase E passes `conn_factory=self._lx_conn_factory` to `memory_manager` and `memory_snapshot` dispatches. `_lx_conn_factory` returns a connection to the lx_state SQLite mirror (the same DB the Phase D shim was rerouting to). No state lives in `state/state.db` — identical to Phase D's acceptance.

### 5.4 Tool-schema compatibility

The new kwarg is keyword-only and optional. Phase D's default-args dict in `_default_args_for` does not currently pass `conn_factory`; under Phase E, `lx_Act` injects it at dispatch time — it never appears in the Cognate's planned args dict, only in the call-site invocation. This means `procedural_wins` entries stay schema-identical across the Phase D → E boundary; existing learned rewards remain queryable.

---

## 6. GUI Rewire (Architecture)

### 6.1 Current state

```python
# gui/main_window.py:9
from core.loop import CoreLoop
# gui/main_window.py:41
self.loop = CoreLoop(self.state, self.ollama, self.tools)

# gui/loop_panel.py:11
from core.loop import LoopStep
# Phase enum drives color codes and segment order.
```

### 6.2 Phase E rewire

**`gui/main_window.py`:**
- Import `from core.core import ServoCore` alongside the existing `CoreLoop` import.
- Add a config toggle `USE_SERVO_CORE` (environment variable `SERVO_CORE=1` or config.json `use_servo_core: true`). Default: `True` in Phase E.
- When true, construct `ServoCore(self.state, self.ollama, self.tools, config=self.config)` and expose the same Qt-signal surface the GUI expects.
- `CoreLoop` construction path stays intact for rollback; gated on the same toggle.

**`gui/loop_panel.py`:**
- Replace `from core.loop import LoopStep` with a new `core.lx_steps` module that re-exports a `Step` enum whose values are the six Cognate-world phases. The names and order match the Phase D manifest (`PERCEIVE, CONTEXTUALIZE, REASON, ACT, INTEGRATE, OBSERVE`), so the existing color-map dict keyed on step names continues to work with a one-line import swap.
- `core.lx_steps` is a thin re-export: it imports `LoopStep` from `core.loop` (preserving No-Write) and aliases it as `Step`. This dodges any conceivable circular-import issue and keeps `loop.py` untouched.

**`gui/tool_panel.py`:**
- `TOOL_IS_SYSTEM` display flag unchanged (Phase D §3 constraint).
- Panel reads its dispatch surface from `ServoCore.ATOMIC_PRIMITIVES` (exposed as a public frozenset) rather than from the legacy tool registry. The eleven Phase D primitives now drive the panel's enabled/disabled rendering.
- Row-highlight logic for the currently-dispatched tool reads from a new Qt signal `ServoCore.tool_dispatched(tool_name: str)`; emission happens in `ServoCore.run_cycle` right before the `lx_Act` call.

### 6.3 `gui/log_panel.py` is out of scope

The file has two references to `CoreLoop.log_event` (lines 156, 464). Rewiring the Qt-signal layer is Phase F — log_panel still works in Phase E because it consumes events from whichever loop is running, and the Cognate logging channel can emit the same event shape.

### 6.4 Rollback path

Setting `SERVO_CORE=0` (or `use_servo_core: false` in config) restores the legacy `CoreLoop` construction path. No GUI file is deleted or rewritten past recognition — every change is additive behind a toggle.

---

## 7. Cold-Start Signal Enrichment

### 7.1 Current behavior (Phase D)

```python
# lx_cognates.py:398
def _observation_signal(self) -> str:
    return "directory_scan"
```

### 7.2 Phase E derivation

`lx_Observe` already stashes the 5-tuple snapshot in `state["env_audit"]` (line 162). `_observation_signal` reads it and classifies:

```python
def _observation_signal(self, state: dict) -> str:
    audit = state.get("env_audit") or {}

    # (1) Empty project: total symbols across all roots <= 5
    total_symbols = 0
    for root, tup in audit.items():
        if isinstance(tup, (list, tuple)) and len(tup) >= 2 and tup[1] >= 0:
            total_symbols += tup[1]
    if total_symbols <= 5:
        return "empty_project"

    # (2) Drift: compare to cached prior snapshot
    prior = self.core._prior_audit_snapshot
    if prior and self._drift_percent(prior, audit) >= 0.10:
        return "drift_detected"

    # (3) Default
    return "directory_scan"
```

### 7.3 Lookup table expansion

```python
_COLD_START_LOOKUP = {
    "empty_project":   ("map_project", {"path": ".", "depth": 3}),
    "drift_detected":  ("map_project", {"path": ".", "depth": 2}),
    "directory_scan":  ("file_list",   {"path": ".", "recursive": False}),
    "default":         ("file_list",   {"path": ".", "recursive": False}),
}
```

### 7.4 Why this matters

Under Phase D, every cold start (before `procedural_wins` has enough signal) does the same directory_scan. On a project Servo has never seen, that's fine. On Servo's own project mid-refactor, the directory_scan's reward is already saturated and the scan contributes nothing new. Reading env_audit gives the exploit-less branch a reason to pick `map_project` or `file_read` based on actual project state, not a constant.

### 7.5 Prior-snapshot cache

`ServoCore._prior_audit_snapshot` is set in `lx_Integrate` at the end of each cycle, holding the env_audit that just ran. First cycle has `prior is None`, so drift detection falls through to the default branch. Cache survives across `run_cycle` invocations in a single process; cleared on `ServoCore.__init__` (fresh boot).

---

## 8. Execution Order (Seven Steps)

Dependency-driven; each step lands cleanly (incl. Phase A benchmark green) before the next.

1. **Add `core/config_registry.py` with `_DEFAULTS` matching Phase D literals.** Unit test: `ConfigRegistry()` with no config.json returns every default; `ConfigRegistry()` with a malformed config.json still returns defaults (no raise).
2. **Thread `config` through `ServoCore.__init__` → Cognates + `lx_StateStore`.** Update call sites in `lx_cognates.py` and `lx_state.py` to consult `self.core.config.get(...)` with literal fallback when `config is None`. Verify: Phase A audit green, no behavioral change (all defaults match prior literals).
3. **Refactor `memory_manager` and `memory_snapshot` to accept `conn_factory` kwarg.** Default path unchanged. Verify: standalone tool tests still pass (no conn_factory, legacy path).
4. **Retire the memory-routing branch of `core/lx_loop_shim.py`.** `ServoCore.run_cycle` injects `conn_factory=self._lx_conn_factory` at dispatch. Shim's `LxLoopAdapter` (for `system_config` / `context_dump`) stays untouched. Verify: 100-cycle bench, sha256(state.db) identical before/after (same check as Phase D Step 8).
5. **Cold-start signal enrichment.** Add `_prior_audit_snapshot` to `ServoCore`, rewrite `_observation_signal(state)`, expand `_COLD_START_LOOKUP`. Verify: synthetic states produce correct signals across all three branches (empty_project, drift_detected, directory_scan).
6. **GUI rewire.** Add `core/lx_steps.py`, update `gui/loop_panel.py` import. Update `gui/main_window.py` to construct `ServoCore` behind `USE_SERVO_CORE` toggle (default True). Update `gui/tool_panel.py` dispatch-surface read. Verify: GUI boots under both toggle states; `loop_panel` renders all six phases in correct order; `tool_panel` shows all eleven primitives.
7. **Full Phase A audit.** `python -m benchmark.lx_audit_manager` green. Acceptance gates in §9 pass.

---

## 9. Acceptance Gate

Phase E is **complete** iff:

- `python -m benchmark.lx_audit_manager` exits 0 with `Overall Pass: True`.
- `ConfigRegistry` round-trips: writing `{"epsilon_0": 0.5}` to `config.json`, re-instantiating the registry, and reading `get("epsilon_0")` returns 0.5; deleting the file and re-instantiating returns the default 0.3.
- `sha256(state/state.db)` is byte-identical before and after a 100-cycle bench run with `memory_manager` and `memory_snapshot` dispatched (Phase D Step 8 pattern, re-run with conn_factory path).
- `git diff --ignore-cr-at-eol core/loop.py` is empty. (No-Write constraint satisfied.)
- `lx_Reason._observation_signal(state)` returns all three enriched signals when fed synthetic states matching each branch's conditions; returns `"directory_scan"` on first cycle (prior snapshot is None).
- `gui/main_window.py` under `SERVO_CORE=1` constructs `ServoCore` and the GUI boots; under `SERVO_CORE=0` it constructs `CoreLoop` and the GUI boots. Both paths exercised in a smoke test.
- `gui/loop_panel.py` renders the six Cognate phases in the Phase D order with unchanged color codes.
- `procedural_wins` retains all Phase D entries and accepts new entries with unchanged metadata schema — the ConfigRegistry migration does not invalidate prior learning.
- No new file larger than 300 lines is introduced. (ConfigRegistry ~80 lines, lx_steps ~20 lines, cold-start classifier ~40 lines.)

Any single failure re-opens the circuit; no partial credit.

---

## 10. Open Questions (Resolved)

All questions resolved by Kevin during plan review (D-20260424). Recorded here for the audit trail; Phase E execution proceeds with the decisions below baked in.

- **Q1 — config.json location: RESOLVED.** `codex/manifests/config.json`. Config lives with the identity/truth layer alongside `manifest.json` and `persona_core.md`. `workspace_policy.codex_writers` governs authorship.
- **Q2 — `embed_model` default handling: RESOLVED.** Literal-as-default. `OllamaClient.__init__` keeps `embed_model="nomic-embed-text"` as the declared default; `ConfigRegistry.get("embed_model")` overrides when a registry is passed. Direct `OllamaClient()` callers keep working unchanged.
- **Q3 — `conn_factory` surface: RESOLVED.** Uniform extension. `memory_manager`, `memory_snapshot`, `task`, and `context_dump` all gain the optional keyword-only `conn_factory` kwarg. No behavior change when omitted; establishes a uniform tool-context contract for Phase F.
- **Q4 — `USE_SERVO_CORE` default: RESOLVED.** Default `True`. GUI runs on ServoCore out of the box in Phase E. Rollback remains a single env-var flip (`SERVO_CORE=0`).
- **Q5 — `ATOMIC_PRIMITIVES` exposure: RESOLVED.** Expose as a public frozenset on `ServoCore`, with a comment that consumers should not rely on ordering. Single-import directness wins over method-wrapping for the Phase E GUI read.
- **Q6 — `manifest_stale` detection: REMOVED FROM SCOPE.** Heuristic was too noisy (codex is mostly markdown; the sentinel would fire on any unrelated parse failure). Signal dropped entirely. Cold-start classifier ships with three branches: `empty_project`, `drift_detected`, `directory_scan`.

---

## 11. Intellectual Honesty Notes

- **ConfigRegistry on first pass is a glorified dict with a reload method.** That's the point. Phase E migrates literals without committing to an over-engineered config system. Phase F adds hot-reload and telemetry-driven tuning; neither belongs in Phase E's scope.
- **`core/lx_steps.py` is a one-line re-export dodge.** It exists specifically to keep `gui/loop_panel.py` from importing `core.loop` directly while honoring the No-Write constraint. If a future phase refactors `LoopStep` out of `loop.py`, the shim goes with it.
- **The conn_factory refactor retires one monkey-patch and leaves another.** The `_get_loop_ref` intercept for `system_config` and `context_dump` stays through Phase E because refactoring those tools requires a broader context-injection contract (they read `loop.state`, `loop.config`, `loop.telemetry` — not just a connection). That's a Phase F concern.
- **Cold-start enrichment is heuristic, not principled.** The four-signal classifier is a pragmatic first cut. Phase F might replace it with a similarity query against env_audit snapshots in ChromaDB (reusing the Phase D NN infrastructure). Phase E's version is good enough to beat "always return directory_scan."
- **GUI rewire behind a toggle is risk-management, not indecision.** A default-true toggle with a one-flip rollback is the lightest possible shipping discipline for code touching the user-visible surface. Phase F removes the toggle once the rewire has a couple of real-world cycles behind it.
- **No-Write on loop.py remains the plan's cornerstone.** Phase E's acceptance gate re-checks `git diff` on loop.py. Breaking that invariant mid-plan would require an ADR and Kevin's explicit sign-off.

---

*Plan Version: 4.0.1 (D-20260424, open questions resolved, pending execution approval)*
*Prepared after Phase D landing. Await explicit approval before execution.*
