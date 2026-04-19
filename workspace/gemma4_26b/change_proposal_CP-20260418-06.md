# Change Proposal: CP-20260418-06

**Status:** Draft
**Author:** Architect
**Date:** 2026-04-18
**Target:** `tools/log_summarizer.py` and `codex/log_digest.md` structure

## 1. Problem Statement
Currently, the `log_summarizer` tool is in a broken state. While the `role_sentinel` is designed to use this tool to condense cold logs into `codex/log_digest.md`, the failure of the tool prevents the maintenance of long-term log observability. This results in the `logs/sentinel.jsonl` growing unbounded and the `log_digest.md` becoming stale.

## 2. Proposed Solution
Perform a structured refactor of the `log_summarizer` tool to:
1.  **Fix the underlying error:** Identify and resolve the crash/error causing the tool to fail during execution.
2.  **Verify Checkpoint Logic:** Ensure the `state/.log_summarizer_checkpoint.json` is correctly updated only after a successful write to the Codex.
3.  **Implement Dry-Run Validation:** Ensure the `dry_run=true` flag works reliably for the Sentinel's sanity checks.
4.  **Standardize Output:** Ensure the summary format aligns with the new `INCIDENTS` vs `ROUTINE` distinction introduced in the recent architecture review.

## 3. Technical Risks
- **Data Loss:** Incorrectly handling the checkpoint could lead to duplicate log summarization or missed log entries.
- **Codex Corruption:** A failure during the `append` operation to `codex/log_digest.md` could leave the file in an inconsistent state.

## 4. Implementation Plan
- **Step 1:** Use `log_query` to inspect recent failures in `logs/sentinel.json_l` related to the summarizer.
- **Step 2:** Create a reproduction script in `workspace/gemma4_26b/` that triggers the failure.
- **Step 3:** Refactor `tools/log_summarizer.py`.
- **Step 4:** Test with `dry_run=true` via `shell_exec` or manual tool invocation.
- **Step 5:** Verify the `log_digest.md` is updated and the checkpoint is advanced.

## 5. Impact
- **Positive:** Restores full observability for the Sentinel role; prevents unbounded log growth; ensures long-term auditability of system events.
- **Negative:** Requires temporary maintenance of the Sentinel's secondary duty during the fix.