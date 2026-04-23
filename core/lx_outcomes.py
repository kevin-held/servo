# lx_outcomes.py
#
# Structured handshake contract between lx_Act and lx_Reason.
# Phase C (UPGRADE_PLAN_2 §4).
#
# The raw tool_registry returns a single string (error or payload);
# ToolOutcome normalizes that into a status + channels pair so:
#   - lx_Integrate can compute reward from a known shape.
#   - lx_Reason can read stderr on the NEXT cycle to adjust plans.
#   - procedural_wins stores a JSON-serializable snapshot.
#
# Convention: tools emit errors as strings prefixed "Error:" or
# "Error in <tool>:". That's the only signal we have from the registry
# contract, so the detection logic lives here and nowhere else.

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, asdict
from typing import Any, Literal


ToolStatus = Literal["ok", "fail", "skip"]

# Covers both "Error: ..." (emitted by tools on their error paths) and
# "Error in <tool>: ..." (wrapped by tool_registry on raised exceptions).
_ERROR_PREFIX_RE = re.compile(r"^\s*Error(\s+in\s+\S+)?\s*:", re.IGNORECASE)


@dataclass
class ToolOutcome:
    """Structured result of a single atomic-primitive dispatch."""
    status: ToolStatus
    return_value: Any
    stderr: str
    latency_ms: float
    tool_name: str
    args_fingerprint: str

    @classmethod
    def from_tool_output(
        cls,
        tool_name: str,
        args: dict,
        output: str,
        latency_ms: float,
    ) -> "ToolOutcome":
        """Wrap a tool_registry.execute() result.

        Output starting with "Error:" or "Error in <tool>:" is routed to
        stderr with status="fail". Anything else is routed to return_value
        with status="ok". The args_fingerprint is a short content hash the
        reward function uses to dedupe identical calls across cycles.
        """
        is_fail = bool(_ERROR_PREFIX_RE.match(output or ""))
        try:
            args_fp = hashlib.sha1(
                json.dumps(args or {}, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
        except (TypeError, ValueError):
            args_fp = "unhashable"

        if is_fail:
            return cls(
                status="fail",
                return_value=None,
                stderr=output or "",
                latency_ms=float(latency_ms),
                tool_name=tool_name,
                args_fingerprint=args_fp,
            )
        return cls(
            status="ok",
            return_value=output,
            stderr="",
            latency_ms=float(latency_ms),
            tool_name=tool_name,
            args_fingerprint=args_fp,
        )

    @classmethod
    def skip(cls, tool_name: str, reason: str) -> "ToolOutcome":
        """Outcome for a tool that was resolved but intentionally not run.

        Used when lx_Reason's chosen tool is excluded by the Phase C
        atomic-primitive filter (D-20260422-05 TOOL_IS_SYSTEM) or when the
        dispatch surface is unavailable. status="skip" lets the reward
        function award partial credit (P=0.3) without flagging a failure.
        """
        return cls(
            status="skip",
            return_value=None,
            stderr=reason,
            latency_ms=0.0,
            tool_name=tool_name,
            args_fingerprint="",
        )

    def to_dict(self) -> dict:
        """JSON-serializable snapshot for delta merging / ChromaDB storage."""
        return asdict(self)
