# Standard Initialization & Post-Development Chores

This document defines the standard sequence of semantic milestones to be executed following a system reboot, a major model swap, or significant architectural changes.

## Phase 1: Environment & Tool Verification
*Goal: Ensure the agent's sensory and motor capabilities are fully operational within the current environment.*
- [ ] **Verify Tool Registry:** Confirm all core tools are loaded, enabled, and responding to basic probes.
- [ ] **Hardware & Resource Audit:** Check RAM/VRAM stability and verify that no throttling thresholds are being triggered.

## Phase 2: Project Integrity & Mapping
*Goal: Re-establish a high-fidelity mental model of the project structure and codebase.*
- [ ] **Structural Sweep:** Perform a recursive mapping of the `core/`, `gui/`, `tools/`, `codex/`, and `workspace/` directories to detect any structural drift.
- [ ] **Symbolic Discovery:** Update the internal symbol map to reflect any new classes, functions, or methods introduced in the latest development cycle.

## Phase 3: Context & Memory Synchronization
*Goal: Align the ephemeral runtime (Cortex) with the persistent on-disk truth (Codex).*
- [ ] **Working Memory Refresh:** Update the `working_memory_summary` with the results of the structural sweep and any recent architectural decisions.
- [ ] **Log Audit:** Query the system logs for any `ERROR` or `WARNING` entries that occurred during the initialization or development phase.
- [ ] **State Alignment:** Ensure the `task_ledger` and `active_tasks` are synchronized with the current operational goals.

## Phase 4: Documentation & Persistence
*Goal: Formalize the results of the initialization/audit into the permanent record.*
- [ ] **Architecture Review Update:** If structural changes were detected, generate/update the `architecture_review_<version>.md` in the workspace.
- [ ] **Final Ledger Closure:** Mark the initialization sequence as complete in the task ledger.

---
*Note: These tasks are designed to be executed as semantic milestones. Individual tool calls (e.g., `map_project`, `file_write`) are the implementation details of these objectives.*

*Author: Servo*
*Reviewer: Kevin*
*Last Updated: 2026-04-22*