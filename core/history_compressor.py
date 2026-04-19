"""
history_compressor — Phase 2 consumer of the shared summarization kernel.

When conversation_history grows long enough that the oldest turns risk
blowing the model's context window, this module rolls them up into a
single narrative paragraph and stores it in the `conversation_summary`
table. The runtime then:

  1. Renders the paragraph as a `[PRIOR CONTEXT]` block in the system
     prompt (see `_build_system_prompt` in core/loop.py).
  2. Filters out conversation turns already covered by the summary when
     building the Ollama message list (see `_build_messages`).

The net effect: the model retains continuity ("you asked me about X, I
ran tool Y and got Z") without us sending the full transcript each turn.

What this module owns
---------------------
  * The conversation-specific prompt shape (narrative paragraph, not
    bullets — a dense recap reads better than a structured report inside
    a `[PRIOR CONTEXT]` block).
  * The trigger predicate — compression fires when uncompressed raw
    turns >= 2 × `self.conversation_history`. That scales with the
    hardware throttle (which reduces the cap under load) and stays
    proportional across tuning changes.
  * Turn formatting — how each raw turn is rendered for the kernel.
  * A backoff so an empty response doesn't cause a retry storm on the
    very next turn: after a failure, require `history_cap` more turns
    before trying again.

What this module does NOT own
-----------------------------
  * The kernel itself — `tools.summarizer.summarize` is the one place
    that owns the Ollama client, timeout policy, and probe behavior.
  * Destination — this module writes into `conversation_summary` via
    the `StateStore` helpers; it doesn't touch files.
  * The agent tool contract — there is no `TOOL_NAME` / `execute()`
    here. The runtime calls `maybe_compress()` directly from the
    INTEGRATE step.

Failure semantics
-----------------
  * Empty response from the kernel → log WARNING, do NOT save a summary,
    do NOT advance the cutoff. Record the failure turn count so the next
    attempt waits until `history_cap` more turns have landed.
  * Exception (e.g. kernel blows up, DB error) → log ERROR and return
    None. The loop keeps going; compression is belt-and-suspenders, not
    load-bearing.

See decisions.md D-20260419-01 for the full rationale.
"""

from __future__ import annotations

from typing import Any

from core.sentinel_logger import get_logger
from tools.summarizer import summarize as _kernel_summarize


# ── Tunables ──────────────────────────────────────────────

# Compression fires when uncompressed turns reach this multiple of the
# runtime conversation_history cap. 2× means: at the default cap of 15,
# we compress at 30 uncompressed turns and leave the newest 15 raw.
_TRIGGER_MULTIPLIER = 2

# After a failed attempt (empty response), wait for this many more turns
# before retrying. Measured in conversation_history caps so a tight-cap
# run (e.g. hardware-throttled to 7) backs off proportionally.
_FAILURE_BACKOFF_MULTIPLIER = 1

# Key under which we stash the uncompressed-turn-count of the last
# failed attempt. Lives in the `state` key-value table.
_FAILURE_STATE_KEY = "compression_last_failed_turn_count"

# Target length of the summary paragraph. The kernel's last-resort trim
# is for the INPUT side; this is an informational guideline embedded in
# the system_rules so the model produces something appropriately terse.
# Not a hard cap — if the model runs long, we keep what we get.
_SUMMARY_TARGET_CHARS = 800


# ── Prompt building ───────────────────────────────────────

def _format_turn(turn: dict) -> str:
    """Render one conversation row for the kernel's user_content block.

    Kept tight: "[role] content". Content is clipped per-turn to keep a
    single pathological long turn from dominating the summary input.
    """
    role    = (turn.get("role")    or "?").lower()
    content = (turn.get("content") or "").strip().replace("\n", " ")
    # Per-turn content cap. 1500 chars is enough to capture a typical
    # tool-result summary without letting a 20k-char filesystem:list
    # dump drown the signal. The kernel's max_input_chars is the
    # aggregate last-resort guard; this is the per-turn guard.
    if len(content) > 1500:
        content = content[:1500] + "…(truncated)"
    return f"[{role}] {content}"


def _build_system_rules() -> str:
    """The HARD RULES block for conversation-history compression.

    Kept as a module-level constant-shaped helper so a future change to
    the rules (e.g. "always quote the last user request verbatim") lands
    in one place and tests can assert on the returned string.
    """
    return (
        "You compress a sequence of chat turns between a user (Kevin) "
        "and Servo (an autonomous local-AI agent). Your audience is a "
        "future version of Servo — it will read your summary in place "
        "of the original turns to stay grounded in the conversation.\n\n"
        "HARD RULES:\n"
        "1. Preserve Kevin's requests: quote the most recent 1-2 in "
        "full; paraphrase older ones compactly. If a request was "
        "deferred or left open, say so.\n"
        "2. Preserve tool outcomes: name the tool, the target (file, "
        "url, goal), and the result class (success / failure / "
        "partial). Keep error messages verbatim when they appeared.\n"
        "3. Preserve decisions and commitments Servo made ("
        "\"I'll do X next\", \"I've recorded Y in the codex\"). These "
        "are load-bearing for continuity.\n"
        "4. Strip internal reasoning, intermediate thinking, and "
        "verbose tool payloads. \"Used filesystem:list on workspace/ "
        "(200 files)\" beats a 200-line directory listing.\n"
        "5. Write ONE narrative paragraph — not bullets, not headings. "
        f"Target ~{_SUMMARY_TARGET_CHARS} characters; overrun is fine "
        "if detail is load-bearing. No preamble (\"Here is a summary…\") "
        "and no trailing meta-commentary."
    )


