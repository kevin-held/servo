# UPGRADE_PLAN_3.md
**Phase:** D — System-Tool Rewire + Real Embeddings + Symbolic Observation
**Status:** DRAFT — PENDING APPROVAL | **Priority:** HIGH
**Author:** Servo (Claude, in cooperation with Kevin & Gemini)
**Date:** D-20260423
**Supersedes Scope-Of:** `UPGRADE_PLAN_2.md` (closed, Phase C landed as v1.4.0)
**Synced Commit:** post-D-20260423-01 (Phase C ADR accepted)

---

## 1. Objective

Phase C delivered a closed circuit over the six atomic primitives with a live learning signal. Phase D widens the circuit and sharpens its senses:

1. **(a) System-tool rewire** — bring `task`, `system_config`, `context_dump`, `memory_manager`, `memory_snapshot` under Cognate dispatch at the same reward tier as the atomic primitives, without violating the No-Write policy on `loop.py` assets.
2. **(b) Symbolic-drift observation** — upgrade `lx_Observe` from file-counting to a structural signature that captures class/function topology and notices when the codebase meaningfully changes shape rather than just when a file is added.
3. **(c) Real-embedding nearest-neighbor** — replace the exact-match metadata query in `procedural_wins` with a true semantic NN over Ollama-sourced embeddings, so an unseen-but-similar observation can still exploit prior wins.
4. **(d) ToolOutcome compression** — fingerprint the `return_value` and `stderr` channels so procedural_wins stays cheap as the dispatch surface grows (Phase D doubles the tool count from six to eleven).

Phase D is **surface expansion + cognition sharpening**, not architectural reshape. The polymorphic contract (`OBSERVE → REASON → ACT → INTEGRATE`) stays frozen. `lx_StateStore`'s public API stays frozen. `loop.py` stays untouched at the source level.

---

## 2. Scope

