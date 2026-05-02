# UPGRADE_PLAN_6 — Phase G: Legacy Retirement, GUI Cleanup, Cold-Start Replacement

**Version target:** v1.8.0
**Date opened:** 2026-04-30
**Status:** Active
**Predecessor:** UPGRADE_PLAN_5 (Phase F — chat-as-perception, v1.7.0 landed 2026-04-26)
**Gate-of-record:** `python -m benchmark.lx_audit_manager` returning `Overall Pass: True` against v1.7.0 — **GREEN CONFIRMED 2026-04-30** (post-hotfix lx_correctness park/wake update, post-ServoCoreThread lx_StateStore wiring fix).

## Context

Phase F shipped chat-as-perception, the perception queue + park/wake gate, the cross-cycle ACT→OBSERVE handoff via `pending_tool_output`, the `response_ready_hook` + `record_turn` persistence, the `ToolContext` per-dispatch injection, the `_get_loop_ref` shim install retirement, `ConfigRegistry.maybe_reload()`, and the `USE_SERVO_CORE` toggle removal. After Phase F:

- `core/loop.py` and `core/lx_loop_shim.py` have **zero callers** in the cognate dispatch path. Both remain on disk only as dormant rollback targets, kept under No-Write discipline since Phase C.
- The GUI `loop_panel` still renders the Phase D six-phase order (`PERCEIVE`/`CONTEXTUALIZE`/`REASON`/`ACT`/`INTEGRATE`/`OBSERVE`) even though the cognate cycle has narrowed to four (`OBSERVE`/`REASON`/`ACT`/`INTEGRATE`).
- The `INSTALLED TOOLS` dropdown in `tool_panel` uses the `CollapsibleSection` wrapper while the Stream Viewer and Log Viewer in the same panel use a `QPushButton` toggle idiom — visual inconsistency.
- A trace section below the loop state widget is non-functional and Kevin has asked for it gone.
- `lx_Reason._observation_signal` still uses the Phase E hand-tuned classifier (`empty_project` / `drift_detected` / `directory_scan`) backed by `_COLD_START_LOOKUP`. The Phase E handoff flagged replacement via ChromaDB env_audit similarity.

Phase G retires the dormant code, fixes the GUI inconsistencies, and replaces the cold-start classifier with a data-driven similarity branch.

## Decisions taken (this plan)

1. **Manual GUI controls** — none added in Phase G. The candidate list (Single Cycle, Reload Config Now, Clear Perception Queue, Reset Profile State) defers to the Phase H+ backlog.
2. **Cold-start replacement strategy** — full replacement, not fallback. The 3-branch heuristic and `_COLD_START_LOOKUP` table are deleted. The new env_audit similarity branch becomes the only cold-start signal; on a double-miss (no `procedural_wins` neighbor + no `env_snapshots` neighbor) the cognate falls through to neutral ε-greedy exploration.
3. **env_snapshot persistence policy** — write only on successful commits (reward ≥ 0.8), same gate as `procedural_wins`. Signal-pure dataset; cold-start neighbors come from cycles that actually worked.
4. **No-Write invariant** — lifted in Phase G Step 1 with the deletion of `core/loop.py`. Documentation references are scrubbed.
5. **Postponed to Phase H+ backlog** — telemetry-driven config tuning, multi-listener `response_ready_hook` fanout, cross-cycle event bus (gated on a third perception producer materializing), GUI manual controls.

## Step-by-step plan

### Step 1 — Loop + shim deletion + No-Write lift

**Pre-deletion grep sweep.** Confirm zero non-comment imports remain across the repo:
- `from core.loop import` — must hit zero non-comment lines.
- `from core.lx_loop_shim import` — must hit zero non-comment lines.
- `import core.loop` and `import core.lx_loop_shim` (alternate forms) — also zero.

**Deletions.**
- `core/loop.py` — delete file.
- `core/lx_loop_shim.py` — delete file.

