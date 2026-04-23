# UPGRADE_PLAN_2.md
**Phase:** C — Injecting Intelligence into the Cognate Scaffold
**Status:** APPROVED FOR EXECUTION | **Priority:** CRITICAL
**Author:** Servo (Claude, in cooperation with Kevin & Gemini)
**Date:** D-20260423
**Supersedes Scope-Of:** `UPGRADE_PLAN.md` (closed)
**Anchors-On:** `PLAN_PHASE_A_BENCHMARKS.md`, `PLAN_PHASE_B_SCAFFOLD.md`, `PLAN_PHASE_C_BRAIN.md`
**Synced Commit:** `ad2e20c7` (2026-04-22T21:11:35Z)

---

## 1. Objective

Replace the stub bodies in `core/lx_cognates.py` with real Cognate logic, wired to a persistent `lx_StateStore`, so that `ServoCore.run_cycle` can drive a closed-circuit OBSERVE → REASON → ACT → INTEGRATE loop against the atomic-primitive tool surface — producing behaviorally-indistinguishable outcomes from `loop.py` while logging **Success Vectors** to a dedicated ChromaDB collection.

Phase C is **intelligence injection**, not feature expansion. Nothing in this plan changes the registry keys, the Cognate signatures, or the `run_cycle` shape already shipped in Phase B. The polymorphic contract is frozen.

---

## 2. Scope (Medium: Deep on C, Stubs for D/E/F)

**In-Scope for This Plan:**
- Real execution bodies for all four Cognates.
- `lx_StateStore` ChromaDB handshake + JSON mirror.
- `ToolOutcome` wrapper defining the ACT/REASON handshake contract.
- Atomic-primitive-only `lx_Act` dispatch surface.
- Reward computation `R = Φ·(L·P)`, ε-greedy exploration with exp(-λt) decay.
- Benchmark acceptance gate (Phase A suite must pass against the upgraded core).

**Stub-Only (Deferred to Phases D/E/F):**
- Phase D: Rewire `TOOL_IS_SYSTEM` tools to run under Cognate dispatch.
- Phase E: GUI migration off `loop.py` (task panel, tool panel, context viewer).
- Phase F: Retire `loop.py`; promote `core.py` to sole runtime.

Phases D–F are acknowledged here only so cross-cutting decisions (naming, schema, contracts) don't paint them into a corner.

---

## 3. Constraints Inherited from Prior Decisions

These are non-negotiable for Phase C; any deviation must be logged as a new ADR before the fact.

- **Reference preservation of `loop.py`** — Phase C adds, does not subtract. `loop.py` is **never edited in place**; it stays on disk as the original reference loop. Whether it remains runnable is a side-effect, not a requirement.
- **No-Write policy on legacy assets during bench mode** — `core.py` and its Cognates must not mutate files owned by the `loop.py` runtime (config SQLite, task ledger, memory snapshots, and `loop.py` itself). Read-only bridge only.
- **Atomic-primitive-only dispatch** (D-20260421-14) — `lx_Act` targets exactly: `file_read`, `file_write`, `file_list`, `file_manage`, `map_project`, `summarizer`. The legacy composite tools are out of scope.
- **`TOOL_IS_SYSTEM` exclusion** (D-20260422-05) — The six yellow-coded system tools (`task`, `system_config`, `context_dump`, `memory_manager`, `summarizer`*, `memory_snapshot`) are **filtered out** of Cognate dispatch this phase. `summarizer` is the exception: it is promoted to first-class (D-20260421-14) and is permitted under its atomic-primitive identity. Breakage of the other five is accepted and deferred to Phase D.
- **`--chores` bootstrap pattern** (D-20260422-06) — `lx_Observe`'s environment audit inherits the chores-scan shape. Observe reads `chores.md` (or equivalent environment manifest) as its first action each cycle.
- **Hardcoded tunables on first pass** — All reward weights, thresholds, and decay constants are literals in code. Config-registry migration is Phase E.
- **Lexicon compliance is a gate, not a goal** — The Phase A `lx_lexicon` filter is the acceptance signal. Any Cognate output that trips FAIL_PATTERNS opens the circuit.

---

## 4. The `ToolOutcome` Contract

Phase B currently has Cognates passing freeform dicts. Phase C formalizes the ACT ↔ REASON handshake so the reward computation has a stable surface.

```python
# core/lx_outcomes.py (new)
@dataclass
class ToolOutcome:
    status: Literal["ok", "fail", "skip"]   # ok = exit 0 equivalent
    return_value: Any                        # tool's actual payload
    stderr: str                              # prose/error channel
    latency_ms: float                        # measured at dispatch
    tool_name: str                           # which atomic primitive
    args_fingerprint: str                    # sha1(json(args)), for dedup
```

`lx_Act.execute` returns a delta containing `{"last_outcome": ToolOutcome, ...}`.
`lx_Integrate` reads `last_outcome` to compute reward. `lx_Reason` reads `last_outcome.stderr` on the *next* cycle to adjust plans.

---

## 5. The Reward Function

```
R = Φ · (L · P)

Φ = lexicon_pass          (1.0 if zero FAIL_PATTERNS in stderr, else 0.0)
L = 1 / (1 + latency_ms/1000)    (latency penalty, asymptotes to 0)
P = 1.0 if status == "ok" else 0.3 if "skip" else 0.0   (progress signal)

Commit to procedural_wins iff R ≥ 0.8.
```

Φ is a hard multiplicative gate — any lexicon violation zeros the reward regardless of latency or success. This is intentional: prose noise is a circuit-breaker, not a demerit.