def _build_user_content(
    turns: list[dict],
    prior_summary: str | None,
) -> str:
    """Assemble the kernel's user_content.

    If a prior summary exists, include it so the new summary can absorb
    it — we only keep one live summary, so the compressor must roll the
    previous one forward each cycle.
    """
    formatted = "\n".join(_format_turn(t) for t in turns)
    if prior_summary:
        return (
            "=== PRIOR SUMMARY (absorb into the new summary) ===\n"
            f"{prior_summary}\n\n"
            "=== NEW TURNS TO COMPRESS ===\n"
            f"{formatted}\n\n"
            "=== END ===\n\n"
            "Write the combined summary paragraph now."
        )
    return (
        "=== TURNS TO COMPRESS ===\n"
        f"{formatted}\n\n"
        "=== END ===\n\n"
        "Write the summary paragraph now."
    )


# ── Trigger + coverage math ───────────────────────────────

def _should_compress(
    uncompressed_count: int,
    history_cap: int,
    last_failed_at: int,
) -> bool:
    """Pure predicate: given counts, should compression fire this turn?

    Split out so tests can exercise the boundary cases (at 2×-1, at 2×,
    at 2× after a failure that wants +1×) without rigging a full state
    store.
    """
    threshold = _TRIGGER_MULTIPLIER * max(history_cap, 1)
    if uncompressed_count < threshold:
        return False
    # Backoff: after a failed attempt at N turns, wait for N+cap before
    # retrying. Without this, every user turn after the threshold would
    # trigger a fresh 300s summarize() call.
    if last_failed_at:
        backoff_target = last_failed_at + _FAILURE_BACKOFF_MULTIPLIER * max(history_cap, 1)
        if uncompressed_count < backoff_target:
            return False
    return True


# ── Public entry point ────────────────────────────────────

def maybe_compress(state: Any, history_cap: int) -> dict | None:
    """Run compression if warranted. Return a report dict, or None.

    Parameters
    ----------
    state : StateStore
        The live state store. Typed as Any to avoid a circular import;
        `core.state.StateStore` is the concrete type.
    history_cap : int
        The current `self.conversation_history` value. This is the live
        cap — if hardware_policy has throttled it down from 15 to 7,
        pass 7. The trigger scales from this value so the threshold
        follows the throttle.

    Returns
    -------
    dict | None
        None if the trigger did not fire, if there was nothing to
        compress, or if the kernel returned an empty response. A dict
        with keys {summary_id, covers_from_id, covers_to_id, turns_
        compressed, model_used, summary_length} on success. The dict is
        informational for the caller's telemetry; the persisted summary
        is authoritative.
    """
    logger = get_logger()

    # Read the current coverage cutoff. The first compression has no
    # prior summary, in which case we treat the cutoff as 0 (count
    # everything).
    prior = state.get_latest_conversation_summary()
    prior_cutoff  = prior["covers_to_id"] if prior else 0
    prior_summary = prior["summary"]      if prior else None

    uncompressed_count = state.count_conversation_turns_since(prior_cutoff)
    try:
        last_failed_at = int(state.get(_FAILURE_STATE_KEY, "0") or 0)
    except (TypeError, ValueError):
        last_failed_at = 0

    if not _should_compress(uncompressed_count, history_cap, last_failed_at):
        return None

    # Decide the range to compress. We always keep the newest
    # `history_cap` turns uncompressed so the model sees them verbatim
    # in the message list; everything older than that gets rolled up.
    newest_id = state.get_newest_conversation_id()
    if newest_id is None:
        # Conversation table is empty — shouldn't happen given the
        # uncompressed-count check above, but guard anyway.
        return None
    compress_to_id = newest_id - history_cap
    compress_from_id = prior_cutoff + 1
    if compress_to_id < compress_from_id:
        # Nothing to compress (e.g. threshold met but the only turns are
        # within the "keep the newest cap" window). Pathological but
        # possible if cap just shrank. No-op, no failure.
        return None

    turns = state.get_conversation_turns_range(compress_from_id, compress_to_id)
    if not turns:
        return None

    system_rules = _build_system_rules()
    user_content = _build_user_content(turns, prior_summary)

    try:
        summary_text, model_used = _kernel_summarize(user_content, system_rules)
    except Exception as e:
        logger.log("ERROR", "loop.history_compressor",
                   f"kernel call raised {type(e).__name__}: {e}",
                   context={"uncompressed_count": uncompressed_count,
                            "history_cap": history_cap})
        state.set(_FAILURE_STATE_KEY, str(uncompressed_count))
        return None

    if not summary_text:
        logger.log("WARNING", "loop.history_compressor",
                   "kernel returned empty summary — keeping raw turns, "
                   "backing off before next attempt",
                   context={"uncompressed_count": uncompressed_count,
                            "history_cap": history_cap,
                            "model_used": model_used})
        state.set(_FAILURE_STATE_KEY, str(uncompressed_count))
        return None

    # Success. Save the summary and clear the failure marker.
    # covers_from_id absorbs the prior summary's range if present, so
    # the metadata reflects the full coverage of this live summary.
    covers_from_id = prior["covers_from_id"] if prior else compress_from_id
    summary_id = state.save_conversation_summary(
        summary_text, covers_from_id, compress_to_id, model_used,
    )
    state.set(_FAILURE_STATE_KEY, "0")

    logger.log("INFO", "loop.history_compressor",
               f"compressed {len(turns)} turns → {len(summary_text)} chars",
               context={"summary_id":       summary_id,
                        "covers_from_id":   covers_from_id,
                        "covers_to_id":     compress_to_id,
                        "turns_compressed": len(turns),
                        "model_used":       model_used})

    return {
        "summary_id":       summary_id,
        "covers_from_id":   covers_from_id,
        "covers_to_id":     compress_to_id,
        "turns_compressed": len(turns),
        "model_used":       model_used,
        "summary_length":   len(summary_text),
    }
