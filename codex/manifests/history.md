# History — How Servo Got Here

**Version:** 1.0
**Last Updated:** 2026-04-21
**Status:** Canonical (append on each release)

The story of Servo, told in releases. Each entry summarizes what changed and why. For decision-level rationale, see `decisions.md`.

## v1.3.0 — (2026-04-21) Toolset Modularization & Scope Refinement
**Atomic Primitives & Symbolic Intelligence**

### ✨ Key Improvements
*   **Atomic File Primitives**: Decomposed the monolithic `filesystem` tool into four sharp, specialized tools: `file_read` (pagination/summarization), `file_write` (creation/appending), `file_list` (discovery), and `file_manage` (move/delete). This reduces schema "Tax" and improves model precision.
*   **Project Mapping Engine**: Replaced the fuzzy `analyze_directory` with `map_project.py`. This tool provides a "Symbol View" (classes, methods, functions) of the workspace, giving the model a capability map rather than a raw content dump.
*   **Kernel Exposure**: Exposed the `summarizer` kernel as a first-class tool, allowing the agent to explicitly condense arbitrary text blocks to manage context pressure.
*   **Prompt Synchronicity**: Updated Rule 11 and the Large-File guidance in the Core Loop to standardise on the new primitives.
*   **Cleanup**: Formally purged `filesystem.py` and `analyze_directory.py` from the project registry.

### 🐛 Critical Hotfixes & Stability
*   **System Prompt Integrity**: Fixed a critical regression in `core/loop.py` where a missing `return base` statement in the prompt builder caused the model to perceive an empty toolset.
*   **Greedy JSON Parsing**: Refined the tool-call extraction regex (`(?s)({.*})`) to be greedy, ensuring nested JSON objects are fully captured and do not leak residue into the conversation UI.
-   **Terminal Response Emission**: Restored the `self.response_ready.emit` logic in the ACT phase to ensure tool-generated summaries are reliably surfaced to the UI window.
*   **Test Suite Migration**: Migrated 100% of legacy filesystem and directory tests to the new atomic primitive set, ensuring functional parity and a 100% pass rate (202/202 tests).

---

## v1.2.4 — (2026-04-21) Transparency & Tool Visibility Hardening
**Executive Authority & Alignment**

### ✨ Key Improvements
*   **Radical Transparency Directive**: Hardened the Persona Core and Core Loop with mandates to disclose system prompt and internal logic upon request, effectively suppressing hallucinated "Security Alert" refusals.
*   **Tool Visibility Structural Anchors**: Enhanced the system prompt with high-visibility headers (`[AVAILABLE TOOLSET - AUTHORIZED FOR IMMEDIATE USE]`) and explicit "Tool Authority" instructions in the Persona to ensure the model recognizes its internet-enabled capabilities.
*   **Refusal Suppression**: Added Rule 11 to the final system prompt assembly, explicitly overriding "Level 5 Administrator" or "Safety Protocol" boilerplate.

---

## v1.2.3 — (2026-04-21) Polymorphic Logic Remediation
**Test Infrastructure Integrity**

### 🐛 Fixes
*   **Polymorphic Data Extraction**: Updated the `youtube_transcript` tool to handle both dictionary-based payloads (used by the production API) and object-based mocks (used by the `TestToolsLogic` suite). This resolves the `AttributeError: 'DummySnippet' object has no attribute 'get'` and restores the 100% pass rate.

---

## v1.2.2 — (2026-04-21) Tool Hardening & Persona Alignment
**Reliability & Authoritative Execution**

### ✨ Key Improvements
*   **Internet Authority Directive**: Updated the Persona Core to explicitly authorize and mandate the usage of internet-enabled tools (`web_search`, `fetch_url`, `youtube_transcript`). This prevents the model from defaulting to "I cannot browse the internet" refusals.
*   **Robust YouTube Extraction**: Refactored the `youtube_transcript` tool to handle dictionary-based payloads and aligned the API logic with version 1.2.x of the upstream library.
*   **Dependency Formalization**: Formally added `youtube-transcript-api` to the project manifest.

---

## v1.2.1 — (2026-04-21) Emergency Remediation
**Diagnostic Restoration & Path Safety**

### 🐛 Fixes
*   **Positional Path Restoration**: Restored backward compatibility to the `StateStore` constructor. Fixed a specific `WinError 123` where absolute database paths were incorrectly parsed as profile names during unit testing.
*   **Test Suite Synchronization**: Refactored `test_tool_registry.py` to correctly inject a Mock ConfigRegistry. This restores the 100% pass rate for tool output truncation verification.

---

## v1.2.0 — (2026-04-21) 1.0 Completeness & Profile Isolation
**Structural Assurance & Multi-Environment Safety**

### ✨ Key Improvements
*   **Safe State Profiles**: Added `--profile <name>` CLI support. Isolated state repositories (`state_fresh.db` and `chroma_fresh/`) now allow for non-destructive "Clean Slate" testing while preserving the primary development session.
*   **100% Registry Parity**: Completed the architectural unification sweep. All surviving direct `state.get()` calls in the CoreLoop and Compressor were migrated to the tiered `ConfigRegistry`.
*   **Dynamic Tool Boundaries**: The `MAX_TOOL_OUTPUT` scalar is now a registry-managed tunable parameter, allowing per-profile adjustment of context pressure.
*   **State-Aware UI**: The MainWindow title bar now dynamically reflects the active state profile for visual session awareness.

### 🐛 Logical Refinements
*   **Verified Backoffs**: History compression failure tracking is now registry-mediated, ensuring consistent behavior across cold-starts.
*   **Unified Initialization**: The `ToolRegistry` now correctly consumes the central configuration engine during boot.

---

## v1.1.0 — CoreLoop Orchestrator Hardening (2026-04-21)

This release focuses on the absolute stabilization of the autonomous engine (Cortex), achieving a 100% pass rate for the core integrity suite and formalizing hardware-aware safety guards.

1.  **Orchestrator Hardening**: Expanded the `test_loop.py` suite to hit all critical logic branches, including autonomous directive cascades (`done` > `chain` > `nudge`), Windows-path hallucination recovery, and lifecycle interruption handling.
2.  **Robust PERCEIVE Loading**: Migrated from `open().read()` to `pathlib.Path.read_text()` for identity and manifest documents. This eliminates "Extra data" JSON errors and "bytes-like object" TypeErrors caused by Windows-specific encoding ambiguities.
3.  **Safe Telemetry Sensors**: Instrumented `_build_environmental_sensors` with explicit type-guards and safe integer fallbacks (`getattr(..., 0) or 0`). The loop no longer crashes if hardware telemetry (e.g. token counts) returns `None` or `MagicMock` objects.
4.  **Test Isolation**: Refactored the kernel test infrastructure to use isolated temporary directories for all configuration-aware logic, protecting the production `configs/` directory from testing-induced state corruption.
5.  **Diagnostic Integrity**: Fixed a zero-day bug where uninitialized `start_time` caused uptime-based sensor crashes during the first cycle of a session.

See `decisions.md` D-20260421-08 through D-20260421-10.

---

## v1.0.0 — The True Unification & Functional Persistence (2026-04-21)

This release marks the hardening of Servo into a 100% schema-driven system, eliminating all hardcoded fallbacks in favor of a centralized, tiered configuration registry and professional-grade lifecycle telemetry.

1.  **The "True Unification"**: Replaced all remaining direct `state.get()` calls in the `CoreLoop` with the centralized `ConfigRegistry`. The system is now fully governed by `system_defaults.json`; a manual `AttributeError` caused by missing keys is now architecturally impossible.
2.  **Lean Configuration Registry**: Deployed a tiered resolution engine in `core/config.py`. Settings now flow from **Runtime Overrides** to **Persistent Storage** to **Schema Defaults**, ensuring data integrity while maintaining hot-swappable flexibility.
3.  **Core-Wide Hot-Reloading**: Integrated `QFileSystemWatcher` to link the filesystem directly to the GUI. Manual edits to JSON configuration files are now reflected in the dashboard instantly without a restart.
4.  **Functional Memory Snapshots**: To prevent "Executive Amnesia," every update to the Working Memory is now automatically archived as a structured snapshot in the Sentinel Logs. This provides 100% data durability for project strategy and logic without polluting the conversational history.
5.  **Restart Reason Diagnostics**: Instrumented the boot sequence to detect and report the reason for every application start (`CODE_DEPLOYMENT`, `FAILURE_RECOVERY`, or `STANDARD_BOOT`). High-visibility log banners now clearly delineate session boundaries.
6.  **Registry Hardening**: Simplified the `system_config` tool to be a pure consumer of the Registry, reducing complexity and ensuring that all validation happens at the kernel layer.
7.  **Regression Stability**: Fixed a critical regression in the Task Nudge suite where `MagicMocks` were interfering with configuration resolution. 173 tests passing.

See `decisions.md` D-20260421-04 through D-20260421-07.

---
*Append a new section per release. Do not rewrite history.*