---

## 6. ε-Greedy Exploration with Decay

```
ε(t) = ε_0 · exp(-λ · |procedural_wins|)

ε_0 = 0.3      (first-pass literal)
λ   = 0.001    (first-pass literal)
```

On each `lx_Reason` cycle, draw `u ~ U[0,1]`:
- If `u < ε(t)`: pick a random atomic primitive (explore).
- Else: pick the tool with the highest historical R for the current observation signature (exploit).

Observation signature = sha1 of the OBSERVE cognate's environment-audit output. Exact match only on first pass; fuzzy nearest-neighbor via ChromaDB is a Phase D concern.

---

## 7. Execution Order (Nine Steps)

The order is dependency-driven. Each step must land cleanly — including Phase A benchmark pass — before the next begins.

1. **ChromaDB handshake in `lx_StateStore`** — Implement `sync_vector()`. Create the `procedural_wins` collection if absent. Add the JSON mirror (write-through to `state_profile.json` on every `apply_delta`).
2. **`ToolOutcome` dataclass + atomic-primitive dispatch stub in `lx_Act`** — Wire the six atomic tools into `lx_Act.execute`. Return `ToolOutcome` in the delta. No reward yet, no exploration yet — just deterministic dispatch of a pre-specified tool.
3. **Basic `lx_Reason` (exploit-only)** — Read `last_outcome.stderr`, pick the next tool from a static lookup table. No ε-greedy yet. This exists so the loop cycles end-to-end.
4. **Real `lx_Observe`** — Port the `--chores` environment-audit pattern. Emit observation signature in the delta.
5. **`lx_Integrate` with reward computation** — Compute `R`, commit to `procedural_wins` when `R ≥ 0.8`, reset cursor to OBSERVE.
6. **Read-only legacy-config bridge** — `lx_StateStore` gets a `get_legacy_config(key)` method that reads the `loop.py` SQLite config. Never writes.
7. **Full ε-greedy in `lx_Reason`** — Replace the static lookup with the exploration policy. Pull historical R from `procedural_wins`.
8. **Lexicon filter wired into the dispatch path** — `ToolOutcome.stderr` is scanned against Phase A's FAIL_PATTERNS before reward computation. Failures open the circuit (set `halt: True` in the delta) and log an audit event.
9. **Full Phase A audit pass** — `lx_audit_manager.py` runs `lx_lexicon`, `lx_performance`, and `lx_correctness` against `core.py` and must pass all four MVBs, demonstrate improved jitter over the `loop.py` baseline (CV ≤ 0.15 for this phase; 0.05 is Phase D's target), and emit zero lexicon violations.

---

## 8. Acceptance Gate

Phase C is **complete** iff all of the following hold:

- `python -m benchmark.lx_audit_manager --target core.py` exits 0.
- `procedural_wins` ChromaDB collection contains ≥ 10 entries from genuine cycles (not seed data).
- `state_profile.json` mirror is byte-identical to the ChromaDB latest-delta readback across three consecutive cycles.
- `loop.py` on disk is byte-identical to its pre-Phase-C state (`git diff loop.py` returns empty). Runtime bootability is a nice-to-have, not a gate.
- Zero writes to any path owned by `loop.py` detected during a 100-cycle bench run (instrumented via `file_manage` audit).

Any single failure re-opens the circuit; no partial credit.

---

## 9. Deferred: Phases D / E / F

- **Phase D — System Tool Rewire:** Bring the five excluded `TOOL_IS_SYSTEM` tools under Cognate dispatch. Target CV ≤ 0.05. ChromaDB nearest-neighbor observation matching.
- **Phase E — GUI Migration:** Rewire `gui/tool_panel.py`, task panel, and context viewer off `loop.py` imports onto `core.py`. Migrate hardcoded Phase C tunables into ConfigRegistry with bidirectional GUI sync.
- **Phase F — Legacy Retirement:** Delete `loop.py`. Promote `core.py` to `main.py`'s sole runtime target. Archive the task ledger SQLite.

---

## 10. Open Questions (Logged, Not Blocking)

- **Q1 — RESOLVED:** Store the full `ToolOutcome` in `procedural_wins` on first pass. Compression / fingerprinting is a later Integrate-phase refinement, not a Phase C concern.
- **Q2:** Does `lx_Observe` need to deduplicate identical environment signatures within a single session, or is that the reward function's job? — **Deferred; first-pass allows duplicates and lets the reward smooth them.**
- **Q3 — Cold-start question (non-blocking):** When ε-greedy tries to *exploit* a tool choice for an observation signature it has never seen before, it has no historical R to rank by. First-pass fallback: uniform random over the six atomic primitives. Phase D may introduce a curiosity bonus or nearest-neighbor signature match.

---

## 11. Intellectual Honesty Notes

Areas where this plan intentionally diverges from Gemini's handover framing:

- **"overall_pass: false" as a success metric** is rejected. The metric is `R ≥ 0.8` against `procedural_wins` — pass/fail is a projection, not the signal.
- **Starting with `lx_Integrate`** is rejected. Integrate depends on Act's outcome shape and Observe's signature shape; it is implemented fifth, not first.
- **"Reasoning Node" as a persona** is rejected. Cognates are functions, not agents. No persona surface.
- **"Subprocess exit code"** is replaced by `ToolOutcome.status`. The atomic primitives are in-process; subprocess semantics don't apply.

---

*Plan Version: 2.0.0 (D-20260423)*
*Prepared in cooperation with Gemini 3 Flash (scaffolding) and Kevin (validation & direction).*
