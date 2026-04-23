# PLAN_PHASE_C_BRAIN.md
**Status:** DRAFTING IN PROGRESS | **Priority:** CRITICAL

**Resource Allocation:** Claude Pro Opus 4.7 (Reasoning/Logic) / Gemini 3.1 (Escalation)

## 1. Objective
Inject the intelligence layer into the scaffolded cognates. This phase moves from "Placeholder Stubs" to "Closed-Circuit Execution." We will use Claude Pro to handle the heavy regex parsing and architectural reasoning required for persistent memory.

## 2. Component Directives

### A. lx_Reason (The Planner)
**Goal:** Turn the high-level `task_ledger` into a step-by-step `lx_Plan`.
**Intelligence:** Must analyze the current filesystem and state to determine if it should **Exploit** a Success Vector or **Explore** a new trajectory.
**Logic:** Implement the dynamic $\epsilon$ tuning based on previous benchmark results.

### B. lx_Act (The Execution Circuit)
**Goal:** Execute the code/commands via subprocess or `file_write`.
**Closed-Circuit Logic:** If a command returns a non-zero exit code, the `lx_Act` cognate must catch the error and pass it back to `REASON` for an immediate correction cycle—The circuit does not open until the benchmark passes.

### C. lx_Integrate (The Success Vector)
**Goal:** Parse the execution trace and commit a "Win" to ChromaDB.
**Intelligence:** Use Claude Pro to draft the regex patterns that extract:
* Temporal Jitter ($\sigma$)
* Numerical Precision ($\epsilon$)
* Signal-to-Prose Ratio

## 3. The ChromaDB Handshake
* We will wire the `sync_vector()` method in `lx_state.py` to the local ChromaDB instance.
* **The Success Vector Schema:** Each "Win" is stored as a vector with metadata for the Lexicon Score and Execution Time.

---
**Audit Guardrails (Naming Alignment):**
- Ensure all logic refers to `lx_StateStore`, `lx_Observe`, `lx_Reason`, `lx_Act`, and `lx_Integrate`.
- Mandatory return format: `lx_StateDelta` (dictionary).
- Loop Entry: `ServoCore.run_cycle(state_provider)`.

*Author: Servo*
*Plan Version: 1.0.0 (D-20260423)*
