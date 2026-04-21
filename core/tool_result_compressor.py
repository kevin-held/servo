"""
tool_result_compressor — INTEGRATE-time compression of large tool results.

Companion to core/history_compressor.py. Where history_compressor rolls up
*older* raw conversation turns into a single narrative paragraph,
tool_result_compressor works per-turn: when a single tool call returns a
payload big enough to dominate a conversation row, the raw result is
condensed into a short recap BEFORE it lands in the conversation_history
table. The followup round in `_act` still sees the full raw result (so
the model's immediate response isn't degraded); compression applies only
to what gets persisted for future CONTEXTUALIZE pulls.

Why a separate pass from history_compressor
-------------------------------------------
history_compressor is a two-sided design that only fires after 2× the
conversation_history cap of uncompressed turns have accumulated. By
that point a single 14k-char `filesystem:read` dump has already:
  - ridden along in the Ollama message list for up to 2× cap turns,
  - eaten its share of context budget on every one of those turns, and
  - possibly been truncated or tail-preserved by the kernel's last-resort
    trim once history_compressor finally gets to it.
Per-turn compression catches that bloat at the source, so the raw tool
payload never enters the message list in the first place on subsequent
cycles. The two passes are complementary, not redundant.

What this module owns
---------------------
  * The per-turn trigger predicate — compress when
    `len(result_text) > _COMPRESS_THRESHOLD_CHARS`.
  * The tool-result-specific prompt shape (extract the signal: what the
    tool did, the target, the outcome class, any error messages verbatim;
    drop verbose enumeration).
  * A compressed-line wrapper so the model can tell, when reading history
    back, that it's looking at a condensation rather than raw output:
    `"Tool result (<tool>, compressed <orig>→<new> chars):\n<summary>"`.

What this module does NOT own
-----------------------------
  * The kernel — `tools.summarizer.summarize` owns Ollama wiring, timeout
    policy, probe behavior, and last-resort trim.
  * The decision of WHEN in the loop to call — that lives in
    core/loop.py::_integrate, which calls `maybe_compress_tool_result`
    directly just before writing the tool-result conversation turn.
  * The per-tool pagination / summarize flags (filesystem:read,
    youtube_transcript, scholar_runner). Those are upstream caps on the
    raw tool output; this module is a downstream safety net for tools
    that don't have their own size discipline.

Failure semantics
-----------------
  * Input below threshold → return `(None, None)`. Caller uses the raw
    result as-is. No log, no counter.
  * Kernel returns empty string → log WARNING, return `(None, None)`.
    Caller falls back to raw. No counter increment (counter tracks only
    *successful* compressions).
  * Kernel raises → log ERROR, return `(None, None)`. Caller falls back
    to raw. No counter increment.

Design rationale: decisions.md D-20260420-01.
"""

from __future__ import annotations

from typing import Any

from core.sentinel_logger import get_logger
from tools.summarizer import summarize as _kernel_summarize


from core.identity import get_system_defaults

# ── Tunables ──────────────────────────────────────────────

_DEFAULTS = get_system_defaults().get("defaults", {})

# Minimum raw-result size that triggers compression.
_COMPRESS_THRESHOLD_CHARS = int(_DEFAULTS.get("tool_result_compression_threshold", 4000))

# Cap passed to the kernel as max_input_chars.
_MAX_KERNEL_INPUT_CHARS = get_system_defaults().get("summarizer", {}).get("MAX_INPUT_CHARS", 12000)

# Target length embedded in the system_rules.
_SUMMARY_TARGET_CHARS = int(_DEFAULTS.get("tool_result_compression_target_chars", 500))


# ── Prompt building ───────────────────────────────────────

def _build_system_rules(tool_name: str, target_chars: int = _SUMMARY_TARGET_CHARS) -> str:
    """The HARD RULES block for tool-result compression.

    Parameterized by tool_name so the model knows what kind of payload
    it's looking at (a 12k-char directory listing vs a 12k-char log
    digest want subtly different compressions). The rules themselves
    are the same — the name just gives the model a frame of reference
    at the top of the rules block.
    """
    from core.identity import get_identity
    identity = get_identity()
    agent_name = identity.get("agent_name", "Servo")

    return (
        f"You compress a single tool result for {agent_name} (an "
        f"autonomous local-AI agent). The tool was `{tool_name}`. Your "
        f"audience is a future version of {agent_name} — it will read "
        "your recap in place of the raw payload when reconstructing "
        "what happened on this turn.\n\n"
        "HARD RULES:\n"
        "1. Lead with the outcome class: SUCCESS / FAILURE / PARTIAL. "
        "If the tool returned an error string, quote the error message "
        "VERBATIM — do not paraphrase errors, they're load-bearing for "
        "debugging.\n"
        "2. Name the target(s) the tool operated on: file paths, URLs, "
        "task ids, search queries, whatever identifies the work. Keep "
        "paths exactly as written — never abbreviate or normalize.\n"
        "3. Preserve structured counts and totals: \"listed 47 files\", "
        "\"matched 12 of 200 rows\", \"read block 2 of 5 (14932 chars)\". "
        "Prefer the tool's own numbers over your estimate.\n"
        "4. Preserve the TAIL of paginated output — any `[BLOCK N OF M"
        " — call with block=N+1]` footer, `(truncated, use ...)` hint, "
        "or next-step pointer must survive verbatim, because the model "
        "relies on those cues to decide whether to call again.\n"
        "5. Drop verbose enumeration: long directory listings collapse "
        "to counts + a couple of representative names; repeated log "
        "lines collapse to \"N similar lines omitted\"; generated text "
        "collapses to a one-sentence gist.\n"
        f"6. Write ONE short paragraph — not bullets, not headings. "
        f"Target ~{target_chars} characters. No preamble "
        "(\"Here is a summary…\"), no trailing meta-commentary, no "
        "\"as requested\"."
    )


