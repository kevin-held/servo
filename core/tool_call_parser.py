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
from typing import Optional


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

def parse_tool_call(text: str) -> Optional[dict]:
    """Extract a tool call from an LLM response.

    Mirrors `core.loop.CoreLoop._parse_tool_call` so the Cognate
    dispatch surface can use the same parser the legacy chat path
    uses. Procedure:

      1. Strip leading <think>...</think> blocks (R1-style chain-of-
         thought) so they can't confuse the JSON-block matcher.
      2. Prefer a fenced JSON block (```json ... ``` or ``` ... ```).
      3. Fall back to scanning for the first '{' and last '}'.
      4. Try four parse strategies in order:
            (a) direct parse
            (b) trailing-bracket trim (handles "}}}" hallucinations)
            (c) Windows-path escape fixup (C:\\Users style backslashes)
            (d) multiline-string newline escape

    Returns the decoded dict (always with a "tool" key) or None if no
    valid call is present.
    """
    if not text:
        return None

    # Strip <think>...</think> block if present -- the chain-of-thought
    # often contains brace-rich pseudo-JSON that would otherwise win
    # the fenced-block match.
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # Try to find a JSON block specifically. The (?:json)? makes the
    # language tag optional; ``` alone with a JSON body is accepted.
    match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # Fallback: find the first '{' and the last '}'. Greedy on
        # purpose -- a tool call may contain nested objects.
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and start < end:
            json_str = text[start:end + 1]
        else:
            json_str = text

    # 1. Attempt direct parse.
    parsed = _try_parse(json_str)
    if parsed:
        return parsed

    # 2. Attempt trailing bracket trimming (handles hallucinations
    #    like "}}}"). Up to five iterations -- more than that and the
    #    payload is truly malformed.
    temp_str = json_str
    for _ in range(5):
        if temp_str.endswith("}"):
            temp_str = temp_str[:-1]
            parsed = _try_parse(temp_str + "}")
            if parsed:
                return parsed

    # 3. Fallback: models frequently output unescaped Windows paths
    #    like C:\Users. JSON requires backslashes to be escaped; the
    #    regex turns lone backslashes into doubled ones unless they're
    #    already part of a valid escape (\\, \", \/, \b, \f, \n, \r,
    #    \t, \uXXXX).
    fixed_str = re.sub(r'\\(?![\"\\/bfnrtu])', r'\\\\', json_str)
    parsed = _try_parse(fixed_str)
    if parsed:
        return parsed

    # 4. Fallback: multiline unescaped strings (raw newlines inside a
    #    JSON string literal). Building on top of (3) so both fixups
    #    apply.
    fixed_str = fixed_str.replace('\n', '\\n').replace('\r', '\\r')
    parsed = _try_parse(fixed_str)
    if parsed:
        return parsed

    return None


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


__all__ = ["parse_tool_call", "strip_tool_calls"]
