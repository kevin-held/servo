# tool_call_parser.py
#
# Phase F (UPGRADE_PLAN_5 sec 3) -- standalone tool-call parser extracted
# from `core/loop.py._parse_tool_call` and `_strip_tool_calls` so the
# Cognate dispatch surface (specifically lx_Reason / lx_Act) can call
# the same parser the legacy CoreLoop chat path uses, without importing
# loop.py and without duplicating the schema across two implementations.
#
# Why a separate module?
#   - The "Keep No-Write" policy on core/loop.py is in force; we cannot
#     hoist these methods out of the class without editing loop.py.
#     Instead we mirror the logic textually here. Phase G+ may rewire
#     loop.py to delegate to this module; for now it stays a duplicate.
#   - lx_Reason needs to read a fenced-JSON tool call out of an LLM
#     response without dragging the rest of CoreLoop's machinery in.
#     The parser is a small enough surface (one regex pass, four
#     fallback strategies) that a plain function is the right shape.
#
# Contract:
#   parse_tool_call(text: str) -> dict | None
#     Returns the decoded tool-call dict (always {"tool": str, "args": dict})
#     or None if no valid call is present. Strips leading <think> blocks,
#     prefers fenced JSON, falls back to brace scanning, then to four
#     unescaping strategies for common LLM hallucinations.
#
#   parse_tool_calls(text: str) -> list[dict]
#     v1.8.1 (D-20260502-01) -- multi-call variant that returns *every*
#     valid fenced-JSON tool call in the response, in emission order.
#     Empty list when no calls are present. parse_tool_call now thin-
#     shims `parse_tool_calls(...)[0] if any else None` for back-compat.
#     The chain dispatcher in lx_Act enforces a hard cap (2) and a
#     bookkeeping-tail whitelist; the parser itself is permissive and
#     returns the full list so the caller can decide.
#
#   strip_tool_calls(text: str) -> str
#     Removes Markdown-fenced JSON blocks from a string so the remaining
#     prose can be surfaced to chat as the model's response. Mirrors the
#     loop.py helper of the same name.
#
# Determinism: pure functions, no I/O, no side effects, no state. Safe
# to call from the Cognate loop or from the benchmark harness.
#
# D-20260426 (Phase F section 3).

from __future__ import annotations

import json
import re
from typing import List, Optional


# ---------------------------------------------------------------------------
# Internal helper -- single-attempt JSON decode + shape check.
# ---------------------------------------------------------------------------

def _try_parse(s: str) -> Optional[dict]:
    """Attempt to JSON-decode `s` and validate it as a tool call.

    A valid tool call is a dict with a "tool" key. The "args" key is
    conventional but not enforced here -- callers that require args
    handle that downstream.

    Returns the decoded dict on success, None on any failure (decode
    error, non-dict result, missing "tool" key).
    """
    try:
        p = json.loads(s)
        if isinstance(p, dict) and "tool" in p:
            return p
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _try_all_strategies(json_str: str) -> Optional[dict]:
    """Run the four-strategy decode ladder against a single JSON blob.

    Extracted from the original parse_tool_call body so both the
    singular and plural public APIs share the same hallucination-
    tolerant parse path. Strategies, in order:
      (a) direct parse
      (b) trailing-bracket trim (handles "}}}" hallucinations)
      (c) Windows-path escape fixup (C:\\Users style backslashes)
      (d) multiline-string newline escape (combines with (c))
    """
    # 1. Direct parse.
    parsed = _try_parse(json_str)
    if parsed:
        return parsed

    # 2. Trailing bracket trim.
    temp_str = json_str
    for _ in range(5):
        if temp_str.endswith("}"):
            temp_str = temp_str[:-1]
            parsed = _try_parse(temp_str + "}")
            if parsed:
                return parsed

    # 3. Windows-path escape fixup.
    fixed_str = re.sub(r'\\(?![\"\\/bfnrtu])', r'\\\\', json_str)
    parsed = _try_parse(fixed_str)
    if parsed:
        return parsed

    # 4. Multiline-string newline escape (atop (3)).
    fixed_str = fixed_str.replace('\n', '\\n').replace('\r', '\\r')
    parsed = _try_parse(fixed_str)
    if parsed:
        return parsed

    return None


def parse_tool_calls(text: str) -> List[dict]:
    """Extract every fenced-JSON tool call from an LLM response.

    v1.8.1 (D-20260502-01) -- multi-call variant. Returns calls in
    emission order so the dispatcher can honor "do work, then mark
    complete" patterns the model naturally emits.

    Procedure:
      1. Strip leading <think>...</think> blocks.
      2. Find every Markdown-fenced JSON block via re.finditer (NOT a
         single re.search, which is what the singular parser used).
      3. For each block, run the four-strategy decode ladder. Successful
         decodes append to the result list; failures are silently
         dropped (a malformed block in the middle of a chain shouldn't
         poison the calls before/after it).
      4. If no fenced blocks were found, fall back to the brace-scan
         path so a model that emitted a single call without fences
         still produces a one-element list. (We do *not* attempt to
         scan for multiple unfenced calls -- the brace heuristic is too
         lossy to demarcate call boundaries.)

    Returns [] when no valid call is present. Caller (lx_Act) is
    responsible for cap + whitelist enforcement; the parser itself
    is permissive.
    """
    if not text:
        return []

    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    calls: List[dict] = []
    fenced = list(re.finditer(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL))
    if fenced:
        for m in fenced:
            parsed = _try_all_strategies(m.group(1))
            if parsed:
                calls.append(parsed)
        return calls

    # No fenced blocks -- fall back to brace scanning for a single call.
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and start < end:
        json_str = text[start:end + 1]
    else:
        json_str = text
    parsed = _try_all_strategies(json_str)
    if parsed:
        calls.append(parsed)
    return calls


def parse_tool_call(text: str) -> Optional[dict]:
    """Extract a single tool call from an LLM response.

    v1.8.1 thin shim over `parse_tool_calls`: returns the first call
    when one or more is present, else None. Preserved for back-compat
    with any caller that expects a single-call shape (legacy chat path,
    tests written before the chain dispatcher landed).

    Mirrors `core.loop.CoreLoop._parse_tool_call`. Procedure (delegated):

      1. Strip leading <think>...</think> blocks.
      2. Prefer fenced JSON; fall back to brace scanning.
      3. Run the four-strategy decode ladder
         (direct / trailing-trim / Windows-path / multiline).

    Returns the decoded dict or None.
    """
    calls = parse_tool_calls(text)
    return calls[0] if calls else None


def strip_tool_calls(text: str) -> str:
    """Remove Markdown-fenced JSON blocks from `text`, leaving prose.

    Mirrors `core.loop.CoreLoop._strip_tool_calls`. Useful for
    surfacing the model's prose response to the chat panel after a
    tool call has been extracted, so the user sees the explanation
    without the JSON clutter.

    The regex matches ```json ... ``` or ``` ... ``` with a JSON-
    object body. Multiple blocks are stripped. Leading/trailing
    whitespace is trimmed.
    """
    if not text:
        return ""
    text = re.sub(r'```(?:json)?\s*\{.*\}\s*```', '', text, flags=re.DOTALL)
    return text.strip()


__all__ = ["parse_tool_call", "parse_tool_calls", "strip_tool_calls"]
