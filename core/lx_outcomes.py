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


def _sha1_16(text: str) -> str:
    """16-char sha1 of the given text. Empty string -> empty string."""
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _utf8_bytes(text: str) -> int:
    """UTF-8 byte length of the given text. None-safe."""
    if not text:
        return 0
    return len(text.encode("utf-8", errors="replace"))


@dataclass
class ToolOutcome:
    """Structured result of a single atomic-primitive dispatch.

    Phase D adds fingerprint fields (return_value_sha1, stderr_sha1) plus
    byte counts so procedural_wins metadata stays flat as the dispatch
    surface grows. Full text is retained on the instance (still returned
    via to_dict); storage layers may choose to persist only the fingerprints
    in metadata and route the full text through ChromaDB's documents channel.
    """
    status: ToolStatus
    return_value: Any
    stderr: str
    latency_ms: float
    tool_name: str
    args_fingerprint: str
    # Phase D -- fingerprints for cheap procedural_wins lookups.
    return_value_sha1: str = ""
    stderr_sha1: str = ""
    return_value_bytes: int = 0
    stderr_bytes: int = 0

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

        Phase D: populates return_value_sha1 / stderr_sha1 + byte counts
        so downstream consumers can hash-index without carrying the full
        payloads in hot metadata.
        """
        is_fail = bool(_ERROR_PREFIX_RE.match(output or ""))
        try:
            args_fp = hashlib.sha1(
                json.dumps(args or {}, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
        except (TypeError, ValueError):
            args_fp = "unhashable"

        output_text = output or ""
        if is_fail:
            return cls(
                status="fail",
                return_value=None,
                stderr=output_text,
                latency_ms=float(latency_ms),
                tool_name=tool_name,
                args_fingerprint=args_fp,
                return_value_sha1="",
                stderr_sha1=_sha1_16(output_text),
                return_value_bytes=0,
                stderr_bytes=_utf8_bytes(output_text),
            )
        return cls(
            status="ok",
            return_value=output_text,
            stderr="",
            latency_ms=float(latency_ms),
            tool_name=tool_name,
            args_fingerprint=args_fp,
            return_value_sha1=_sha1_16(output_text),
            stderr_sha1="",
            return_value_bytes=_utf8_bytes(output_text),
            stderr_bytes=0,
        )

    @classmethod
    def skip(cls, tool_name: str, reason: str) -> "ToolOutcome":
        """Outcome for a tool that was resolved but intentionally not run.

        Used when lx_Reason's chosen tool is excluded by the dispatch
        surface or when the dispatch layer is unavailable. status="skip"
        lets the reward function award partial credit (P=0.3) without
        flagging a failure.
        """
        reason_text = reason or ""
        return cls(
            status="skip",
            return_value=None,
            stderr=reason_text,
            latency_ms=0.0,
            tool_name=tool_name,
            args_fingerprint="",
            return_value_sha1="",
            stderr_sha1=_sha1_16(reason_text),
            return_value_bytes=0,
            stderr_bytes=_utf8_bytes(reason_text),
        )

    def to_dict(self) -> dict:
        """JSON-serializable snapshot for delta merging / ChromaDB storage."""
        return asdict(self)

    def compact_metadata(self) -> dict:
        """Fingerprint-only view. Use this for metadata-only commits.

        Excludes the full return_value / stderr payloads; the full text is
        recoverable from ChromaDB's documents field if needed. Keeps
        procedural_wins rows cheap as the surface grows.
        """
        return {
            "status": self.status,
            "tool_name": self.tool_name,
            "latency_ms": self.latency_ms,
            "args_fingerprint": self.args_fingerprint,
            "return_value_sha1": self.return_value_sha1,
            "stderr_sha1": self.stderr_sha1,
            "return_value_bytes": self.return_value_bytes,
            "stderr_bytes": self.stderr_bytes,
        }