**Comment scrubs.**
- `core/core.py` — remove the Phase F retirement block that sets `shim_handle = None` and `self._lx_shim_handle = None` inside `run_cycle`. The defensive references are no longer needed once the shim file is gone.
- `gui/main_window.py` — remove the `# from core.loop import CoreLoop` retirement comment.
- `gui/tool_panel.py` — remove the Phase F docstring on `on_tool_dispatched` that mentions ServoCoreThread being the only path; the legacy reference no longer needs explaining.

**Documentation lift.**
- `codex/manifests/decisions.md` — strip "No-Write invariant" / "No-Write discipline" / "No-Write gate" mentions from any active ADR text. Historical ADRs (D-20260423-01, D-20260423-02, D-20260424-01, D-20260426-01) keep their "preserved under No-Write" prose since that was true at the time of those decisions; only forward-looking references get scrubbed.
- `codex/UPGRADE_PLAN_6.md` (this file) — record the lift as part of Step 1.

**Acceptance.**
- `python -m benchmark.lx_audit_manager` still returns `Overall Pass: True`.
- GUI boots, ServoCoreThread starts, OBSERVE parks correctly.
- No new file >300 lines net (we're deleting, not adding).

### Step 2 — GUI cleanup

**2a. Loop-state panel — 4-step display.**
- `gui/loop_panel.py` — update the row list to `["OBSERVE", "REASON", "ACT", "INTEGRATE"]`. The active-step highlight tracks the cognate that just ran via the existing `step_changed` signal. The Phase D `PERCEIVE` / `CONTEXTUALIZE` rows come out.
- `core/lx_steps.py` — narrow the `LoopStep` re-export to the four cognates.
- Verify `gui/main_window._connect_signals` still wires `step_changed` correctly.

**2b. INSTALLED TOOLS dropdown styling.**
- `gui/tool_panel.py` — replace the `CollapsibleSection` wrapper around `tool_list` with a `QPushButton` + `▶/▼` arrow toggle matching the Stream Viewer and Log Viewer idiom. The button text reads `▶ Installed Tools` (collapsed) / `▼ Installed Tools` (expanded). Color matches the existing tool-panel green (`#4CAF50`) for the chevron + label.
- `gui/components.py` `CollapsibleSection` widget stays in place for any future use elsewhere; this is a tool-panel-local change.

**2c. Trace section removal.**
- `gui/loop_panel.py` — delete the `QPlainTextEdit` widget rendering trace lines, the `on_trace_event` slot, and the `_trace_lines` storage if present.
- `gui/main_window.py` — remove the `loop.trace_event.connect(...)` line that targets the loop panel's trace handler.
- `core/lx_servo_thread.py` `trace_event` signal stays defined as a no-op surface for any Phase H+ listener that wants to consume it. Existing emit calls in `lx_servo_thread.run` stay; nothing listens, but emission is cheap.

**Acceptance.**
- Loop panel shows four rows in `OBSERVE → REASON → ACT → INTEGRATE` order; active row highlights as cycles progress.
- INSTALLED TOOLS toggle visually matches Stream Viewer and Log Viewer.
- No trace widget below loop state.
- Audit still green.

### Step 3 — Cold-start replacement (full)

**3a. New ChromaDB collection on lx_StateStore.**
- `core/lx_state.py` — add `env_snapshots_<profile>` collection alongside `procedural_wins`. Pinned to `hnsw:space=cosine` at creation. Same graceful-degradation pattern: `_env_snapshots = None` if chromadb fails to init.

**3b. New methods on lx_StateStore.**
- `commit_env_snapshot(env_audit: dict, embedding: list, tool_name: str, reward: float) -> bool` — writes a row only when `reward >= self._cfg_get("commit_threshold", _COMMIT_THRESHOLD)`. ID is sha1 of `f"{env_audit_payload}|{tool_name}|{reward:.4f}"` (same dedupe pattern as `commit_success_vector`). Metadata: `tool_name`, `reward`, `timestamp`, `embed_source`. Document: JSON-serialized `env_audit` for recovery on demand.
- `query_env_snapshots(embedding: list, k: int = 5, similarity_floor: float = 0.6) -> list[dict]` — cosine kNN, returns `[{"tool_name": str, "reward": float, "_similarity": float, ...}, ...]` sorted by similarity descending. Filters out zero-vector / wrong-dim rows the same way `query_success_vectors` does.
- `similarity_floor` defaults to 0.6 (looser than `procedural_wins`' 0.7 because env-shape similarity is fuzzier than observation-signature similarity). Configurable via `ConfigRegistry` key `env_snapshot_similarity_floor`.

**3c. lx_Integrate writes the snapshot.**
- `core/lx_cognates.py` `lx_Integrate.execute` — alongside the existing `commit_success_vector` call, also call `commit_env_snapshot(state["env_audit"], state["observation_embedding"], outcome.tool_name, reward)` when reward clears the threshold. Both commits gated on the same threshold so the datasets stay in lockstep.

**3d. lx_Reason consumes env_snapshots.**
- `core/lx_cognates.py` `lx_Reason._exploit` — the cold-start branch becomes:
  1. Try `procedural_wins` semantic NN at the 0.7 floor (existing behavior).
  2. On miss, try `env_snapshots` at the 0.6 floor — pull `(tool_name, reward, similarity)` tuples and blend `score = reward × similarity` per neighbor, aggregate by tool_name (max score per tool), use as the cold-start exploit bias.
  3. On double-miss, return a neutral signal — no exploit bias, ε-greedy explores uniformly.

**3e. Delete the heuristic.**
- `core/lx_cognates.py` — delete `lx_Reason._observation_signal(state)` method and the `_COLD_START_LOOKUP` module-level table. Any test that imports the symbols updates accordingly. The `_prior_audit_snapshot` field on `ServoCore` survives because `lx_Integrate` still writes it for diff-based logging; if no Phase H+ consumer materializes it can be deleted in Phase H.

**3f. ConfigRegistry default.**
- `codex/manifests/config.json` (or `_DEFAULTS` in `core/config_registry.py`) — add `env_snapshot_similarity_floor: 0.6`.

**3g. Bench fixture.**
- `benchmark/criteria/lx_correctness.py` or a new fixture file — add a synthetic `env_snapshots` row before the handshake test so any test exercising `_exploit`'s cold-start path has at least one neighbor available. The current handshake test halts on OBSERVE→REASON so it doesn't yet exercise this; if Phase H adds a deeper end-to-end test the fixture will be in place.

**Acceptance.**
- `python -m benchmark.lx_audit_manager` returns `Overall Pass: True` after the rewrite.
- `lx_Reason._observation_signal` and `_COLD_START_LOOKUP` are absent from `lx_cognates.py`.
- `lx_StateStore.commit_env_snapshot` and `lx_StateStore.query_env_snapshots` exist and round-trip a synthetic snapshot in a unit test.
- Cognate boot under a fresh profile (empty `procedural_wins` + empty `env_snapshots`) doesn't crash; `_exploit` returns a neutral signal and ε-greedy takes over.

### Step 4 — Audit + ADRs + v1.8.0 landing

**4a. Final audit.** Run `python -m benchmark.lx_audit_manager` end-to-end. Confirm `Overall Pass: True`. Capture the audit JSON timestamp for the v1.8.0 history entry.

**4b. ADRs.** Append to `codex/manifests/decisions.md`:
- **D-20260427-01 — ServoCoreThread wiring hotfix (lx_StateStore construction).** Records the Phase F miss where ServoCoreThread passed the legacy `core.state.StateStore` into `ServoCore.run_cycle` instead of constructing an `lx_StateStore`. Fix landed during Phase G boot triage.
- **D-20260427-02 — lx_correctness audit handshake updated for park/wake gate.** Records the Phase F regression where `test_core_loop_handshake` hung indefinitely because OBSERVE was now a park/wake gate and the test never submitted a perception. Fix: feed a synthetic `user_input` perception before `run_cycle`, halt on OBSERVE→REASON transition rather than REASON→ACT.
- **D-20260428-01 — Phase G: legacy retirement, GUI cleanup, cold-start replacement.** Documents the deletion of `core/loop.py` + `core/lx_loop_shim.py`, lifts the No-Write invariant, the four-cognate GUI display, the dropdown restyle, the trace-section removal, the env_audit similarity-based cold-start branch (full replacement), and the Phase H+ backlog.

**4c. History entry.** Prepend to `codex/manifests/history.md`:
- **v1.8.0 — (2026-04-XX) Phase G: Legacy Retirement & Cold-Start Replacement** — covers Steps 1-3 deliverables, the audit gate-of-record, and the Phase H+ backlog.

**4d. Manifest bumps.** `codex/manifest.json` and `codex/manifest_compact.json` `"version"` field bumped from `"1.7.0"` to `"1.8.0"`.

**Acceptance.**
- All three ADRs land with full Context / Decision / Consequences sections.
- v1.8.0 history entry exists with a Phase H+ Handoff section listing the postponed work.
- Manifest pair shows 1.8.0.
- `python -m benchmark.lx_audit_manager` green at landing.

## Phase H+ Backlog (recorded, not built)

These are formally postponed in Phase G's ADR D-20260428-01 and the v1.8.0 history's "Phase H Handoff" section:

- **Telemetry-driven config tuning** — `ConfigRegistry.maybe_reload()` becomes the substrate; a tuning loop reads telemetry (drift volume, reward distribution, NN hit-rate) and writes back to `config.json` so the registry's hot-reload picks up the new values. Out of scope for G.
- **Multi-listener `response_ready_hook` fanout** — currently single-callable. If a Servo mirror / observer pane lands, the hook becomes a list. Out of scope until that consumer exists.
- **Cross-cycle event bus** — replaces the ACT-writes-`pending_tool_output` convention if a third perception producer materializes (background timer, scheduled task). Out of scope until a third producer exists.
- **GUI manual controls** — Single Cycle, Reload Config Now, Clear Perception Queue, Reset Profile State, Dump Current State, Reset Turns DB. Phase G ships none of these per Kevin's "none for now" decision; reconsider in Phase H based on actual debugging friction.
- **`_prior_audit_snapshot` cleanup** — the field survives Phase G as the diff-based logging substrate; if no Phase H+ consumer materializes it can be deleted.
- **Bench fixture for cognate end-to-end test** — Phase F mentioned a deterministic Ollama fixture for the audit's correctness suite. The Phase G handshake test halts on OBSERVE→REASON so it dodges the issue, but a deeper end-to-end test would need the fixture in place first.

## Risk register

- **Cold-start regression on fresh installs.** Until `env_snapshots` accumulates rows, the cognate operates on neutral ε-greedy exploration. This is a transient bootstrap window (typically the first 5-20 cycles) where cognate behavior is more random than under the Phase E heuristic. Mitigation: the audit's correctness suite halts before `_exploit` runs, so this doesn't break the gate. Real-world cognate boot may feel less directed for the first dozen cycles after upgrade.
- **No-Write lift propagation.** Other ADRs and UPGRADE_PLAN documents reference No-Write as a live invariant. The scrub touches forward-looking references only; historical decisions keep their "preserved under No-Write" prose to remain truthful about state-at-decision-time.
- **GUI signal teardown.** Removing the trace-section listener while keeping the `trace_event` signal alive risks orphaned emits. Cheap operationally (Qt handles emit-with-no-listener cleanly), but worth noting.

## Acceptance summary (all four steps)

1. `core/loop.py` and `core/lx_loop_shim.py` are absent from the repo.
2. Loop-state GUI panel shows four cognates in correct order with active-step highlight.
3. INSTALLED TOOLS dropdown matches Stream Viewer / Log Viewer idiom.
4. Trace section below loop state is gone; `trace_event` signal still defined.
5. `lx_Reason._observation_signal` and `_COLD_START_LOOKUP` are absent.
6. `lx_StateStore` exposes `commit_env_snapshot` / `query_env_snapshots`.
7. `lx_Integrate` writes env_snapshots on successful commits.
8. `python -m benchmark.lx_audit_manager` returns `Overall Pass: True`.
9. v1.8.0 history entry + three ADRs + manifest bumps land in `codex/`.
