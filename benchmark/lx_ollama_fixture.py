# lx_ollama_fixture.py
#
# Phase F (UPGRADE_PLAN_5 sec 4) -- benchmark / unit-test fixture that
# satisfies the OllamaClient.chat protocol without hitting a real
# Ollama server. The principle (Kevin, D-20260425):
#
#   "I don't want to build a harness as smart as the llm."
#
# So the stub does the dumbest possible thing that keeps Phase A
# determinism intact and the cognate dispatch path exercised: it reads
# the bandit hint list out of the system prompt (which lx_Reason
# always renders, even when the list is empty) and emits a fenced-JSON
# tool call for the top-1 hint. If the hint list is empty, it falls
# back to the first atomic primitive in ATOMIC_PRIMITIVES so the loop
# still advances. lx_Reason.execute then backfills safe default args,
# so the stub never has to know each tool's argument schema.
#
# A test that wants different behaviour passes one of:
#   - `fixed_tool="<name>"`        -> always emits that tool.
#   - `fixed_response="<text>"`    -> returns the raw text verbatim
#                                      (useful for prose-only or
#                                      malformed-JSON regression tests).
#   - `responder=callable`         -> receives (system_prompt, messages)
#                                      and returns the chat content.
#
# The stub's chat() returns (content, truncated=False) so it slots
# directly into ServoCore(ollama=StubOllama()) without any
# call-site changes.
#
# D-20260426 (Phase F section 4).

from __future__ import annotations

import json
import re
from typing import Callable, List, Optional, Tuple

from core.lx_cognates import ATOMIC_PRIMITIVES


# Regex extracts the bullet-list of bandit hints from the REASON
# system prompt. lx_Reason._build_system_prompt renders each hint as
# "  - <toolname>" on its own line; we capture every such line under
# the "in order:" header until a blank line ends the block.
_HINT_BLOCK_RE = re.compile(
    r"in order:\n((?:\s*-\s*\S+\n)+)",
    re.IGNORECASE,
)
_HINT_LINE_RE = re.compile(r"-\s*(\S+)")


class StubOllama:
    """Drop-in stand-in for OllamaClient in benchmarks and unit tests.

    Only the surface lx_Reason.execute exercises is implemented:
      - `chat(system_prompt, messages, timeout=300, cancel_event=None)`
        returning a `(content, truncated)` tuple.
      - `model` attribute (some tools read it for logging).
      - `temperature`, `num_predict` attributes (system_config tool
        reads these for the GET path).

    Behaviour by construction order:
      1. If `responder` is callable, it wins -- it receives
         (system_prompt, messages) and returns the raw response text.
      2. Else if `fixed_response` is non-empty, return it verbatim.
      3. Else if `fixed_tool` is set, emit a fenced JSON call for it.
      4. Else extract the bandit top-1 from the system prompt and emit
         a fenced JSON call for it.
      5. Else emit a fenced JSON call for the first atomic primitive
         (preserves Phase A determinism on a fresh boot).
    """

    def __init__(
        self,
        *,
        fixed_tool: Optional[str] = None,
        fixed_response: Optional[str] = None,
        responder: Optional[Callable[[str, list], str]] = None,
        model: str = "lx-stub:0.0",
        temperature: float = 0.0,
        num_predict: int = 256,
    ):
        self._fixed_tool = fixed_tool
        self._fixed_response = fixed_response
        self._responder = responder

        # Attributes mirrored from OllamaClient so tools that read
        # `loop.ollama.model` etc. don't crash under the stub.
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict

        # Capture last call for assertion in tests.
        self.last_system_prompt: Optional[str] = None
        self.last_messages: Optional[list] = None
        self.call_count: int = 0

    # ------------------------------------------------------------------
    # OllamaClient surface
    # ------------------------------------------------------------------

    def chat(
        self,
        system_prompt: str,
        messages: list,
        timeout: int = 300,
        cancel_event=None,
    ) -> Tuple[str, bool]:
        """Mirror of OllamaClient.chat -- returns (content, truncated).

        Truncated is always False for the stub: the response is built
        from a fixed-size template so num_predict can't fire.
        """
        self.last_system_prompt = system_prompt
        self.last_messages = list(messages or [])
        self.call_count += 1

        if self._responder is not None:
            content = self._responder(system_prompt, list(messages or []))
            return str(content or ""), False

        if self._fixed_response is not None:
            return self._fixed_response, False

        tool_name = self._fixed_tool or self._extract_top_hint(system_prompt)
        if not tool_name or tool_name not in ATOMIC_PRIMITIVES:
            # Last-resort default. The first ATOMIC_PRIMITIVE is
            # `file_read` which is read-only and idempotent under
            # lx_Reason._default_args_for.
            tool_name = ATOMIC_PRIMITIVES[0]

        return self._fenced_call(tool_name), False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_top_hint(self, system_prompt: str) -> Optional[str]:
        """Parse the bandit hint list out of the REASON system prompt.

        Returns the first hint name, or None when the list is empty
        (REASON renders the "no prior procedural wins" branch).
        """
        if not system_prompt:
            return None
        block_match = _HINT_BLOCK_RE.search(system_prompt)
        if not block_match:
            return None
        first_line = _HINT_LINE_RE.search(block_match.group(1))
        return first_line.group(1) if first_line else None

    @staticmethod
    def _fenced_call(tool_name: str) -> str:
        """Render a minimal fenced-JSON tool call.

        We intentionally emit empty args; lx_Reason.execute backfills
        safe defaults via _default_args_for, so the stub never has to
        know each tool's argument schema. parse_tool_call accepts the
        empty-args shape (any dict with a "tool" key passes the gate).
        """
        payload = json.dumps({"tool": tool_name, "args": {}})
        return f"```json\n{payload}\n```"


# A module-level convenience for tests that just need *something* in
# place. Equivalent to `StubOllama()` but reads slightly nicer at the
# call site: `core = ServoCore(ollama=lx_ollama_fixture.default())`.
def default(**kwargs) -> StubOllama:
    return StubOllama(**kwargs)


__all__ = ["StubOllama", "default"]
