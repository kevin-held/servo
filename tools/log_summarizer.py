"""
log_summarizer — Phase 5 pilot tool for cold-log condensation.

Reads entries from logs/sentinel.jsonl that are:
  * older than `age_hours` (default 24h) — i.e. "cold"
  * newer than the last checkpoint at state/.log_summarizer_checkpoint.json

If any qualifying entries exist, asks the currently loaded Ollama model to
condense them into a short digest, appends a dated section to
codex/log_digest.md, and advances the checkpoint.

This is the Phase 5 pilot for the broader memory-summarization work
(see UPGRADE_PLAN.md §4.6 and decisions.md D-20260417-06). Scoped intentionally
small: one append-only destination file, one driver tool, age-based threshold.

Contract: standard agent tool — TOOL_NAME / TOOL_DESCRIPTION / TOOL_ENABLED /
TOOL_SCHEMA / execute().
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

TOOL_NAME        = "log_summarizer"
TOOL_DESCRIPTION = (
    "Condense cold (>24h old) entries from logs/sentinel.jsonl into a short "
    "digest and append it to codex/log_digest.md. Uses a checkpoint so the "
    "same window is never summarized twice. Pass dry_run=true to preview the "
    "digest without writing to disk or advancing the checkpoint."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "dry_run": {
        "type": "boolean",
        "description": "(Optional) If true, return the generated digest without "
                       "writing to codex/log_digest.md or updating the checkpoint. "
                       "Default false.",
    },
    "age_hours": {
        "type": "integer",
        "description": "(Optional) Age threshold in hours. Entries older than this "
                       "are eligible for summarization. Default 24.",
    },
    "max_entries": {
        "type": "integer",
        "description": "(Optional) Hard cap on entries fed to the model in a single "
                       "run. Default 500. Extra entries roll over to the next run.",
    },
}

# ── Path resolution ────────────────────────────────────────
_ROOT            = Path(__file__).parent.parent.resolve()
_LOG_FILE        = _ROOT / "logs" / "sentinel.jsonl"
_DIGEST_FILE     = _ROOT / "codex" / "log_digest.md"
_CHECKPOINT_FILE = _ROOT / "state" / ".log_summarizer_checkpoint.json"

# Add project root to sys.path so we can import core.ollama_client
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helpers ────────────────────────────────────────────────

def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp (with or without trailing Z) into an aware datetime."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_checkpoint() -> str | None:
    """Return the ISO timestamp of the last summarized entry, or None if unset."""
    if not _CHECKPOINT_FILE.exists():
        return None
    try:
        with _CHECKPOINT_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("last_summarized_ts")
    except Exception:
        return None


def _save_checkpoint(last_ts: str, summarized_count: int) -> None:
    """Persist the checkpoint after a successful append."""
    _CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_summarized_ts": last_ts,
        "summarized_count":   summarized_count,
        "updated_at":         datetime.now(timezone.utc).isoformat(),
    }
    with _CHECKPOINT_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _collect_entries(age_hours: int, max_entries: int, checkpoint_ts: str | None) -> list[dict]:
    """Stream sentinel.jsonl and return the list of entries eligible for summarization."""
    if not _LOG_FILE.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    checkpoint_dt = _parse_iso(checkpoint_ts) if checkpoint_ts else None

    entries: list[dict] = []
    with _LOG_FILE.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = obj.get("timestamp_utc")
            if not ts:
                continue
            try:
                dt = _parse_iso(ts)
            except Exception:
                continue
            if dt >= cutoff:
                # "Hot" — skip. Sentinel log is append-order so we could break,
                # but we scan the whole file to tolerate clock skew / out-of-order
                # writes from multiple components.
                continue
            if checkpoint_dt is not None and dt <= checkpoint_dt:
                continue
            entries.append(obj)
            if len(entries) >= max_entries:
                break
    return entries


_ERROR_LEVELS = {"WARNING", "ERROR", "CRITICAL"}


def _format_entry(e: dict, *, include_full_context: bool) -> str:
    """Render one entry for the prompt. Errors keep full context values; info keeps key names only."""
    level     = e.get("level", "?")
    component = e.get("component", "?")
    ts        = e.get("timestamp_utc", "?")
    message   = (e.get("message") or "").strip().replace("\n", " ")
    ctx       = e.get("context") or {}

    if include_full_context and isinstance(ctx, dict) and ctx:
        # Full values — but clip any single value to avoid a 10KB traceback
        # blowing up the prompt.
        parts = []
        for k in sorted(ctx.keys()):
            v = ctx[k]
            v_str = str(v).replace("\n", " ")
            if len(v_str) > 400:
                v_str = v_str[:400] + "…(truncated)"
            parts.append(f"{k}={v_str}")
        ctx_note = f" [ctx: {'; '.join(parts)}]"
    elif isinstance(ctx, dict) and ctx:
        ctx_note = f" [ctx_keys: {', '.join(sorted(ctx.keys()))}]"
    else:
        ctx_note = ""

    return f"{ts}  {level:<8} {component:<28} :: {message}{ctx_note}"


# Budget for the log payload that goes in the user message.
# Chosen to fit comfortably inside a default 8k-token context window
# (roughly ~32k chars, leaving ample room for the model's response).
# Incidents are never truncated; only routine lines get clipped.
_USER_PAYLOAD_MAX_CHARS = 12_000


def _build_prompt(entries: list[dict]) -> tuple[str, str]:
    """
    Split the prompt into a short *system rules* block and a *user content*
    block. This is the shape Ollama's chat endpoint actually expects — a
    system-only request (no user turn) produces empty responses on gemma and
    several other models, which is what caused the first pilot to write
    blank digests.

    Structural insight (unchanged from the prior revision): ERROR/WARNING
    entries have to be segregated from INFO/DEBUG, otherwise a ~1% incident
    signal drowns in ~99% routine chatter and the model summarizes the
    wrong thing.

    Returns:
        (system_rules, user_content)
    """
    incidents: list[str] = []
    routine:   list[str] = []

    for e in entries:
        level = str(e.get("level", "")).upper()
        if level in _ERROR_LEVELS:
            incidents.append(_format_entry(e, include_full_context=True))
        else:
            routine.append(_format_entry(e, include_full_context=False))

    incidents_block = "\n".join(incidents) if incidents else "(none)"
    routine_block   = "\n".join(routine)   if routine   else "(none)"

    # Incidents are sacred; only trim routine to stay under the budget.
    reserve_for_incidents = min(len(incidents_block), _USER_PAYLOAD_MAX_CHARS // 2)
    routine_budget        = max(1_000, _USER_PAYLOAD_MAX_CHARS - reserve_for_incidents - 500)
    if len(routine_block) > routine_budget:
        routine_block = routine_block[-routine_budget:]

    system_rules = (
        "You compress cold system-log entries into a short digest. Your "
        "audience is a future version of the same agent that produced these "
        "logs; the digest is how it will remember what happened.\n\n"
        "HARD RULES:\n"
        "1. If the INCIDENTS section is non-empty, your FIRST bullets MUST "
        "describe those entries. Quote component, error class, and paths "
        "verbatim from the context — do not paraphrase into vagueness.\n"
        "2. Group repeated errors from the same component into one bullet "
        "with a count (e.g. 'role_sentinel hit FileNotFoundError on "
        "<path> x7').\n"
        "3. Do not speculate about intent. A path error means the path was "
        "wrong, not that the agent tried to escape its sandbox. Stick to "
        "what the log actually says.\n"
        "4. After incidents, add at most 2 bullets summarizing ROUTINE "
        "activity as a trend (cycle count, active roles, restarts). Never "
        "enumerate individual routine lines.\n"
        "5. Return ONLY bullet points, one per line, each starting with "
        "'- '. No preamble, no trailing commentary, no headings."
    )

    user_content = (
        f"Summarize the following log window as bullets.\n\n"
        f"=== INCIDENTS (WARNING/ERROR/CRITICAL, n={len(incidents)}) ===\n"
        f"{incidents_block}\n"
        f"=== ROUTINE (DEBUG/INFO, n={len(routine)}) ===\n"
        f"{routine_block}\n"
        f"=== END ===\n\n"
        f"Write the bullets now."
    )

    return system_rules, user_content


def _summarize(entries: list[dict]) -> tuple[str, str]:
    """
    Build the INCIDENTS/ROUTINE prompt for the given entries and hand it
    to the shared summarization kernel (`tools.summarizer.summarize`).

    Returns (summary_text, model_name_used). An empty summary string is
    passed through verbatim; the caller (`execute()`) decides whether
    that is fatal. See D-20260418-10 for the kernel split rationale.
    """
    from tools.summarizer import summarize as _kernel_summarize

    system_rules, user_content = _build_prompt(entries)
    return _kernel_summarize(user_content, system_rules)


def _append_digest(
    entries: list[dict],
    summary: str,
    model_name: str,
    first_ts: str,
    last_ts: str,
) -> None:
    """Append a dated section to codex/log_digest.md."""
    _DIGEST_FILE.parent.mkdir(parents=True, exist_ok=True)

    header = (
        f"\n## Digest — {first_ts} → {last_ts}\n\n"
        f"**Entries summarized:** {len(entries)}  \n"
        f"**Model:** `{model_name}`  \n"
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n"
    )
    # Normalize summary — if the model forgot bullets, wrap in a code block.
    body = summary if summary else "_(model returned empty summary)_"

    with _DIGEST_FILE.open("a", encoding="utf-8") as f:
        f.write(header)
        f.write(body.rstrip() + "\n")


# ── Public entry point ────────────────────────────────────

def execute(dry_run: bool = False, age_hours: int = 24, max_entries: int = 500) -> str:
    try:
        age_hours   = int(age_hours)   if age_hours   is not None else 24
        max_entries = int(max_entries) if max_entries is not None else 500

        checkpoint_ts = _load_checkpoint()
        entries = _collect_entries(age_hours, max_entries, checkpoint_ts)

        if not entries:
            return (
                f"No cold log entries to summarize "
                f"(age_hours={age_hours}, checkpoint={checkpoint_ts or 'none'})."
            )

        first_ts = entries[0]["timestamp_utc"]
        last_ts  = entries[-1]["timestamp_utc"]

        summary, model_name = _summarize(entries)

        # Guard against the silent-failure mode that bit the first pilot:
        # if the model returns nothing, DO NOT advance the checkpoint and
        # DO NOT write a placeholder digest entry — surface the failure so
        # the caller knows to investigate (likely a timeout, a system-only
        # prompt, or a prompt that overflowed the model's context window).
        if not summary:
            return (
                f"Model {model_name} returned an empty response for "
                f"{len(entries)} entries ({first_ts} -> {last_ts}). "
                f"Checkpoint NOT advanced, digest NOT written. "
                f"Check that the model is loaded, its context window "
                f"can hold the user message (prompt capped at ~12k chars), "
                f"and the 300s timeout was sufficient."
            )

        if dry_run:
            return (
                f"[DRY RUN] Would summarize {len(entries)} entries "
                f"({first_ts} → {last_ts}) using {model_name}.\n"
                f"Checkpoint NOT advanced.\n\n"
                f"--- Preview ---\n{summary}\n--- End preview ---"
            )

        _append_digest(entries, summary, model_name, first_ts, last_ts)
        _save_checkpoint(last_ts, len(entries))

        return (
            f"Appended digest for {len(entries)} entries "
            f"({first_ts} → {last_ts}) to {_DIGEST_FILE.relative_to(_ROOT)}. "
            f"Checkpoint advanced."
        )

    except Exception as e:
        return f"Error in log_summarizer: {e}"
