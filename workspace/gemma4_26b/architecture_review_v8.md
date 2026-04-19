# Architecture Review: Servo — Cybernetic Actuator

**Status:** Stable
**Last Updated:** 2026-04-18
**Version:** 8.0

## System Overview
Servo is an autonomous agentic ecosystem organized into three canonical layers: **Cortex** (ephemeral runtime), **Persona** (identity + overlays), and **Codex** (on-disk truth). The system has recently transitioned from a passive persona-only model to an active, tool-triggered execution model where roles like the Scholar and Sentinel use `auto_tool` configurations to bootstrap their context.

## Recent Changes & Engineering Progress

### 1. Scholar Role & Versioning Hardening
Significant improvements were made to the `scholar_runner` tool and the Scholar's operational logic to prevent version regression. 
- **Self-Healing Version Counter:** The `scholar_runner` now scans both the active workspace and `old_stuff/` to find the highest `architecture_review_v<N>.md`. This ensures that if a prior cycle archived the baseline before the new review was written, the counter does not reset to `v1`.
- **Removal of Self-Skip:** The tool no longer ignores its own file (`tools/scholar_runner.py`). This ensures that any updates to the scanning logic itself are captured as deltas in the next review.
- **Diagnostic Observability:** The addition of `scan_stats` (e.s., `files_scanned`, `mtime_delta_count`) provides the Scholar with immediate feedback on the efficacy of the delta scan.

### 2. Filesystem & Tool Registry Refinements
- **Surgical Filesystem Operations:** The `filesystem` tool was extended with `move` and `delete` operations. This allows roles like the Scholar and Architect to perform archival (moving old reviews/proposals to `old_stuff/`) and cleanup without resorting to `shell_exec`.
- **Large File Pagination:** The `read` operation now supports `block` pagination, preventing the tool registry's 16,000-character limit from truncating large file reads and ensuring the model receives complete data.
- **Path Discipline:** The system has moved to a strict, project-root-relative path contract. The `core/path_utils.py` module now enforces this, rejecting absolute paths and preventing directory traversal attempts, which significantly reduces hallucination-driven tool failures.

### 3. Goal & Process Stability
- **Goal Queue Hardening:** The `goal_manager` and the underlying loop were updated to handle malformed `goals.json` entries (e.g., string-based `schedule_minutes`) by coercing values to integers, preventing `TypeError` crashes during the election cycle.
- **Log Summarization (Phase 5):** The `log_summarizer` tool was refined to separate `INCIDENTS` (errors/warnings) from `ROUTine` (info/debug) logs. This prevents critical error signals from being drowned out by routine operational chatter during the digestion process.

## Architectural Decisions & Rejections

- **Rejection of VRAM Hysteresis (CP-20260416-03):** The proposal to add a complex hysteresis layer for VRAM monitoring was rejected in favor of the existing, simpler AND-gate threshold combined with the established throttle-and-restore pattern in `core/loop.py`.
- **Rejection of Guardian Role (CP-20260418-01):** The activation of a dedicated `guardian` role for file integrity monitoring was rejected as over-engineered for the current single-user threat model. Prevention via `path_utils.py` is prioritized over detection via periodic hashing.
- **Rejection of Tool Metadata Rework:** Proposals to move tool metadata into a centralized JSON manifest were rejected to avoid the synchronization risks inherent in decoupled metadata stores.

## Next Steps
- Continue refining the `log_summarizer` (Phase 5 pilot).
- Monitor the stability of the `scholar_runner` versioning during high-frequency archival cycles.
- Maintain the strict path-relative contract across all new tool implementations.