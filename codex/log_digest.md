# Log Digest

**Status:** Append-only, machine-written
**Maintainer:** `tools/log_summarizer.py` (Phase 5 pilot)
**Source:** `logs/sentinel.jsonl`

This file is the human-readable destination for periodic summaries of cold log entries. The log summarizer reads entries older than 24 hours that have not yet been summarized, asks the active model to condense them into a short digest, and appends one section per run.

## Editing rules

- **Do not hand-edit prior entries.** This file is append-only. If a digest entry is wrong, add a corrective entry below it — never silently rewrite.
- New entries go at the bottom, under a `## Digest — <UTC date range>` heading.
- The summarizer updates `state/.log_summarizer_checkpoint.json` after each successful append so it does not re-summarize the same window on the next run.
- If this file is missing, the summarizer will recreate it with this header.

## Why it exists

Cold log lines are verbose, low-information, and repetitive (e.g. ~100 `loop.contextualize` INFO lines per day). Keeping them condensed in the Codex lets small-context models build an accurate picture of "what happened yesterday" without paying for every tokenized INFO line. This is the Phase 5 pilot for the broader memory-summarization work (tied to CP-20260416-01, scoped down per UPGRADE_PLAN.md §4.6).

---

<!-- Entries are appended below this line by tools/log_summarizer.py. -->

## Digest — 2026-04-17T08:23:56.134232+00:00 → 2026-04-17T08:52:37.032150+00:00

**Entries summarized:** 500  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T16:12:17.934330+00:00

- System log audit via `log_query` returned no ERROR or CRITICAL entries.
- Frequent automated snoozing of continuous goals `role_servo` and `role_sentinel` via `goal_manager`.
- Periodic workspace and goal status audits performed using `context_dump`.
- Core loop maintained continuous operation with automated tool-chaining enabled.

## Digest — 2026-04-17T08:52:37.034097+00:00 → 2026-04-17T09:21:26.759390+00:00

**Entries summarized:** 500  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T16:28:54.786065+00:00

- System restart and core loop initialization detected.
- Repeated `log_query` executions for `ERROR` level returned no matches, indicating a clean system state.
- `role_sentinel` goal was consistently snoozed/marked as run via `goal_manager`.
- `analyze_directory` tool triggered a truncation warning during execution.

## Corrective Note — 2026-04-17 (Kevin-sourced)

The two digests above are incomplete. The Sentinel role actually encountered path errors during these windows (references to the legacy `gemma4_26b_notes/` folder that was consolidated into `workspace/gemma4_26b/` in v0.4.0) and the model misinterpreted those errors as attempted sandbox escapes, which is not what happened — the agent was simply holding a stale path in memory. The underlying path-memory issue is noted for a future fix.

Root cause of the miss was in `tools/log_summarizer.py::_build_prompt`: it rendered ERROR and INFO entries in the same chronological stream and stripped context dict **values** (keeping only key names) across the board, which deleted the error details — paths, exception classes, stack traces — before the model ever saw them. A ~1% error signal then got drowned out by 99% routine chatter.

Fix in place (v0.5.0 + 1): the prompt now splits into an INCIDENTS section (WARNING/ERROR/CRITICAL entries with full context values preserved) and a ROUTINE section (INFO/DEBUG compressed to component + message + key names only), with explicit hard rules telling the model to lead with incidents, quote context verbatim, count repeats, and not to speculate about agent intent. Future digests covering this window should be re-run against the fixed tool to get an accurate record — but per the editing rules, the original entries stay as-is.

## Digest — 2026-04-17T16:45:32.755893+00:00 → 2026-04-17T16:53:51.320838+00:00

**Entries summarized:** 387  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T16:54:17.060380+00:00

_(model returned empty summary)_

## Digest — 2026-04-17T16:54:17.061557+00:00 → 2026-04-17T16:58:59.082993+00:00

**Entries summarized:** 85  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T16:59:23.211762+00:00

_(model returned empty summary)_

## Digest — 2026-04-17T17:14:33.414718+00:00 → 2026-04-17T17:14:43.475264+00:00

**Entries summarized:** 25  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T17:15:06.218527+00:00

_(model returned empty summary — response was truncated, likely due to context limits)_

## Digest — 2026-04-17T17:14:33.414718+00:00 → 2026-04-17T17:15:27.076714+00:00

**Entries summarized:** 71  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T17:33:19.143822+00:00

_(model returned empty summary — response was truncated, likely due to context limits)_

## Digest — 2026-04-17T17:14:33.414718+00:00 → 2026-04-17T17:15:27.076714+00:00

**Entries summarized:** 71  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-17T17:34:31.162401+00:00

_(model returned empty summary — response was truncated, likely due to context limits)_


## Digest — 2026-04-19T01:25:11.778419+00:00 → 2026-04-19T02:21:16.517857+00:00

**Entries summarized:** 500  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-19T02:43:08.247013+00:00

- core_loop hit WARNING with 'Response truncated by num_predict — auto-continuing' x2
- Continuous execution through cycles 13 to 16 using tool chaining for filesystem and goal_manager
- Consistent maintenance of 15 conversation turns and 5 recent memory entries

## Digest — 2026-04-19T02:21:16.519214+00:00 → 2026-04-19T03:03:20.835602+00:00

**Entries summarized:** 170  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-19T03:03:43.764106+00:00

- 3 cycles processed with auto-chained tools including `log_summarizer`, `goal_manager`, and `context_dump`.
- `core_loop` restarted with `gemma4:26b` and `role_sentinel` set to snooze.

## Digest — 2026-04-19T19:43:48.398144+00:00 → 2026-04-19T21:26:11.075144+00:00

**Entries summarized:** 500  
**Model:** `gemma4:26b`  
**Generated:** 2026-04-19T21:27:35.879464+00:00

- core_loop hit WARNING: Response truncated by num_predict — auto-continuing (1/2) x1
- loop.history_compressor hit WARNING: kernel returned empty summary — keeping raw turns, backing off before next attempt x3
- Executed perception cycles 3 through 5 involving filesystem tool reads on `codex/decisions.md`.
- tool_registry loaded 11 tools including filesystem, shell_exec, and memory_manager.
