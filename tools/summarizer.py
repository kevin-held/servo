"""
summarizer — Shared kernel for model-driven text condensation.

This module is the factored-out core of the summarization logic that the
log_summarizer pilot (D-20260417-06) proved out, now made reusable so the
upcoming INTEGRATE-time auto-compression hook and a future agent-facing
`summarize` tool can share one prompt-shape / client / timeout strategy
instead of drifting copies.

What the kernel owns:
  - Detecting which Ollama model is currently loaded (unless the caller
    names one explicitly).
  - Sending a `system_rules` + `user_content` pair through
    OllamaClient.chat — the shape Ollama's /api/chat endpoint actually
    expects. A system-only call (empty messages list) produces an empty
    response on gemma 26B and several other Ollama models; this was the
    silent failure that burned the first log_summarizer pilot.
  - A longer default timeout (300s) than the main chat loop, because
    local 26B models summarizing ~12k-char payloads can legitimately take
    60-120s without being stuck. 60s was silently timing out in the pilot.
  - Last-resort char trim on user_content so a caller that forgot to trim
    doesn't blow past the model's context window. Callers with priority
    rules (keep incidents, drop routine) must trim BEFORE calling
    `summarize()`; the kernel's trim is a blunt tail-preserve-head-drop.
  - Empty-response passthrough: `summarize()` returns `("", model_name)`
    when the model produced nothing, and lets the caller decide what that
    means. log_summarizer treats it as fatal (no digest written, no
    checkpoint advance). The upcoming INTEGRATE hook will treat it as
    soft (keep the raw payload in history, log a WARNING).

What the kernel does NOT own:
  - Prompt content. Each caller builds its own `system_rules` string
    with its own rules-of-compression; the kernel ships no default rules.
  - Input shaping. Log entries get bucketed into INCIDENTS/ROUTINE by
    log_summarizer before reaching `summarize()`. A file summarizer will
    pre-trim to headings-plus-excerpts. A tool-result compressor may
    strip ANSI codes and line-number prefixes. All of that is caller
    territory.
  - Destination. The kernel returns text; it never writes files, never
    updates checkpoints, never touches disk. Callers decide where the
    summary lives.
  - Tool-registry metadata. There is no TOOL_NAME / TOOL_DESCRIPTION /
    execute() here. The module is imported directly, not invoked via the
    agent's tool-call contract. The agent-facing `summarize` tool (Phase 3)
    will be a separate thin module in this same folder.

Design rationale recorded in decisions.md D-20260418-10.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so `from core.ollama_client import
# OllamaClient` resolves regardless of how the caller imported us.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# Default chat timeout for summarization work. Deliberately larger than
# the main loop's per-turn timeout — a 26B model compressing 12k chars
# takes 60-120s locally, and a 60s cap was silently timing out in the
# log_summarizer pilot.
_DEFAULT_TIMEOUT = 300

# Default cap on user_content size. Chosen to fit comfortably inside an
# 8k-token context window (roughly ~32k chars total) leaving headroom
# for system_rules and the model's response. Callers should pre-trim to
# respect their own priority rules; this is the last-resort guard.
_DEFAULT_MAX_INPUT_CHARS = 12_000

# Fallback model name when Ollama's /api/ps probe fails. Matches Kevin's
# baseline setup; callers can override by passing `model=...` to summarize().
_DEFAULT_FALLBACK_MODEL = "gemma4:26b"


def detect_loaded_model(fallback: str = _DEFAULT_FALLBACK_MODEL) -> str:
    """Return the name of the model currently loaded in Ollama.

    Queries http://localhost:11434/api/ps and returns the name of the
    first loaded model. Falls back to `fallback` if:
      - Ollama isn't reachable
      - The request times out (2s probe)
      - No models are loaded
      - The response doesn't carry a parseable 'name' field

    The 2s probe timeout is intentionally tight: if Ollama is slow to
    respond to /api/ps, the downstream chat() call is going to be very
    slow too, and we'd rather fail fast into the fallback than spend the
    caller's budget waiting for a probe.
    """
    try:
        import requests
        r = requests.get("http://localhost:11434/api/ps", timeout=2)
        models = (r.json() or {}).get("models", [])
        if models:
            return models[0].get("name", fallback)
    except Exception:
        pass
    return fallback


def summarize(
    user_content: str,
    system_rules: str,
    *,
    model: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    max_input_chars: int = _DEFAULT_MAX_INPUT_CHARS,
) -> tuple[str, str]:
    """Run a single-shot summarization against a loaded Ollama model.

    Parameters
    ----------
    user_content : str
        The text to summarize, pre-shaped by the caller. If longer than
        `max_input_chars`, the TAIL is kept and the head is dropped
        (last-resort trim). Callers with priority-aware rules should
        trim intentionally before calling this function; this trim is a
        fallback, not a feature.
    system_rules : str
        The system-prompt scaffolding — tone, format, hard rules. Must be
        non-empty. A `ValueError` is raised if empty because shipping
        empty rules to a summarizer is almost always a wiring bug (the
        caller forgot to build their prompt).
    model : str | None, keyword-only
        Explicit model name. If None, auto-detect via
        `detect_loaded_model()`. Pass `model="gemma4:26b"` (or similar)
        to pin to a specific model regardless of what Ollama reports as
        loaded — useful if the caller wants deterministic summarizer
        behavior across reloads.
    timeout : int, keyword-only
        Chat timeout in seconds. Default 300. Smaller/faster models can
        safely pass e.g. 60; do not drop below that without evidence that
        the model actually finishes in less time on the target payload.
    max_input_chars : int, keyword-only
        Hard cap applied to `user_content` as a last-resort trim.

    Returns
    -------
    (summary, model_used) : tuple[str, str]
        `summary` is the model's response, `.strip()`-ed. May be "" if
        the model returned an empty string — the caller decides how to
        handle that. The kernel does NOT retry, does NOT raise, and does
        NOT log on empty response; it just returns the empty string and
        lets the caller's error model take over.
        `model_used` is the resolved model name (after auto-detection or
        fallback). Callers that cite the model in their output (e.g. a
        digest header or a history footer) should read this from the
        return value rather than trusting the `model=` input.

    Raises
    ------
    ValueError
        If `system_rules` is empty. The kernel refuses to run an
        unsystemed call because that's almost always a wiring bug.
    """
    # Hardfail on empty system_rules — shipping an empty rules block is
    # almost always a caller-side wiring bug, and a system-only chat
    # call with no rules is the worst of both worlds (model doesn't know
    # what shape to produce, and we don't have a user turn to react to).
    if not system_rules:
        raise ValueError("summarize() requires a non-empty system_rules")

    # Resolve the model name ONCE, up front, so the return value's
    # `model_used` matches what we actually sent even on the empty-input
    # early-return below.
    model_name = model or detect_loaded_model()

    # Empty input is a no-op — nothing to summarize. Return empty summary
    # with the resolved model name so the caller can still cite it if it
    # wants to log "summarizer returned nothing because input was empty".
    if not user_content:
        return "", model_name

    # Last-resort trim: preserve the TAIL. Callers with smarter priority
    # rules (e.g. log_summarizer's incidents-first rule) should trim
    # BEFORE calling summarize(); this fires only when the caller
    # neglected to cap the input or deliberately yielded to the default.
    if len(user_content) > max_input_chars:
        user_content = user_content[-max_input_chars:]

    # Import lazily so test code can stub or skip this path without
    # dragging the full Ollama client into scope at module load.
    from core.ollama_client import OllamaClient
    client   = OllamaClient(model=model_name)
    messages = [{"role": "user", "content": user_content}]
    content, _ = client.chat(system_rules, messages, timeout=timeout)
    return (content or "").strip(), model_name