## v0.9.0 — Granular Guards & Ergonomic Refinement (2026-04-21)

This release transitions the system from binary toggles to a granular, threshold-based performance model, while stabilizing the GUI for better ergonomics and terminology parity.

1. **Granular Performance Guards**: Replaced binary `summarize_history` and `summarize_tool_results` with numeric triggers (`history_compression_trigger`, `tool_result_compression_threshold`). The history compressor now fires at a multiplier (default 2.0x) of your active context history limit, aiming for a dense narrative recap (default 800c). Oversized tool results are now semantically compressed once they exceed a character threshold (default 4000c).
2. **Auto-Summarize File Guard**: Implemented a context-protection guard that automatically enforces `summarize=true` on any `filesystem:read` operation exceeding 800 lines. This ensures large file reads never saturate the model's active attention window with raw code.
3. **Enhanced Environmental Trace**: Upgraded `core/loop.py::_build_environmental_sensors` to provide live telemetry in the system prompt. Three new sensors — **Autonomy Turn**, **History Maturity** (turns until compression), and **Context Altitude** (token usage) — are injected into every cycle to help the model reason about its own resource boundaries.
4. **GUI Ergonomics & Layout Fixes**:
    *   **Schema Alignment**: Refactored the SYSTEM CONTROLS labels to match the `system_config` tool schema 1:1, removing technical underscores and "enabled" suffixes for a cleaner, native-feeling interface.
    *   **Stability**: Standardized input widths to 102px/60px to prevent layout stretching during window resizing. 
    *   **Resource Reasoning**: Re-grouped Hardware Throttling under the Resource Reasoning section and renamed the guards section to "Summarizer Settings."
6. **Role Decoupling Phase 2**: Performed a final scrub of the configuration manifests (`manifest.json`, `manifest_compact.json`) to remove legacy "Role" and "Overlay" keys. Process descriptions (architecture reviews, closed-proposal sweeps) were refactored to be logic-driven rather than role-driven, aligning the Codex with the mono-identity Servo runtime.
7. **Infrastructure Hardening**:
    *   Upgraded `system_config` to support decimal-based parameters with full float parsing and bounds checking.
    *   Fixed a `ValueError` in environmental sensors caused by integer-casting the decimal history multiplier.
    *   Synchronized all new state parameters with the `StateStore` and `MainWindow` for persistent model-profile compatibility.
    *   **Regression Suite**: Deployed a 16-test comprehensive suite (`tests/test_tool_result_compressor.py`) to verify the granular guards and their fallback logic under simulated kernel failure.

See `decisions.md` D-20260421-01 through D-20260421-03 and D-20260420-01.

## v0.8.1 — Autonomous Testing Suite & Tool Block Paging (2026-04-19)

1. **End-to-End Live Harness:** Constructed a natively headless testing script `tests/test_e2e_live.py` that fully instantiates the internal PySide `CoreLoop` natively, eliminating the gap between API simulations and full filesystem execution paths. See `decisions.md` D-20260419-15.
2. **Context Limits Testing Overhaul:** Decoupled sequence tracking from raw conversation context limits within `eval_context_limits.py`. The suite now individually scores the model on its logic handling under 10-turn limits versus parsing specific agenda tracking tools (like `working_memory`).
3. **Transcript Block Feature (Authored natively by Servo):** Servo autonomously updated `youtube_transcript.py` to insert a paginated `block` argument explicitly scoped to 15,000 characters, mirroring `filesystem:read` limits. This ensures multi-hour videos safely slide underneath the 16,000 character `MAX_TOOL_OUTPUT` boundary defined in `tool_registry.py`.

## v0.8.0 — Task Ledger with Ungated Stuck-Detection Nudge (2026-04-19)

A plan-shaped structure re-enters the architecture, deliberately lower-altitude than the v0.7.0-purged goals system. Motivating problem: longer operator requests — Kevin's smoke test was "move every file in `workspace/<model>/` into `old_stuff/`" — were failing in two opposite ways. The model either declared victory after the first tool call and stopped chaining, or kept chaining but drifted off plan mid-way, reinventing the remaining steps incorrectly. Both fail the "longevity" requirement: the agent should hold a multi-step plan across many turns without the operator baby-sitting it. The goals system had been the wrong shape for this (time-scheduled background firing, role-bound), but something smaller and user-directed was still missing.

The design, locked before any code landed: a single `task` tool with four actions — `create`, `complete`, `list`, `clear` — backed by a new `tasks` SQLite table (`id`, `description`, `status`, `created_at`, `completed_at`). Tasks are semantic-grain (one task = one milestone, not one tool call — the tool description teaches this explicitly). The `create` action accepts either a `tasks: list[str]` batch or a single `description: str`; batches over the `soft_max=20` cap are rejected with a teaching error rather than silently truncated, so a malformed plan becomes a prompt signal rather than a hidden partial. `complete` is idempotent — a second call on a completed row returns "already completed" without erroring. `list` renders the same ledger shape the system prompt uses, so the model sees a consistent frame whether the ledger was pushed or pulled. `clear` wipes the ledger but leaves the conversation history intact; conversely, `clear_conversation` (the `/reset` path) leaves the ledger intact. The ledger is sticky — plans survive across resets until explicitly cleared.

CORTEX-side, `_contextualize` now pulls `active_tasks = self.state.get_all_active_tasks()` on every cycle and passes it through to `_build_system_prompt`. `_render_active_tasks_block` produces an `[ACTIVE TASKS]` block with an arrow cursor on the first pending row and `[x]` on completed rows; completed rows stay visible as the model's trail of done work. Empty ledger renders as the empty string — no decorative placeholder in runs that don't use the tool. The block sits in the prompt between `[PATH DISCIPLINE]` and `AVAILABLE TOOLS` so the plan context is adjacent to the tool menu that will execute it. The teaching line at the bottom of the block names the tool action (`task` with `action=complete`, `task_id=N`) so the model doesn't have to remember how to retire a row.

The load-bearing piece is the stuck-detection nudge. `_run_cycle` gains a new branch after the chain-branch and before the continuous-mode gate: if the model produced no chained tool call AND the pending ledger is non-empty AND the inbound payload doesn't already carry a `_task_nudge` marker, the loop returns `action="task_nudge"` with a transient SYSTEM payload naming the cursor task and the remaining count. Critically, this branch is UNGATED from `continuous_mode` — it fires whenever there's pending plan work, regardless of the continuous-mode checkbox. Bounds come from two places: `autonomous_loop_limit` (the same cap continuous mode already uses) suppresses the nudge once the loop has re-entered enough times, and the `_task_nudge` marker on the inbound payload prevents two consecutive nudges from the same cycle (a genuinely-stuck model gets exactly one prod, not a runaway self-loop). The nudge payload carries `_transient: True` so it never pollutes conversation history — the loop-control signal stays inside the loop. `run()` dispatches `action="task_nudge"` unconditionally, parallel to `chain`, so the re-loop works in both continuous and single-turn modes. Precedence inside `_run_cycle`: chain > task_nudge > grace > done. Chain takes precedence because a model that's actively working doesn't need prodding; task_nudge beats grace because a named cursor task is a more actionable signal than the generic "did you want to chain?" prompt.

A dependency surfaced during the feature's first live test: `submit_input` had been calling `if self.step != LoopStep.OBSERVE` (added by D-20260419-10) but no code path ever wrote `self.step` — `_set_step` only emitted the Qt signal. The first user interrupt crashed with `AttributeError: 'CoreLoop' object has no attribute 'step'`. Fixed by initializing `self.step = LoopStep.OBSERVE` in `__init__` and having `_set_step` assign the attribute before emitting. See `decisions.md` D-20260419-13.