**In-Scope:**
- Dispatch surface: `ATOMIC_PRIMITIVES` grows from 6 to 11; `_FORBIDDEN_TOOLS` shrinks to the empty set.
- Loop-ref shim: a single adapter that presents the `_get_loop_ref()` surface the sys-tools currently expect, sourced from `ServoCore + lx_StateStore` when running under Phase D and from `CoreLoop` when running under legacy boot. Neither sys-tool file is edited in place — the shim lives in a new module and is wired via monkey-patching at import time (reversible).
- Memory routing: `memory_manager` reads/writes the lx_state JSON mirror when dispatched from a Cognate, and falls back to the legacy SQLite path when dispatched from `loop.py`. Detection happens in the shim, not in the tool.
- Observation signature: a `(file_count, symbol_count, class_count, function_count, import_count)` tuple per canonical root, hashed to a stable signature. Drift detection: two cycles hashing to the same signature iff they see the same symbolic topology.
- Ollama embedding helper: a new `OllamaClient.embed(text, model="nomic-embed-text")` method plus a thin cache layer in `lx_StateStore`. Embeddings commit to `procedural_wins` alongside metadata.
- NN query path: `lx_StateStore.query_success_vectors(obs_sig, obs_embedding=None, k=10)` runs ChromaDB semantic search when `obs_embedding` is present and falls back to exact-match when it's `None`.
- ToolOutcome compression: `return_value` and `stderr` get `sha1_fingerprint` fields; full text stored in `documents` (chromadb's payload channel) while metadata stays small.

**Stub-Only / Deferred to Phase E+:**
- GUI migration off `loop.py` imports.
- ConfigRegistry migration of Phase C/D hardcoded tunables.
- Retirement of `loop.py`.
- Curiosity bonus for unseen observation signatures (Phase D's NN match subsumes most of the motivating cases).

---

## 3. Constraints Inherited from Prior Decisions

- **Reference preservation of `loop.py`** (from Phase C) remains active. No edits to `core/loop.py` or anything imported only by it.
- **No-Write policy on legacy assets** — refined: `lx_StateStore`'s read-only bridge to the legacy SQLite stays. `memory_manager` under Cognate dispatch writes to the lx_state JSON mirror, not the legacy `state/state.db`. The legacy DB remains a read-only reference (per Phase C).
- **Atomic-primitive contract** (D-20260421-14) — extended, not redefined. The eleven Phase D primitives share the same execute signature contract and the same `ToolOutcome` wrapper.
- **TOOL_IS_SYSTEM is a display flag, not a dispatch filter** — Phase D unifies dispatch. `TOOL_IS_SYSTEM = True` continues to drive the yellow highlight in the GUI tool panel; it no longer gates Cognate selection.
- **Lexicon compliance is a gate, not a goal** (from Phase C) remains active across the expanded surface.
- **Hardcoded tunables on first pass** — the new constants (`OBSERVE_SYMBOLIC_WEIGHT`, `EMBEDDING_MODEL`, `NN_SIMILARITY_FLOOR`) land as literals. Config-registry migration is Phase E.

---

## 4. Loop-Ref Shim (Architecture)

The three sys-tools that depend on a running CoreLoop (`system_config`, `context_dump`, `memory_snapshot`) currently do:

```python
from core.loop import _get_loop_ref  # module-global
loop = _get_loop_ref()
# then reads loop.telemetry, loop.state, loop.config, etc.
```

Phase D adds `core/lx_loop_shim.py`:

```python
# core/lx_loop_shim.py (new)
class LxLoopAdapter:
    """Presents the CoreLoop surface the sys-tools expect, sourced from ServoCore."""
    def __init__(self, servo_core, lx_store):
        self._core = servo_core
        self._store = lx_store

    @property
    def state(self): return self._store            # .conn for legacy SQL callers
    @property
    def config(self): return _ConfigProxy(self._store)  # legacy-config readonly bridge
    @property
    def telemetry(self): return _TelemetrySnapshot.empty()  # Cognate world has no GUI telemetry
    # ... other surface as discovered during Phase D
```

At `ServoCore.run_cycle` entry, when the active store has `_adapter_installed` unset, we install `lx_loop_shim.LxLoopAdapter` as the return value of `tools.system_config._get_loop_ref`, `tools.context_dump._get_loop_ref`, `tools.memory_snapshot._get_loop_ref` via `monkey_patch` (reversible — stashed original is restored at `run_cycle` exit).

**This preserves No-Write on `loop.py`**: the sys-tool files are not edited in place. The shim is Cognate-world infrastructure.

**Test isolation**: the monkey-patch scope is the duration of `run_cycle`. A subsequent `loop.py` boot in the same process finds the original `_get_loop_ref` restored and behaves as before.

---

## 5. Symbolic-Drift Observation

Current `_snapshot_environment` (Phase C):
```python
for name in ("core", "gui", "tools", "codex"):
    snapshot[name] = sum(1 for _ in sub.rglob("*.py"))
```

Phase D upgrades this to a 5-tuple per root:
```python
(file_count, total_symbols, class_count, function_count, import_count)
```

Implementation:
- Walk `*.py` files with `ast.parse` (stdlib, no new dep).
- Count `ast.ClassDef`, `ast.FunctionDef`, `ast.AsyncFunctionDef`, `ast.Import`, `ast.ImportFrom`.
- `total_symbols = class_count + function_count` (semantically meaningful top-level surface).
- Fall through to `(-1, -1, -1, -1, -1)` on any `SyntaxError` or `OSError` for that root — preserves Phase C's sentinel pattern.

Signature: `sha1` over `sorted(f"{root}={tuple}" for root, tuple in snapshot.items())`, truncated to 16 chars.

**Why this matters**: Phase C's file-count signature says "core has 18 python files" and doesn't change when someone adds a new method to `lx_cognates.py`. Phase D's signature registers that addition. The exploit branch gets more-specific context to rank against. The explore branch converges faster.

**Cache**: AST parsing is slow. `lx_Observe` caches the (file_path, mtime) → tuple dict across cycles. A file whose mtime hasn't changed reuses its parse result. Cache lives on the Cognate instance, cleared when the observation signature itself changes by a threshold.

---

## 6. Ollama Embeddings + Nearest-Neighbor Matching

**6.1 OllamaClient upgrade:**
```python
# core/ollama_client.py — new method
def embed(self, text: str, model: str = None) -> list[float] | None:
    """Single-vector embedding. None on any failure (degrade, don't raise)."""
    try:
        r = requests.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model or self.embed_model, "prompt": text},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("embedding")
    except Exception:
        return None
```

`OllamaClient.__init__` gets a new `embed_model="nomic-embed-text"` parameter. `nomic-embed-text` is a 137M-param model (~270 MB on disk) that Kevin can `ollama pull` once; no code changes needed if the model name changes — the literal is a first-pass default and migrates to ConfigRegistry in Phase E.

**6.2 Embedding substrate for procedural_wins:**
- Phase C's `commit_success_vector` passes `embeddings=[[0.0, 0.0, 0.0, 0.0]]`. Phase D replaces that with a real vector when one is available:
  ```python
  obs_vec = self._core.ollama.embed(json.dumps(outcome_snapshot))
  if obs_vec is None:
      obs_vec = [0.0] * 768  # nomic-embed-text dim; graceful degrade
  self._procedural_wins.add(embeddings=[obs_vec], ...)
  ```
- Dimension: 768 for `nomic-embed-text`. Stored as `List[float]`. ChromaDB handles the index internally.

**6.3 NN query:**
```python
def query_success_vectors(
    self, observation_signature: str, obs_embedding: list[float] | None = None,
    limit: int = 10, similarity_floor: float = 0.7,
) -> list:
    if self._procedural_wins is None:
        return []
    if obs_embedding is not None:
        # Semantic search
        res = self._procedural_wins.query(
            query_embeddings=[obs_embedding], n_results=limit,
        )
        # Apply similarity floor on distances
        ...
    else:
        # Phase C's exact-match path — kept for tests and degraded mode
        res = self._procedural_wins.get(
            where={"observation_signature": observation_signature}, limit=limit,
        )
    return _flatten_metadatas(res)
```

**6.4 lx_Reason upgrade:**
- Observation embedding is computed once per OBSERVE cycle, stored in `state["observation_embedding"]`.
- `_exploit` pulls `state["observation_embedding"]` and passes it to `query_success_vectors`. On Ollama-down, `obs_embedding` is None and we fall back to exact-match (Phase C behavior).

**6.5 Graceful degradation:** Ollama unreachable → `embed()` returns None → commits store zero-vectors → queries fall back to exact-match → loop still runs. The only thing lost is the semantic-similarity lift. This matches Phase C's `_chroma_degraded` pattern: a missing signal never opens the circuit.

---

## 7. ToolOutcome Compression

Current `ToolOutcome` stores the full `return_value` and `stderr` strings. For short tool outputs (≤1KB) this is fine. For `summarizer` or `map_project` outputs (10-100KB), procedural_wins grows expensively.

Phase D adds fingerprint fields:
```python
@dataclass
class ToolOutcome:
    # ... existing fields ...
    return_value_sha1: str       # new — sha1 of return_value, 16 chars
    stderr_sha1: str             # new — sha1 of stderr, 16 chars
    return_value_bytes: int      # new — len(return_value.encode())
    stderr_bytes: int            # new — len(stderr.encode())
```

- Metadata stored in procedural_wins: just the sha1 fingerprints + byte counts.
- Full text: kept in ChromaDB's `documents` field (separate column, lazily fetched).
- Retrieval: `query_success_vectors` returns metadata only by default. `get_success_vector_bodies(entry_ids)` fetches full text only when explicitly requested.

This keeps hot-path memory usage flat as the dispatch surface grows. It also makes `observation_signature + tool_name + return_value_sha1 + reward` the content-hash for entry_id, which is what Phase C already does conceptually but without the explicit field.

---

## 8. Execution Order (Nine Steps)

Dependency-driven; each step lands cleanly (incl. Phase A benchmark green) before the next.

1. **Add `OllamaClient.embed()` + `embed_model` parameter.** Smoke-test against a live `nomic-embed-text` model. Kevin confirms model is pulled before this step — if not, step 1 writes the method but returns None on every call, and step 6 still works in degraded mode.
2. **Symbolic-drift observation** — rewrite `lx_Observe._snapshot_environment` to produce 5-tuples, add AST cache, verify deterministic signatures across cycles.
3. **ToolOutcome compression** — add fingerprint fields, update `from_tool_output` classmethod, wire into `commit_success_vector`. Backward-compatible (older entries without fingerprints still readable).
4. **Loop-ref shim** — write `core/lx_loop_shim.py`, test in isolation against each of the three dependent sys-tools. Verify the monkey-patch is reversible (before/after `loop.py` boot smoke test).
5. **Dispatch-surface expansion** — move the five sys tools into `ATOMIC_PRIMITIVES`, drop `_FORBIDDEN_TOOLS` to `frozenset()`, add default-args entries in `_default_args_for`. Each sys-tool gets a hand-authored safe default that won't produce destructive side effects on a benchmark run (e.g. `task` defaults to `action="list"`, `memory_manager` defaults to a read-only op).
6. **Real-embedding commits** — replace dummy embeddings in `commit_success_vector` with Ollama-sourced vectors. Verify commits land with real 768-dim vectors; verify `_chroma_degraded` still isolates the loop when Ollama is down.
7. **NN query wiring** — add the semantic-search branch to `query_success_vectors`, wire `lx_Reason._exploit` to pass `obs_embedding`. Fallback to exact-match on None remains the default path for tests.
8. **Memory-routing decision** — `memory_manager` under Cognate dispatch writes to lx_state JSON mirror; under `loop.py` writes to legacy SQLite. Detection via the shim — when the adapter is installed, memory_manager's writes route through the adapter. Verify via bench run: no writes to `state/state.db` during a 100-cycle bench.
9. **Full Phase A audit** — `python -m benchmark.lx_audit_manager` green. Acceptance gates in §9 pass.

---

## 9. Acceptance Gate

Phase D is **complete** iff:

- `python -m benchmark.lx_audit_manager` exits 0 with `Overall Pass: True`.
- `procedural_wins` contains entries across all 11 primitives (not just the 6) after a 50-cycle bench run.
- Real embeddings stored: at least 10 entries in `procedural_wins` have a non-zero-vector `embedding` field (Ollama reachable during the bench).
- `lx_Reason` semantic NN hit rate: on an observation signature that differs from a historical one by a single digit of symbol count but is otherwise close, the NN query returns the neighbor with similarity ≥ 0.7.
- Zero writes to `state/state.db` (loop.py's SQLite) during the 50-cycle bench, even with `memory_manager` dispatched.
- `git diff --ignore-cr-at-eol core/loop.py` and `git diff --ignore-cr-at-eol tools/system_config.py tools/context_dump.py tools/memory_snapshot.py tools/task.py tools/memory_manager.py` both empty — every file edited in Phase D is a new file or is `core/lx_*.py`.
- `loop.py` still boots and passes its own smoke test (nice-to-have per Phase C gate).

Any single failure re-opens the circuit; no partial credit.

---

## 10. Open Questions (Logged)

- **Q1 — default-args for sys-tools:** `task(action="list")` and `memory_manager(action="append", content="probe")` are the natural Cognate-world probes. `system_config(operation="get", parameter="model")` reads the current model. `context_dump(show_user=False, pause_loop=False)` returns a snapshot. `memory_snapshot(label="bench")` takes a labeled snapshot. Are any of these destructive on a live machine (not a benchmark env)? **Proposed default: all read-only or idempotent; destructive actions only via explicit Reason plans.**
- **Q2 — AST cache key:** Using `(file_path, mtime)` as the cache key means touching a file invalidates the cache. Is mtime resolution (1 second on most filesystems) sufficient, or do we need `(file_path, size, mtime)` to handle same-second edits? **Proposed first-pass: `(path, mtime, size)`.**
- **Q3 — Similarity floor:** 0.7 for `nomic-embed-text` in the NN query is a guess. Phase D ships with the literal; Phase E migrates it to ConfigRegistry with telemetry-driven tuning. **Proposed: 0.7 as first-pass floor.**
- **Q4 — Memory-routing shim detail:** The shim has to intercept `memory_manager`'s direct sqlite3 calls without editing the tool file. Options: (a) Shim wraps `sqlite3.connect` for that path at monkey-patch time, (b) Shim provides an alternative DB path via an env var that `memory_manager` happens to honor (it doesn't today — would require a small patch). Phase D picks (a) for first-pass because it's reversible; Phase E may refactor `memory_manager` to accept a `conn_factory` kwarg for testability.

---

## 11. Intellectual Honesty Notes

- **"nomic-embed-text" is a default, not a commitment.** Any Ollama-served embedding model works once this lands. `mxbai-embed-large`, `bge-m3`, or a multilingual model are drop-in swaps via the `embed_model` parameter.
- **AST parsing isn't free.** Phase D's observation step adds ~20-50ms per cycle on a codebase of this size. Acceptable for a cycle time already in the 100ms-1s range; worth revisiting if Phase E's latency budget tightens.
- **Monkey-patching has a smell.** The loop-ref shim is a pragmatic bridge that dissolves in Phase E when the tools get refactored to accept explicit context. Treating it as permanent would be a mistake.
- **Degraded mode is the tested path, not the fallback path.** Benchmark runs with Ollama down and with Ollama up should both pass; Phase D's testing plan includes both.

---

*Plan Version: 3.0.0 (D-20260423, pending approval)*
*Prepared after Phase C landing. Await explicit approval before execution.*
