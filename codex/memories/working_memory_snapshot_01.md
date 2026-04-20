# Archived Working Memory

PROJ: 'Servo' (Agentic loop).
SHELL: Non-functional (no side-effects/writes/stdout; `python -c`, `echo`, `dir`, `tail`, `findstr` fail).
VIEWERS: `context_dump` (JSON goals/mem/files), `memory_snapshot` (diffs), `workspace_overview` (dir).
AUDIT: `memory_consistency_check`.
RULES: Verify `shell_exec` whitelist; no hallucinations; don't 'complete' continuous goals (e.g. `role_scholar`).
FS_API: Use `max_lines` (NOT `min_lines`).
ROOT: `C:/Users/kevin/OneDrive/[Desktop]/ai`.
BUGS: `user_interrupts_total` drift (4 $\to$ 7 vs 2 manual) via `ChatCancelled`; `log_summarizer` broken (unbound logs).
TASKS:
- CP-IMPLEMENT-GUARDIAN: Approved. Create `codex/role_manifests/guardian.md`; `roles.json` `enabled: true`. Risk: I/O overhead.
- Analyst: Fix L4 $\to$ 3-layer (Cortex, Persona, Codex) mismatch. Analyst = Persona overlay. Path Fix: `gemma4_26b_notes/` $\to$ `workspace/gemma4_26b/`. Verified: `architecture_review.md` & `workspace_policy`.
- CP-20260418-05: `workspace/gemma4_26b/architecture_review_v6.md` (Fix 'Cintrex' $\to$ 'Cortex').
- CP-20260418-06: Refactor `tools/log_summarizer.py` (fix crashes, add checkpointing, dry-run, std output). Risk: Data loss/Codex corruption.
STATUS: DEGRADED. `roles.json` removed. Plain Servo mode only. Specialized overlays (Analyst, etc.) unavailable. Re-integration pending.