def _build_user_content(tool_name: str, args: Any, result_text: str) -> str:
    """Assemble the kernel's user_content.

    Includes tool name + args so the model has full context for what
    the raw payload represents. Args are rendered with `json.dumps` so
    dicts / lists come through as readable text without quoting noise.
    """
    import json
    try:
        args_rendered = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args_rendered = repr(args)

    return (
        f"=== TOOL CALL ===\n"
        f"tool: {tool_name}\n"
        f"args: {args_rendered}\n\n"
        f"=== RAW RESULT ({len(result_text)} chars) ===\n"
        f"{result_text}\n\n"
        f"=== END ===\n\n"
        "Write the compressed recap paragraph now."
    )


# ── Public entry point ────────────────────────────────────

def maybe_compress_tool_result(
    tool_name: str,
    args: Any,
    tool_result: Any,
    *,
    threshold_chars: int = _COMPRESS_THRESHOLD_CHARS,
    target_chars: int = _SUMMARY_TARGET_CHARS,
) -> tuple[str | None, dict | None]:
    """Compress a tool result if it's over threshold, else return (None, None).

    Parameters
    ----------
    tool_name : str
        The name of the tool that produced the result. Passed into the
        system_rules and into the compressed-line wrapper so the model
        can tell what kind of payload it's looking at.
    args : Any
        The args dict the tool was called with. Rendered into the user
        content so the model has full context on what the raw payload
        represents.
    tool_result : Any
        The raw result (anything `str()`-able). Stringified inside.
    threshold_chars : int, keyword-only
        Override the default compression trigger. Tests pin this lower.

    Returns
    -------
    (wrapped_text, report) : tuple[str | None, dict | None]
        On successful compression: `wrapped_text` is the line-ready
        string the caller should persist in place of the raw result
        (already prefixed with a compression marker — see module
        docstring). `report` is a telemetry dict with `orig_chars`,
        `new_chars`, `model_used`, and `tool_name`.

        On skip (below threshold, empty response, kernel exception):
        `(None, None)`. Caller should persist the raw result unchanged.
    """
    logger = get_logger()

    result_text = str(tool_result) if tool_result is not None else ""
    orig_chars = len(result_text)

    # Below threshold → pass through raw. This is the common case for
    # short tool results (task list, filesystem:list on small dirs,
    # math, most tool_result payloads under normal use).
    if orig_chars <= threshold_chars:
        return None, None

    system_rules = _build_system_rules(tool_name, target_chars=target_chars)
    user_content = _build_user_content(tool_name, args, result_text)

    try:
        summary_text, model_used = _kernel_summarize(
            user_content,
            system_rules,
            max_input_chars=_MAX_KERNEL_INPUT_CHARS,
        )
    except Exception as e:
        # Compressor must never crash the loop. Fall back to raw.
        logger.log("ERROR", "loop.tool_result_compressor",
                   f"kernel call raised {type(e).__name__}: {e}",
                   context={"tool": tool_name, "orig_chars": orig_chars})
        return None, None

    if not summary_text:
        # Empty response: keep raw payload, log WARNING. Unlike
        # history_compressor we don't bother with a backoff — tool
        # results are per-turn, so the next call is a fresh input
        # shape and there's no retry-storm risk.
        logger.log("WARNING", "loop.tool_result_compressor",
                   "kernel returned empty summary — keeping raw result",
                   context={"tool":       tool_name,
                            "orig_chars": orig_chars,
                            "model_used": model_used})
        return None, None

    new_chars = len(summary_text)
    wrapped = (
        f"Tool result ({tool_name}, compressed "
        f"{orig_chars}→{new_chars} chars):\n{summary_text}"
    )

    logger.log("INFO", "loop.tool_result_compressor",
               f"compressed {tool_name} result {orig_chars} → {new_chars} chars",
               context={"tool":       tool_name,
                        "orig_chars": orig_chars,
                        "new_chars":  new_chars,
                        "model_used": model_used})

    return wrapped, {
        "tool_name":  tool_name,
        "orig_chars": orig_chars,
        "new_chars":  new_chars,
        "model_used": model_used,
    }