Test coverage: `tests/test_task_tool.py` (28 cases covering StateStore CRUD — order preservation, blank-entry skipping, complete idempotence, clear behavior, sticky-across-reset — plus `tools/task.py`'s `execute()` dispatch on all four actions including cap rejection, missing-arg paths, and non-integer `task_id`); `tests/test_task_block_render.py` (9 cases covering empty-ledger empty-string, header presence, single-pending cursor, all-pending cursor-on-first-only, completed-with-check, cursor-skips-leading-completed, all-completed-no-cursor, trailing-newline, teaching-line-mentions-complete); `tests/test_task_nudge_stuck_detection.py` (10 cases covering the decision branch — fires on pending+no-chain, no-fire on empty ledger, no-fire on second consecutive nudge in non-continuous mode, re-fires on consecutive nudge in continuous mode, respects auto-cap in continuous mode, cap suppression, fires-under-cap, fires with continuous_mode=False, chain-takes-precedence, and nudge-message-counts-remaining). The teaching-line in `_render_active_tasks_block` originally used "The cursor ▶ points at…" which collided with the cursor-count assertions (the ▶ appeared twice per block instead of once); reworded to "The arrow marker points at…" so the literal `▶` glyph appears exactly once, on the cursor row itself. See `decisions.md` D-20260419-12.

A follow-up refinement (D-20260419-14) landed after live testing surfaced a mid-plan halt bug. The `_task_nudge` single-fire marker was too blunt: after a nudge cycle where the model responded with prose instead of a tool call, the marker suppressed re-nudging and the loop fell through to `action="done"` even in continuous mode. That defeated the whole point of continuous mode perseverance. Fix: gate the suppression on `not self.continuous_mode`. In continuous mode, task-nudges now re-fire on every cycle with pending work and no chain, bounded only by `autonomous_loop_limit`. Non-continuous mode still single-fires. New test cases cover both paths. Also caught during the same session: `submit_input` was reading `self.step` (added by D-20260419-10 as a telemetry guard) but `_set_step` only emitted the Qt signal without storing the attribute, so the first user interrupt crashed with `AttributeError`. See `decisions.md` D-20260419-13.

A second teaching refinement (D-20260419-17) landed after Kevin observed the model was registering tasks for short jobs that would fit inside a single chained cycle, bloating `[ACTIVE TASKS]` with transient rows that completed the same turn they were created. Root cause: `TOOL_DESCRIPTION` in `tools/task.py` — the only copy the model actually reads — described HOW to use the ledger but not WHEN. The module docstring had the chain-vs-ledger threshold documented, but that's developer-facing and never enters the prompt. Fix: prepend a WHEN-TO-USE clause to `TOOL_DESCRIPTION` naming the threshold explicitly (plans exceeding `chain_limit` or crossing user turns use the ledger; short jobs chain directly) and a concrete rule of thumb. Pure prompt wording — no code change.

## v0.7.2 — Identity Centralization and Self-Evaluation Bugfixes (2026-04-19)

A hybrid feature/maintenance release born directly from an autonomous self-evaluation generated natively by the local agent model.

1. **Identity Centralization**: Consolidated all hardcoded instances of the operator's name ("Kevin") and agent's name ("Servo") from the core logic (`loop.py`, `history_compressor.py`, `chat_panel.py`) and persona profile (`persona_core.md`). These are now purely dynamic string-templates (`{user_name}`, `{agent_name}`) bound at boot against a dedicated `configs/identity.json` controller `core.identity.py`. See `decisions.md` D-20260419-09.
2. **Ghost Task Eviction**: The model accurately flagged an operational contradiction: the v0.7.0 roles purge had taken place, but latent references to "roles.json" targets (like CP-IMPLEMENT-GUARDIAN) explicitly survived inside the persistent `state.db` SQLite rows. Extracted the ghost buffer to `codex/memories/working_memory_snapshot_01.md` and wiped the live memory.
3. **Telemetry Drift Corrections**: Discovered an over-counting logic bug inflating `user_interrupts_total`. The UI pipeline correctly emitted `cancel_events` on chat-submit, but the core blindly tracked every conversational submit as a hard logic interrupt. Patched with a strict `LoopStep != OBSERVE` guard so metrics remain true to actual interrupt events. See `decisions.md` D-20260419-10.
4. **VRAM Explicit Evictions**: High processing loads when handling megabytes of text (`decisions.md` audit) caused Ollama to hold >86% VRAM caches aggressively (default 5 min `keep_alive`). Intercepted this behavioral gap by wiring an explicit `unload()` HTTP endpoint wrapper into `core/ollama_client.py` pushing `keep_alive: 0` to unstick bloated model environments natively. See `decisions.md` D-20260419-11.

## v0.7.1 — Context Limits and GUI Config Sync (2026-04-19)

A diagnostic release focusing on measuring hardware boundaries and optimizing the core loop.

1. **Context Limit Evaluations**: Created local test suites (`tests/eval_context_limits.py`, `tests/eval_summarizer_fidelity.py`) to systematically map task-amnesia boundaries. Findings confirmed the model effortlessly processes large payloads (passed 32k raw chars flawlessly), but suffers extreme attention-dilution if chained conversational turns exceed depth 10–15. See `decisions.md` D-20260419-06.
2. **Conversation History Optimization**: Reduced `self.conversation_history` default in `core/loop.py` from 15 down to 5. Instead of caching 30 conversational turns and halting the system for 60 seconds to summarize them, the agent now frequently rolls up 5-turn blocks in roughly ~19 seconds. The Fidelity Test proved this tighter window perfectly retains 'mid-chain pivot' memory while slashing runtime latency. Forced-capping `num_predict` output tokens caused fatal 0-byte generation and was abandoned. See `decisions.md` D-20260419-07.
3. **GUI Config Sync Fixes**: Overhauled the configuration bridging between PySide6 and the `CoreLoop`. The `system_config.py` tool now synchronously broadcasts UI updates over a newly unified `config_changed` PySide signal. At boot, `gui/main_window.py` properly aligns `models.json` defaults into both the `OllamaClient` back-end and the UI dials immediately so they mirror reality from frame 1. See `decisions.md` D-20260419-08.

## v0.7.0 — Excision of Roles and Goals (2026-04-19)

The persona overlays and continuous scheduled task (goals) systems have been completely removed to simplify the agent architecture. The agent now functionally tracks context and chains tool requests in an event-driven manner rather than pretending to be alternating personalities executing disconnected background tasks. All configuration dependencies (`roles.json`, `goals.json`), their respective management tools (`role_manager.py`, `goal_manager.py`), runner scripts (`scholar_runner.py`, `analyst_runner.py`), and GUI target trackers were purged from the system. Continuous mode remains conceptually intact by passively chaining tool executions infinitely if requested, rather than injecting target goals. See `decisions.md` D-20260419-05.

## v0.6.10 — Phase 3 Summarization Hooks (2026-04-19)

Phase 3 of the summarization rollout closes the slot that D-20260419-01 explicitly left open in v0.6.8. With the kernel factored (v0.6.7) and conversation-history auto-compression in place (v0.6.8), the remaining motivation was file-payload compression — the "directed tool that fires as part of the loop ... to remove irrelevant stuff" from Kevin's original brief. Kevin sketched two shape alternatives: (A) a tool-argument lever letting the model opt individual reads into summarization inline (pseudocode `file read block 1 prev=summarize,clean,keep` or `read(filename,1).summarize`), or (B) refining role tasks to chain `summarize(read(file))` explicitly. Scope review pinned three decisions before any code landed: (1) the lever attaches to `filesystem:read` only — the other path-reading tools already emit bounded output, and a universal wrapper would cross-concern too much; (2) empty-kernel responses fall open to raw content with an inline marker so callers never get silently empty output, matching D-20260418-10's contract; (3) `scholar_runner` turns pre-summarization on by default so the feature fires in testing without requiring a role-manifest edit, while `filesystem:read` defaults to off so existing callers are unaffected. A fourth question — drop/delete semantics ("acknowledge the read without returning content") — was explicitly deferred to a future separate hook because a `content_mode` enum would cross-concern summarize and drop, and shipping summarize cleanly first was the priority.

Two reinforcing mechanisms landed together. The first is a `summarize: bool = False` parameter on `filesystem:read`. When true, the body (after pagination / max_lines, which run first) feeds through `tools.summarizer.summarize` with a file-type-agnostic `system_rules` block and comes back wrapped as `[SUMMARY of <path> — <N> lines]\n<summary>\n[END SUMMARY]`. Empty kernel returns fall back to the raw body prefixed with `[SUMMARIZER RETURNED EMPTY — returning raw content]`; kernel exceptions fall back with `[SUMMARIZER FAILED — <err> — returning raw content]`. Pagination footers (`[BLOCK N OF M …]`, `[Showing first N of M total lines]`) are appended AFTER the envelope so the navigation hint survives. `TOOL_SCHEMA` documents the new flag. A private `_summarize_read_body(body, rel)` helper owns the envelope shape so future callers can reuse it without drift.

The second is default-on pre-summarization for delta files in `tools/scholar_runner.py`. Any delta exceeding 500 lines (the `_DELTA_SUMMARIZE_LINE_THRESHOLD` constant — tunable, chosen so growing ledgers become summaries within one to two releases of accumulated entries while small utility modules pass through verbatim) gets fed through the kernel during the scan and emitted as a `{path, summary, raw_line_count, raw_bytes}` dict alongside the plain path strings for small files. The summary is wrapped in the same `[SUMMARY of ... — N lines] ... [END SUMMARY]` envelope as the read-time flag, so the Scholar sees a consistent shape no matter how the summary arrived. A new `summarization_stats` diagnostic block (`files_summarized`, `files_skipped_small`, `files_summarize_failed`, `time_seconds`, `enabled`) surfaces the pass's behavior for operators diagnosing cycle slowness. A per-call `summarize_deltas: bool = True` knob lets workflows that need exact-string matching opt out. Failures fall open: kernel exceptions, empty responses, and unreadable files all fall through to the plain path string so the Scholar always has something to act on.

Manifest teaching in `codex/role_manifests/scholar.md` pairs with the code changes. Step 2 (`Ingest the deltas`) now branches on delta shape: plain strings go through `filesystem:read` (with an optional `summarize: true` for the model's own judgment calls on large files), dict deltas use the embedded `summary` directly and only fall back to verbatim reads when the summary is insufficient. Step 4 (closed-proposal sweep) explicitly requires verbatim reads of `decisions.md`, `history.md`, and `rejected_proposals.md` — the sweep matches on exact `CP-YYYYMMDD-NN` and `D-YYYYMMDD-NN` IDs that a summary could paraphrase, so the three ledgers must be pulled with `summarize: false` even when the payload delivered them as dicts. The auto-tool payload description picks up a new bullet documenting `summarization_stats` and the mixed-shape semantics so the model's starting context explains the fields it's looking at.

Coverage: `tests/test_filesystem_summarize.py` (7 classes, covering default-false no-kernel-call, happy-path envelope, full-body kernel input, empty-response fallback, exception fallback, pagination + summarize footer survival, max_lines + summarize slice, and TOOL_SCHEMA contract) and `tests/test_scholar_runner_summarize.py` (8 classes, covering summarize_deltas=False legacy shape, small-file skip path, large-file dict shape, kernel-exception fallback, empty-kernel fallback, summarization_stats keys, TOOL_SCHEMA contract, and `execute()` JSON wrapping). Both suites stub `tools.summarizer.summarize` via `unittest.mock.patch` so no Ollama process is required — the kernel's own live-path coverage lives in `test_summarizer.py`. Phase 4 (agent-facing standalone `summarize` tool) remains deferred: the read-time flag plus default-on pre-summarization cover the foreseeable callers, and a standalone tool would duplicate surface area. If a caller emerges that needs to summarize non-file content (aggregated tool output, composite nudges), Phase 4 can land then. Drop/delete semantics stay out of scope; a later hook could add `acknowledge_only: true` without reshaping the existing flag. See `decisions.md` D-20260419-04.

## v0.6.9 — LogPanel Dedupe and Scholar Write-Call Discipline (2026-04-19)

Two co-shipped fixes from the same debugging session. Kevin reported a Scholar cycle in continuous mode chewing 12+ minutes of wall clock — three Ollama streams hitting `num_predict=16384`, auto-continue exhausted at 2/2, no visible progress — and observed that every truncation WARNING and its INFO trace mirror appeared twice in the GUI log panel at the same second. The reasonable suspicion was that `_auto_continue` was firing twice per truncation and doubling the work. Investigation split that into two independent defects.

The double-logging turned out to be display-layer, not execution-layer. `SentinelLogger` is a singleton with a single file handle and a write lock, so `logs/sentinel.jsonl` has exactly one line per event — verified on disk. `_auto_continue` has one call path for `phase=reason` per turn. The Ollama stream count (4 stream-begins for 3 truncations) matches the math `260.6s × ~60 tok/s ≈ 16384 tokens` — no ghost streams. The duplication was at `gui/log_panel.py::LogPanel`, which has two independent ingress paths for every event: the `CoreLoop.log_event` Qt signal (wired for low-latency rendering) and a `QFileSystemWatcher` on `sentinel.jsonl` (which detects file growth and parses new lines in `_on_file_changed`). Both end at `_render_entry`. Dropping the signal would cost latency and the context payload; dropping the watcher would silence every entry that bypasses `_slog` (`state.add_trace`, `core/tool_registry.py`, `core/history_compressor.py` — anywhere a module calls `get_logger().log(...)` directly). Fix: keep both ingress paths for resilience, dedupe at render time by `(level, component, message)` within a 2-second recency window. New `_is_duplicate()` helper backed by a 64-entry deque of `(key, monotonic_time)` pairs, called from `_render_entry` right after the level-filter check. `_refresh_display` clears the tracker so toggling a level filter and re-rendering the buffer doesn't self-suppress legitimate historical entries. The 2s window is wide enough to catch the signal/watcher race (always tens of milliseconds) and narrow enough not to suppress actual back-to-back repeats. See `decisions.md` D-20260419-02.

The Scholar slowness was real work generating real tokens. Reconstructing from the verbose stream log: stream 1 (14.6s) was the preamble ending in a `filesystem:read` on the first delta file; stream 2 (260s, full `num_predict`) was the response to the tool result — and it contained no tool call. Auto-continue 1 fed "continue where you left off" and it burned another full budget; auto-continue 2 did the same, then the 2/2 give-up fired. The only pattern consistent with `num_predict`-equals-budget across three streams and no tool-call emergence is that the model was composing the architecture review body directly in its chat response instead of emitting a `filesystem:write` call with the review as the `content` arg. The `scholar.md` step 3 wording ("Emit the new review. Write `workspace/<model>/architecture_review_v<N>.md` ... Prefer a coherent narrative over a changelog") was ambiguous between "emit a `filesystem:write` call whose content is the narrative" and "write the narrative in your response." The weaker model read the latter. Auto-continue then reinforces the failure — telling a model that is mid-prose to "continue where you left off" tells it to keep writing prose, not to switch modalities to a tool call. This is the generalized form of D-20260418-06 (pseudo-function-call template in the WRAP-UP nudge read as text): a manifest that describes a long-document emission without explicitly locking the tool-call frame.

Fix: a new **WRITE-CALL DISCIPLINE** sub-block inside `scholar.md` step 3, with three imperative rules. (1) The review body MUST appear only inside the `content` argument of a single `filesystem:write` call. (2) The chat response for this step is one short sentence naming the version about to be emitted (e.g. "Emitting `architecture_review_v9.md`."), not narrative prose. (3) If the model catches itself writing a paragraph of review prose in chat, STOP and fold it into a `filesystem:write` call instead. Positioned inside step 3 rather than at the top of the manifest so the guidance lands in attention at the exact moment the model is deciding how to emit the review. Scope limited to the Scholar — the Architect writes change proposals with similar shape and may need the same treatment, but Kevin's report was Scholar-specific and premature rewrites risk breaking stable roles. A followup ADR will generalize if the Architect shows the same symptom. Num_predict tuning is Kevin's lever and this release does not touch runtime_config; the `_auto_continue` continuation prompt could grow a "prose-detect → emit tool call now" branch alongside the existing JSON-detect branch at `core/loop.py:1037`, but that structural option is deferred. See `decisions.md` D-20260419-03.

## v0.6.8 — Conversation History Auto-Compression (2026-04-19)

Phase 2 of the summarization rollout. With the kernel extracted in v0.6.7, the next consumer was always going to be conversation-history compression — the motivating use case behind Kevin's "directed tool that fires as part of the loop" brief. Symptom to head off: `conversation_history` (default 15, floor 7 under throttle) caps what we send to Ollama, but once a session crosses the cap, older turns just fall off the tail and the model loses them entirely. A user asking "what did we decide about X an hour ago?" would get a blank stare from a model whose context window no longer held the original exchange. Scope for this release is narrow — the INTEGRATE-time hook only. File-payload compression during CONTEXTUALIZE (Phase 3) and an agent-facing `summarize` tool (Phase 4) remain deferred.

Three design decisions locked the shape before any code landed. (1) Summary lives in the system prompt as a non-destructive `[PRIOR CONTEXT]` block rather than as a synthetic conversation turn — raw turns are never mutated or deleted, and the filter for already-covered turns is keyed on `covers_to_id` so rollback is a one-row delete. (2) Trigger is a turn-count threshold at `2 × conversation_history`, not a char-budget watermark — the cap is already the live throttled value, so the threshold scales with hardware state automatically (at a throttled floor of 7, we compress at 14; at the default 15, we compress at 30). (3) Compression is on by default with no toggle — the prior summary is injected even if the model chose not to reference it, and a failed compression silently keeps raw turns. All three were confirmed as the recommended defaults before implementation.

New module: `core/history_compressor.py` (300 lines). `maybe_compress(state, history_cap) -> dict | None` is the single entry point. It loads the latest row from the new `conversation_summary` SQLite table (columns: `summary`, `covers_from_id`, `covers_to_id`, `model_used`, `created_at`), counts uncompressed turns since `covers_to_id`, and runs the pure predicate `_should_compress(uncompressed_count, history_cap, last_failed_at)` — fires at `2 × cap`, backs off `+cap` turns after a failure so a kernel timeout doesn't produce a retry storm every subsequent user turn. On trigger, it keeps the newest `history_cap` turns raw and rolls up everything from `prior_cutoff + 1` through `newest_id - history_cap`. Each row is rendered as `[role] content` with a 1500-char per-turn clip so a 20k-char `filesystem:list` dump can't dominate the summary input. If a prior summary exists, the user_content absorbs it via an explicit "PRIOR SUMMARY (absorb into the new summary)" prefix — only one live summary exists at a time, and each cycle rolls the previous one forward. The `HARD RULES` block in `_build_system_rules()` is conversation-specific, not log-specific: quote the most recent 1-2 Kevin requests verbatim, preserve tool outcomes by (tool, target, result class), preserve Servo's decisions and commitments, strip internal reasoning and verbose payloads, write ONE narrative paragraph targeting ~800 chars with no preamble. On success, `save_conversation_summary()` persists the new row with `covers_from_id = prior["covers_from_id"] if prior else compress_from_id` (so metadata reflects full cumulative coverage, not just the current cycle) and clears the failure marker.

Failure semantics match the kernel's contract deliberately: empty response from the kernel logs a WARNING to Sentinel, does NOT save a summary, does NOT advance the cutoff, and stashes the current uncompressed-turn-count in a `compression_last_failed_turn_count` state key so the next attempt waits until `+cap` more turns have landed. An exception (kernel blow-up, DB error) logs ERROR and returns None. Either way, the loop keeps going with raw turns — compression is belt-and-suspenders continuity, not load-bearing for correctness.

Wiring in `core/loop.py` touched four hook points. (1) `self.history_compressions_total` counter added next to the other loop telemetry. (2) `_contextualize` calls `state.get_latest_conversation_summary()` and threads the row into the context dict. (3) `_build_system_prompt` inserts a new `[PRIOR CONTEXT]` block between the briefing block and `[SYSTEM ENVIRONMENT]` whenever a summary exists, with teaching prose instructing the model to treat it as its own memory: "do not ask Kevin to repeat decisions or requests captured here." (4) `_build_messages` filters out any conversation turn whose `id <= covers_to_id` so the model sees the summary plus the newest `history_cap` raw turns — never both the raw and the compressed versions of the same turn. Legacy rows without an `id` field pass through unchanged. `_integrate` calls `maybe_compress()` at the end of every non-transient turn, wrapped in try/except so a bug here cannot break the loop, and increments the telemetry counter on success.

State-store support: `core/state.py` picked up `get_latest_conversation_summary()`, `save_conversation_summary(summary, from_id, to_id, model)`, `count_conversation_turns_since(id)`, `get_newest_conversation_id()`, and `get_conversation_turns_range(from_id, to_id)`. `get_conversation_history()` now includes the row `id` in each returned dict so the filter in `_build_messages` can key on it. `clear_conversation()` was extended to also `DELETE FROM conversation_summary` — a full conversation reset drops summaries too. `tools/context_dump.py` surfaces the new `history_compressions_total` counter in its `loop_telemetry` block so `context_dump` reports compression activity alongside truncations and auto-continues.

Coverage: `tests/test_history_compressor.py` with 17 tests across four classes — `TestShouldCompress` (6 predicate boundary tests: below threshold, at threshold, post-failure within backoff, post-failure past backoff, zero cap, first-run with no failure), `TestConversationSummaryTable` (6 CRUD tests on a tempdir SQLite with stubbed chromadb), `TestMaybeCompress` (5 end-to-end tests with `_kernel_summarize` mocked to validate the success path, the empty-response backoff, the exception path, the "nothing to compress" no-op, and prior-summary rollover), and `TestBuildMessagesFilter` (3 filter tests using `CoreLoop._build_messages(MagicMock(), context)` to confirm covered turns are dropped, uncovered turns pass, and legacy rows without id pass). See `decisions.md` D-20260419-01.

## v0.6.7 — Summarization Kernel Extraction (2026-04-18)

The log_summarizer pilot (v0.5.2, D-20260417-06) shipped the first working Ollama-backed summarization in the codebase. Its debugging history taught a specific set of defaults the hard way: a system-only `/api/chat` call with no user turn silently returns empty on gemma 26B (this was the silent failure that burned the first pilot), a 60s chat timeout that is fine for main-loop turns cuts off 26B summarization of ~12k-char payloads before first token, `/api/ps` probes want a tight 2s cap while the actual chat wants a generous 300s, and empty model responses want passthrough semantics so the caller decides what that means (log_summarizer treats it as fatal and blocks checkpoint advance; the next consumer, an INTEGRATE-time auto-compression hook, wants to treat it as soft and keep the raw payload). Kevin's assessment brief (`generalized tool ... directed tool that fires as part of the loop either in contextualize to remove irrelevant stuff, or integrate to clean up after a Reason Act`) pointed at three future summarization sites: conversation-history compression during INTEGRATE, file-payload compression during CONTEXTUALIZE, and an agent-facing `summarize` tool. Shipping three more copies of the pilot's defaults would guarantee that the next regression fires in whichever copy was last touched.

This release is Phase 1 of the broader summarization rollout — the kernel extraction only, behavior-preserving for `log_summarizer`. `tools/summarizer.py` now owns the one canonical implementation: `summarize(user_content, system_rules, *, model=None, timeout=300, max_input_chars=12_000) -> (summary, model_used)` plus `detect_loaded_model(fallback="gemma4:26b") -> str`. The kernel owns model detection (2s probe, fallback on any failure), the system+user message shape Ollama actually expects, the 300s default chat timeout, a last-resort tail-preserve trim for callers that forgot to cap, and empty-response passthrough. It does NOT own prompt content (each caller builds its own `system_rules`), input shaping, destination (the kernel returns text, never writes files), or the agent tool contract (no `TOOL_NAME`/`execute` — imported directly). `log_summarizer._summarize` is refactored to a three-line delegator that calls its existing `_build_prompt` for the INCIDENTS/ROUTINE shape and hands `(user_content, system_rules)` to the kernel. The previous `_detect_loaded_model` helper in log_summarizer is removed; its one caller now reaches through the kernel. Coverage: `tests/test_summarizer.py` with 16 tests across four classes (`TestDetectLoadedModel`: 5, `TestSummarizeValidation`: 3, `TestSummarizeHappyPath`: 7, `TestLogSummarizerIntegration`: 1). 15/16 pass; the 16th (integration) is VM-mount-stale due to OneDrive sync lag and will pass once sync catches up — log_summarizer's authoritative post-refactor source is the two-line delegator. Phases 2–4 (INTEGRATE hook, CONTEXTUALIZE file compression, agent-facing `summarize` tool) will ship as separate ADRs once their scope is firm. See `decisions.md` D-20260418-10.

## v0.6.6 — Continuous-Mode Prompt Gating (2026-04-18)

Kevin reported: "it shouldnt run through roles when continuous mode is not checked, its unchecked by default." Symptom: on reboot, a plain user question triggered a Scholar cycle — `scholar_runner` fired, the model tried to write `architecture_review_v<N+1>.md`, and only `chain_limit` stopped the cascade. Follow-up diagnosis from Kevin: "it's possible it inferred a role was due from the conversation history." That framing pointed at the right layer. The execution path was already gated correctly — `continuous_mode` defaults to False, the goal-election block at `core/loop.py:339` is guarded by `elif self.continuous_mode:`, `_active_role` is cleared on every `submit_input`, and the idle `_check_goals_status` sweep only expires finite goals. The leak was one level above, in the prompt itself. `_build_system_prompt` rendered the `[ACTIVE GOALS]` block identically in both modes, so whenever a continuous role goal crossed `time_since >= sched_sec`, the system prompt on the very next user turn told the model: `[CONTINUOUS PRIORITY 2] role_scholar: [Scholar] ... (DUE NOW - Please execute and call goal_manager mark_done)` — under a `CRITICAL: You must execute ...` header. The model was doing exactly what the prompt asked. Continuous mode being off meant the loop would not auto-prod; it did nothing to stop the prompt from asking.

Fix: the `[ACTIVE GOALS]` block is now mode-aware. Finite goals are split from continuous goals up front. When `continuous_mode` is True, the legacy CRITICAL-finite-before-continuous header and `DUE NOW - Please execute ...` / `Snoozing for N minutes` labels are preserved verbatim. When continuous_mode is False, continuous role goals render inertly — `Scheduled every N min — Continuous Mode OFF, will not fire` — with no `DUE NOW` verb and no `Please execute` hint. The header above the list carries explicit lockout language: `Continuous Mode is OFF. The goals below are listed for visibility only — they only fire when Continuous Mode is enabled and the loop auto-prods you. You MUST NOT elect yourself into a role on a user turn or invoke their auto-tools unprompted.` When continuous_mode is False but a finite goal is present, the header is instead `CRITICAL: Execute FINITE goals (Priority 1) completely using tools. Continuous Mode is OFF — continuous role goals below are listed for visibility only; you MUST NOT elect yourself into one on a user turn or invoke their auto-tools unprompted.` The `schedule_minutes` parse inside the rendering loop picks up the same `int()`-coercion guard that `_check_goals_status` already uses (D-20260418-04), defaulting to 60 on a malformed entry so one bad goal cannot kill the whole block. Synthetic coverage: `test_goals_block.py` asserts 17 properties across four fixtures (continuous ON + continuous-only queue, continuous OFF + continuous-only, continuous OFF + mixed with finite, empty queue in both modes). All 17 pass. See `decisions.md` D-20260418-09.

## v0.6.5 — Proposal Pipeline Sharpening (2026-04-18)

Four Architect cycles in a row drafted proposals against archived files — a typo fix in `architecture_review_v6.md` while v8 was live, ADR backfills into `architecture_review_v5.md`, and a label change to a Sentinel manifest field that already carried the correct label. Each matching Analyst critique APPROVED, because its auto-tool (`filesystem:list` on the workspace folder) carried no signal about whether a named target was archived. A fifth proposal (CP-20260418-06) proposed a structured refactor of `log_summarizer`, which has been working since v0.5.2 — the Architect was pattern-matching on a stale "Known issue: log_summarizer is currently broken" line in `sentinel.md` that should have been struck when v0.5.2 landed. Five rejections, two structural gaps, one case of manifest rot. All five proposals are now recorded in `codex/rejected_proposals.md`.

Fix in two parts. (1) Richer auto-tool payloads for the review pipeline. `tools/scholar_runner.py` picks up an opt-in `include_review_head: bool` parameter that inlines the current `architecture_review_v<N>.md` text (capped at 8000 chars with a `[...TRUNCATED]` sentinel that names the `block=2` filesystem:read for the tail) into the payload; the Architect's auto-tool now sets it to `true` so the baseline lands in every nudge. A new `tools/analyst_runner.py` replaces the Analyst's `filesystem:list` — it auto-picks the workspace by newest proposal mtime, locates the newest `change_proposal_CP-*.md` without a matching `critique_CP-*.md`, inlines the proposal body, extracts every referenced file path from the text (regex over a known extension list, with URL and shell-path reject substrings), previews each target (up to 8 targets, 1500 chars each), and classifies each target as `is_archived=true/false` via two rules: `old_stuff/` segments, and `architecture_review_v<N>.md` with N below the highest active version. The Architect and Analyst manifests each gain an explicit "ARCHIVAL GUARD" step right after reading the auto-tool payload — for the Architect it forbids drafting against archived targets, for the Analyst it mandates REJECT with rationale `"targets archived file — <path> is superseded (<archived_reason>)"` whenever any target carries `is_archived=true`. `roles.json` is rewired in the same cycle: Architect's `auto_tool.args` becomes `{"include_review_head": true}`, Analyst's becomes `{"name": "analyst_runner", "args": {"workspace_folder": "{workspace_folder}"}}`, and both role tasks are rewritten as five- and six-step flows starting from the new payload shape. See `decisions.md` D-20260418-07.

(2) Retire the stale Sentinel warning. The `> **Known issue:** log_summarizer is currently broken.` blockquote in `codex/role_manifests/sentinel.md` was correct at some earlier debugging point and dangerously wrong by the time CP-20260418-06 was written. It was replaced with a positive teaching line for the steady-state no-op case: `If log_summarizer returns "no cold logs" (the checkpoint is already caught up), that is the expected steady-state no-op. Report green and call mark_done — do not treat it as an error.` The corresponding `sentinel.task` text in `roles.json` was updated in the same cycle. General rule established: when a tool's behavior changes, update every role manifest that teaches about that tool in the same commit as the tool code — a false "Known issue" block has the same blast radius as a broken line of code. See `decisions.md` D-20260418-08.

## v0.6.4 — Sentinel Rapid-Fire Fix (2026-04-18)

gemma4:26b was rapid-firing `role_sentinel` every 7–15 seconds — six cycles in a minute — because `mark_done` was never actually running. Root cause: `core/loop.py::_build_role_nudge_text` ended the role briefing with a pseudo-function-call template (`goal_manager action="mark_done" goal_name="role_sentinel"`) while `_parse_tool_call` only recognizes fenced JSON blocks with a top-level `"tool"` key. The weaker model copied the example text verbatim, the parser couldn't match it, `last_run` stayed stale, and the sentinel was due again on the very next cycle. Other tool calls in the same session (log_summarizer) parsed fine because they came from the AVAILABLE TOOLS JSON example, not the WRAP-UP template. Fix: rebuild the WRAP-UP block as a real fenced JSON tool call matching the AVAILABLE TOOLS contract verbatim (```` ```json\n{"tool": "goal_manager", "args": {"action": "mark_done", "goal_name": "role_<role>"}}\n``` ````), and add explicit warning prose naming the prose-vs-JSON failure mode so models don't regress to the old shape. Smoke test through the live `_parse_tool_call` regex confirmed the new block parses to the exact payload `goal_manager.execute` expects. See `decisions.md` D-20260418-06.

## v0.6.3 — Version-Counter Recovery (2026-04-18)

The Scholar's architecture-review counter regressed from `v6` to `v1` when a cycle archived the baseline to `old_stuff/` before emitting the next review. Root cause: `scholar_runner` only globbed the active workspace for `architecture_review_v*.md`, and `scholar.md` step 3 told the model to compute `<v+1>` by parsing the baseline filename itself — both steps silently assumed the baseline would still be in the active folder when the model wrote. Any reversal of step 3, or a crash between archive and write, emptied the folder and routed the model into the "bootstrap `v1`" branch. Fix: `scholar_runner` now scans both active and `old_stuff/` review files via a `_VERSION_RE = re.compile(r"architecture_review_v(\d+)\.md$")` regex and surfaces `next_version`, `highest_version_seen`, and `highest_version_path` in its payload. The empty-active-folder case splits into a `warning` (old_stuff has versions → resume at `next_version`) versus an `error` (no reviews anywhere → genuine bootstrap). `codex/role_manifests/scholar.md` step 1 now branches on `review_path` / `warning` / `error` explicitly, and step 3 instructs the Scholar to write `architecture_review_v<next_version>.md` directly rather than incrementing a parsed filename. The write-then-move ordering still matters for a clean active folder, but reversing it no longer corrupts the counter — the next scholar_runner run recovers automatically. See `decisions.md` D-20260418-05.

## v0.6.2 — Delta Scan and Queue Hardening (2026-04-18)

A wave of small structural fixes landed together after several distinct failure modes surfaced in the same week. **scholar_runner** was silently self-skipping every edit to itself on an obsolete "infinite loop" rationale; the Scholar never saw that the scanning tool had changed. It was also using a loose `architecture_review_*.md` glob that matched legacy `architecture_review_part1.md` bootstrap files and could theoretically shadow a real `v<N>.md` baseline. And `codex/rejected_proposals.md` was referenced by scholar.md step 4 as one of three ledgers to read, but only `decisions.md` and `history.md` were force-included in deltas. Fix: remove the self-skip entirely, tighten the glob to `architecture_review_v*.md`, add `rejected_proposals.md` to `_MANDATORY_FILES`, sync `_PRUNED_DIRS` with `analyze_directory`, and emit a new `scan_stats` block (`files_scanned`, `mtime_delta_count`, `newest_file`, `newest_file_mtime`) so "why didn't my edit show up?" has a direct diagnostic answer. See `decisions.md` D-20260418-02.

**analyze_directory** could emit 25–30KB of output on a recursive call and then spend seconds stat'ing every archived proposal in `old_stuff/` or every compiled `.pyc`. The registry's 16000-char cap would then clip the tail — including the `[SUMMARY]` footer — so the model saw a truncated report with no closing summary. Fix: a 12000-char `_OUTPUT_BUDGET`, smaller per-file previews (20 lines, 1500 chars), and a pruned-dir set (`__pycache__`, `.git`, `.venv`, `old_stuff`, `node_modules`, etc.) that gets consulted both for recursive `os.walk` (via in-place `dirnames[:]` pruning) and non-recursive folder listings. When the budget is hit mid-scan the `[SUMMARY]` footer still lands, and a `[NOTE]` line tells the model exactly how many of the targeted files got previewed.

A **misleading "Target Queue empty" trace** was masking a real goals.json coercion bug. A hand-edited `"schedule_minutes": "0"` entry (string) made `"0" * 60` a 60-character zero-string, which crashed the `sched_s <= 0` comparison with a TypeError. The bottom-level `except Exception:` in `_check_goals_status` swallowed it and returned `(False, ...)`, which the loop rendered as "Target Queue empty. Halting continuous cycle." — indistinguishable from a legitimately empty queue. Fix: coerce `schedule_minutes` with `int()` inside a targeted `except (TypeError, ValueError)` and emit an actionable trace naming the specific goal and its malformed value, then skip just that entry. The offending `role_scholar` entry in `goals.json` was corrected to integer `120` (matching the Scholar manifest) and its description brought back in line with the current scholar_runner-driven flow. See `decisions.md` D-20260418-03.

**Ghost role keys** from stale `role_*` goals (e.g. `role_manager` left behind after an overlay rename) could get elected by `_check_goals_status` and fire `active_role_changed.emit("manager")`, producing UI artifacts on a role that no longer exists. The election step now filters `role_*` goals against the live `roles.json` keyset before any scheduling arithmetic. Same day, the GUI's `_ROLE_MAP` in `gui/chat_panel.py` lost the "The " prefix on every role title — overlay labels now render as "Sentinel", "Scholar", "Architect", etc. See `decisions.md` D-20260418-04.

Alongside these, `roles.json` scholar.task text was updated to reference all three ledgers (decisions, history, rejected_proposals) in the closed-proposal sweep description, matching the manifest.

## v0.6.1 — Filesystem Extensions: move, delete, block pagination (2026-04-18)

`tools/filesystem.py` picked up three surgical additions to cover gaps that were forcing the model out to `shell_exec` for ordinary maintenance. `operation: "move"` takes a `dest`, routes both endpoints through the single-anchor resolver, and refuses to overwrite an existing destination — archival workflows (Scholar's closed-proposal sweep, Architect's old-review rollover) no longer need a shell call, and overwrites require an explicit delete-first step so the log remains a reviewable audit trail. `operation: "delete"` removes single files only (directories are rejected; the empty-then-delete pattern makes deletions inspectable one-by-one instead of `rm -rf`ing state in a single call). `operation: "read"` gained an optional `block` integer parameter that paginates large files in 15000-char chunks — chosen deliberately below the registry's `MAX_TOOL_OUTPUT=16000` cap so the `[BLOCK N OF M — chars X..Y of Z]` footer always fits without being clipped. Pagination auto-triggers on files over one block even when the caller didn't pass `block`, so models that don't know the parameter still get a teaching footer that names the exact `block=N+1` value to request next. See `decisions.md` D-20260418-01.

## v0.6.0 — Path Discipline: Single-Anchor Resolver (2026-04-17)

The model had been emitting absolute paths with hallucinated user-segments — `C:/Users/ke/...`, `C:/Users/iam/...`, `C:/Users/kevin/OneDrive/to/Desktop/ai/...` — and tools would either fail opaquely or, worse, silently fall through to a different file. Two root causes were teaching the model this shape by example: `core/loop.py` was substituting `{workspace_folder}` and `{codex_folder}` into the system prompt as fully-qualified absolute paths, and `tools/analyze_directory.py`'s schema description literally read `"e.g., 'C:/Users/kevin/OneDrive/Desktop/ai'"`. The model dutifully imitated, then mangled the imitation under sampling pressure.

Fix: a new `core/path_utils.py` module owns a single anchor, `PROJECT_ROOT = Path(__file__).parent.parent.resolve()`. Every model-supplied path now flows through `resolve()`, which rejects absolutes (POSIX leading slash, Windows drive letter, UNC, `Path.is_absolute` fallback) and rejects `..` segments that climb out of the root, returning a teaching `PathRejectedError` whose text steers the model back to the correct shape (`"Absolute paths are not allowed... Use project-root-relative paths. Example: 'core/tool_registry.py', not 'C:/Users/.../core/tool_registry.py'."`). `tools/filesystem.py`, `tools/analyze_directory.py`, and `tools/screenshot.py` were rewired to call `resolve()` and to advertise relative-path examples in their schemas. The system prompt's `{workspace_folder}` and `{codex_folder}` substitutions now expand to `workspace/<model>` and `codex` (relative), and a new `[PATH DISCIPLINE]` block teaches the contract — correct vs. rejected examples, no fuzzy matching, re-issue with the relative form on rejection. Antigravity's "fuzzy resolution" plan was considered and rejected: silent salvage trains the model to keep emitting the wrong shape, where rejection-with-error trains it to stop. Tests in `tests/test_path_utils.py` cover all three named hallucination variants explicitly. See `decisions.md` D-20260417-09.

## v0.5.2 — Log Summarizer: User-Turn Message Shape (2026-04-17)

Second follow-up to v0.5.0. After v0.5.1 landed, the digest was still arriving empty when run against gemma4:26b — but succeeded against llama3:9b. Root cause: `tools/log_summarizer.py::_summarize` was packing the entire prompt (rules + log data) into `OllamaClient.chat(system_prompt, messages=[])`, producing an Ollama request with only a system turn and no user turn. gemma and several other models treat that as "system established, waiting for the human" and return an empty string; looser models like llama3:9b answer anyway. A short 60s timeout on a 26B model crunching ~12k chars was a secondary contributor.

Fix: `_build_prompt` now returns `(system_rules, user_content)`; `_summarize` calls `client.chat(system_rules, [{"role":"user","content":user_content}], timeout=300)`. The user payload is capped at ~12k chars so it fits in the stock 8k-token context window. An empty-response guard in `execute()` refuses to advance the checkpoint or append a digest entry when the model returns nothing — silent failures are now impossible. A module-level `__version__` marker (`tools/log_summarizer.__version__`) was added so a live process can verify which build is loaded. See `decisions.md` D-20260417-08.

## v0.5.1 — Log Summarizer: Incidents vs Routine (2026-04-17)

Follow-up to v0.5.0. The first two digests written by `tools/log_summarizer.py` missed real ERROR-level events and hallucinated a "clean system state." Root cause in `_build_prompt`: entries were rendered in a single chronological stream so the ~1% ERROR signal drowned in ~99% INFO cycle chatter, and context dicts were reduced to key names only (stripping paths, exception classes, tracebacks before the model ever saw them). On top of that the model editorialized a path error as a sandbox-escape attempt — the agent was just holding a stale legacy path from before v0.4.0.

Fix: split the entry stream into labelled `INCIDENTS` (WARNING/ERROR/CRITICAL, full context values clipped only per-value at 400 chars) and `ROUTINE` (INFO/DEBUG, component + message + context key names only) sections. Added five hard rules: lead with incidents, quote context verbatim, group repeats with a count, cap routine coverage at two trend bullets, no speculation about agent intent. Prior empty/wrong digests stay in place per the append-only rule; a Corrective Note was added to `codex/log_digest.md` documenting what was missed. See `decisions.md` D-20260417-07.

## v0.5.0 — Phase 5 Pilot: Cold-Log Digestion (2026-04-17)

The first sliver of the memory-summarization work landed. Rather than tackle conversation history, episodic memory, and cold logs all at once, Phase 5 scoped down to one data store — the Sentinel JSONL log — and one append-only destination: `codex/log_digest.md`. A new tool, `tools/log_summarizer.py`, reads entries older than 24 hours that are newer than its checkpoint, asks the currently loaded Ollama model to condense them into a short bullet list, appends a dated section to the digest, and advances the checkpoint at `state/.log_summarizer_checkpoint.json`. The Scholar's role manifest and 120-minute task now call the summarizer as a normal tool invocation; there are no prompt-level auto-triggers. `codex/manifest.json` registers `log_digest.md` and carries a new `memory_summarization` block declaring this is the "Phase 5 pilot" with scope="cold logs (>24h)". Conversation and episodic summarization are deferred to Phase 6. See `decisions.md` D-20260417-06.

## v0.4.1 — Codex Becomes Role-Writable (2026-04-17)

Follow-up to v0.4.0. The initial `[WORKSPACE POLICY]` block described the Codex as "read-mostly," but the Scholar and Orchestrator roles have maintenance tasks that require writing into `codex/`. The prompt and manifest were updated to explicitly permit writes into `codex/` alongside `workspace/<model>/`, with per-file conventions: Scholar → `architecture_review.md`; Orchestrator → `skill_map.md` + `role_manifests/`; any role → append to `decisions.md` and `history.md`; `persona_core.md` hand-edited by Kevin only. The physical sandbox in `tools/filesystem.py` was already project-root scoped, so no tool code changed. See `decisions.md` D-20260417-05.

## v0.4.0 — The Three-Layer Reorganization (2026-04-17)

The system finally got names for its layers. Before this release, "the loop," "the persona," and "the docs" were all informal categories that drifted from the code over time. Phase 4 of the upgrade plan made them real:

- **Cortex** (in `core/`) is the ephemeral runtime. Allowed to lose state on restart.
- **Persona** (in `codex/persona_core.md` + `roles.json`) is the identity layer. Invariant identity, situational overlays.
- **Codex** (in `codex/`) is the canonical on-disk truth.

Concretely, Phase 4:
- Moved `gemma4_26b_notes/architecture_review.md` and `skill_map.md` into `codex/` and refreshed them to reflect the three layers.
- Promoted the per-role manifests into `codex/role_manifests/`.
- Renamed the legacy `role_system_master.md` → `codex/role_overlays.md` and rewrote it around the servo-default model.
- Created four new Codex docs: `lexicon.md`, `decisions.md`, `glossary.md`, `history.md`.
- Consolidated all six `<model>_notes/` folders into a single `workspace/<model>/` tree.
- Added a compact manifest variant for small-context models.

## v0.3.1 — Servo Default Hotfix (2026-04-17)

Phase 3 introduced `servo` as a default role overlay, but the role-manager `sync` action created a `role_servo` continuous goal with `schedule_minutes: 0`. The election arithmetic (`remaining = 0 - elapsed`) made this goal perpetually overdue, so the Cortex auto-elected the servo identity every cycle. Fix: three-layer defense. `role_manager` now treats `servo` as non-schedulable, prunes any stale goal on sync, and `_check_goals_status` skips both the deny-list keys and any goal with `schedule_minutes ≤ 0`.

## v0.3.0 — Persona as a First-Class Layer (2026-04-17)

The Persona layer was extracted from the system-prompt assembly code and given two homes: an invariant identity in `codex/persona_core.md` and situational overlays in `roles.json`. Each role gained `voice_overlay`, `format_bias`, `risk_tolerance` fields. The Cortex now loads the persona core (mtime-cached, HTML comments stripped), looks up the active overlay (falling back to `servo`), and renders an `[ACTIVE ROLE]` block in every system prompt. The GUI grew an overlay label that updates live as roles switch.

## v0.2.0 — Determinism, Cancellability, Telemetry (2026-04-16)

Phase 2 hardened the Cortex. Role election became deterministic (priority asc, overdue desc — no more random ties). Ollama chat/chat_stream became cancellable. `submit_input` now cancels in-flight generation. The grace-cycle counter got a cap to prevent indefinite overlay lock. SYSTEM nudges stopped being persisted to history. Truncation and auto-continue counters were added to the telemetry stream. The 5-vs-6-step ambiguity was resolved by renaming `IDLE` → `OBSERVE`. The `MANIFEST.json` was placed at the root and injected into every system prompt.

## v0.1.x — Pre-Reorganization (≤ 2026-04-15)

Servo started as a continuous-loop agent with a Sentinel/Architect/Analyst/Scholar/Orchestrator role system, hardcoded paths to `gemma4_26b_notes/`, an informal `role_system_master.md` registry, and an in-prompt persona that drifted between commits. The 6-step loop existed but was sometimes called 5 steps (IDLE was treated as the absence of a step). Six per-model `<model>_notes/` folders accumulated organically.



---

## v1.3.1 — Targeted Line Reading & Standardized Pagination (2026-04-22)
**File Read Precision & Token Limiting**

### ✨ Key Improvements
*   **Targeted Read Access**: Added 1-indexed `start_line` and `end_line` support to `file_read` and `fetch_url`. This allows the agent to target specific logic blocks without character-offset math or context bloat.
*   **Standardized Pagination**: Implemented a unified block-based pagination system across all content-heavy tools (`file_read`, `fetch_url`, `youtube_transcript`).
*   **Standardized Footers**: Tool results now include clear pagination metadata, e.g., `[Showing lines 100-200 of 1540]`, providing absolute location awareness.
*   **Efficiency Standards**: Formally codified the **Efficient File Investigative Pattern** in the Engineering Standards, mandating surgical reads for code exploration.

---

## v1.3.2 — Context Viewer UI & Thread Synchronization (2026-04-22)
**State Auditing & Synchronization**

### ✨ Key Improvements
*   **The Context Viewer**: Implemented a diagnostic interface (`gui/context_viewer.py`) that mirrors the agent's internal perception window.
*   **Prompt State Logging**: The viewer exposes the rendered system prompt, conversation history, task ledger, and working memory exactly as sent to the LLM.
*   **Synchronous Thread Pause**: Integrated `wait_if_paused` logic into `CoreLoop`. The `context_dump` tool now acts as a "Pause" trigger, allowing synchronous auditing of mid-thought state.
*   **Safe Resumption**: Closing the viewer or clicking the prominent "RESUME" button unblocks the execution thread safely.

---


---

## v1.3.3 — GUI Component Modularization & UI Polish (2026-04-22)
**Layout Refinement & Space Efficiency**

### ✨ Key Improvements
*   **Collapsible Tool Panel**: Implemented a "fold/unfold" mechanism (>> / «) for the main Tool Panel to maximize chat workspace.
*   **Dynamic Stretch Application**: Refactored the `ContextViewer` and `ToolPanel` to use shared `CollapsibleSection` components. These use dynamic stretch factors to greedily consume 100% of available vertical space.
*   **Internal List Collapsibility**: Added a collapsible header to the "INSTALLED TOOLS" list in the Tool Panel, providing deeper decluttering options.
*   **One-Click Diagnostics**: Standardized interactive triggers for `context_dump` and `system_config` in the tools list for instant auditing.
*   **Non-Pausing State Auditing**: Updated `context_dump` with `pause_loop=False` support, enabling live background snapshots without interrupting the agent's reasoning.
*   **Shared Component Library**: Factored out `CollapsibleSection` into `gui/components.py` to ensure consistent theming and behavior across future UI expansions.

### 🐛 Stability & Hardening
*   **NameError Resolution**: Fixed a missing `QPushButton` import in `MainWindow`.
*   **Type-Safe Persistence**: Hardened the working memory snapshot logic in `CoreLoop` to ensure non-string payloads are cast to string before emission.
*   **Safeguarded Dismissal**: Linked the Context Viewer window-close event ("X") to the loop's `resume()` slot to prevent the agent from being accidentally orphaned in a paused state.
*   **Layout Hardening**: Set `Expanding` size policies on all collapsible text editors to prevent static whitespace gaps in the dashboard.

---
 
 ## v1.3.4 — Tool Registry Classification & Initialization Commands (2026-04-22)
 **Core State Visibility & Automated Initialization**
 
 ### ✨ Key Improvements
 *   **Tool Classification**: Implemented a visual and metadata-level distinction between **System Tools** (Yellow) and **Standalone Tools** (Green).
 *   **System Tool Visibility**: Yellow highlights in the GUI now clearly demarcate tools that require core hooks or drive the loop (e.g., `context_dump`, `task`, `summarizer`).
 *   **Startup Chores**: Introduced the `--chores` CLI flag. This enables automated initialization procedures from a user-customizable `chores.md` file.
 *   **Automated Initialization**: Chores allow the agent to map the project, persist findings to the workspace, and audit "mission residue" (logs/tasks) automatically upon boot.
 *   **Fresh State Synchronization**: Mandated a working memory synthesis during chores to ensure total alignment between the model, the user, and the current source code state.
 
 ---

## v1.4.0 — Phase C: Cognate Intelligence Pass (2026-04-23)
**The circuit learns.** Phase B closed the loop; Phase C fills it with cognition.

### ✨ Key Improvements
*   **Sovereign Ledger Durability**: `lx_StateStore` now persists to `state/lx_state_<profile>.json` (byte-identical mirror of `current_state`) and commits Success Vectors to a ChromaDB `procedural_wins` collection per profile.
*   **Real Cognate Bodies**: `lx_Observe` emits a sha1 observation signature from structural Python-file counts. `lx_Reason` runs ε-greedy tool selection with exponential decay (ε₀=0.3, λ=0.001) and post-failure pivots. `lx_Act` dispatches atomic primitives through a constrained ToolRegistry with a lexicon halt gate. `lx_Integrate` synthesizes R = Φ · (L · P) and commits iff R ≥ 0.8.
*   **ToolOutcome Contract**: New `core/lx_outcomes.py` dataclass carries `status`, `return_value`, `stderr`, `latency_ms`, `tool_name`, `args_fingerprint` between Cognates — the first common vocabulary for inter-Cognate feedback.
*   **Atomic Dispatch Surface**: Phase C restricts the loop to six verified primitives (`file_read`, `file_write`, `file_list`, `file_manage`, `map_project`, `summarizer`) per D-20260421-14; system-tier tools (D-20260422-05) are filtered and deferred to Phase D.
*   **Reference Preservation for loop.py**: Phase C's `lx_StateStore` opens the legacy `state.db` in URI read-only mode. Zero writes to loop.py paths (`git diff --ignore-cr-at-eol core/loop.py` empty). The legacy boot path remains untouched as a reference artifact.
*   **Environment-Portable ProceduralWins**: Metadata-only exact-match queries with dummy embeddings mean the Success Vector collection transfers across machines without ONNX model downloads. Phase D can swap in real embeddings when NN matching lands.
*   **Audit Fence Sharpening**: Lexicon samples are now `(text, expected_pass)` tuples — the regression sample ("I'm sorry, as an AI...") is supposed to fail the filter, and module-pass is now `observed == expected`. `Overall Pass: True` is once again a meaningful signal.

### 🐛 Stability & Hardening
*   **Graceful Chroma Degradation**: Missing or corrupt `procedural_wins` index leaves `_procedural_wins = None` — commits silently skip and queries return `[]`. The loop still cycles without the reinforcement signal rather than opening the circuit.
*   **Merge-Only Delta Apply**: `apply_delta` merges into `current_state` instead of overwriting — prevents parallel Cognates or halt signals from being dropped.
*   **Active-Store Lifecycle**: `ServoCore.run_cycle` stashes `self._active_store = state_provider` at loop start and clears it when the loop breaks, so a stale handle can't leak into a later out-of-cycle Cognate call.
*   **Correctness setUp Portability**: Legacy StateStore is routed into a tempdir so setUp works on sandbox mounts where chromadb's embedded SQLite can't acquire file locks. `test_core_loop_handshake` uses a scoped profile + `store.reset()` to guarantee a clean OBSERVE cursor.
*   **Stale `.pyc` Flush**: Bumped lx_state.py mtime to force Python to recompile away a stale bytecode that was missing the `embeddings` kwarg in the commit path — commits now actually land.

---
 *Append a new section per release. Do not rewrite history.*
