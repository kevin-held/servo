"""
path_utils — Single-anchor path resolver for tool arguments.

Every tool that takes a path argument routes it through resolve(). Contract:

  * Input must be a project-root-relative string (forward or backward slashes
    accepted; normalised internally).
  * Absolute paths — POSIX-style (`/etc/...`) or Windows drive-letter
    (`C:/...`) — are REJECTED with a model-readable error.
  * Relative paths are joined to PROJECT_ROOT, resolved, and verified to lie
    within PROJECT_ROOT. `..` segments that escape the root are REJECTED.

Rationale (see decisions.md D-20260417-09):

  The model was producing hallucinated absolute paths with mangled user
  segments — `C:/Users/iam/OneDrive/...`, `C:/Users/ke/OneDrive/...`,
  `C:/Users/kevin/OneDrive/to/Desktop/...`. The root cause was the system
  prompt rendering workspace/codex folders as absolute paths (see core/loop.py
  substitutions for {workspace_folder}/{codex_folder}) and tool schemas whose
  descriptions literally contained absolute-path examples. The fix is a
  discipline layer: the prompt only ever shows relative forms, tools only
  ever accept relative forms, and the absolute anchor lives here in Python
  where the model cannot corrupt it.

  Rejection-over-salvage: attempting to recover from a mangled absolute path
  means fuzzy matching on the workspace folder name, which re-introduces the
  non-determinism the discipline is meant to eliminate. A clean rejection
  with a teaching error message gives the model the feedback it needs in
  its next cycle's context, without hiding the drift in the logs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

# Anchor discovered once at import time. `core/` is one directory deep from
# the project root, so parent.parent is the project root. This is the SAME
# derivation used by every existing tool (_ROOT = Path(__file__).parent.parent)
# and by log_summarizer; keeping it co-located here gives every caller a
# single source of truth.
PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()


class PathRejectedError(ValueError):
    """
    Raised when a path argument violates the project-relative rule.

    Tool execute() wrappers should catch this and return str(exc) as the
    tool output so the error text lands in the model's next-cycle context.
    """


def _looks_absolute(raw: str) -> bool:
    """
    Detect absolute paths in a cross-platform way.

    On Windows, Path('C:/x').is_absolute() is True but on Linux it is False.
    Because Servo development and verification can happen on either OS, we
    reject drive-letter strings explicitly rather than delegating to Path's
    host-dependent behavior.
    """
    if not raw:
        return False
    # POSIX-style absolute (e.g. "/etc/passwd")
    if raw.startswith(("/", "\\")):
        return True
    # Windows drive-letter (e.g. "C:/...", "C:\\...", "c:foo")
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        return True
    # Python's own check as a belt-and-suspenders fallback (catches UNC paths
    # like "\\server\share" that the above heuristics might miss in unusual
    # inputs).
    if Path(raw).is_absolute():
        return True
    return False


def resolve(path_arg: Union[str, Path]) -> Path:
    """
    Resolve a tool path argument against PROJECT_ROOT.

    Args:
        path_arg: Project-root-relative path, as a string or Path. Forward
                  or backward slashes are accepted.

    Returns:
        Absolute Path inside PROJECT_ROOT.

    Raises:
        PathRejectedError: If the input is empty, absolute, a drive-letter
                           string, or escapes the project root via '..'.
                           The error message is phrased for the model to
                           read and learn from in its next cycle.
    """
    if path_arg is None:
        raise PathRejectedError(
            "Path argument is required but was None. "
            "Use a project-root-relative path like 'codex/manifest.json'."
        )

    raw = str(path_arg).strip()
    if not raw:
        raise PathRejectedError(
            "Path argument is empty. "
            "Use a project-root-relative path like 'codex/manifest.json'."
        )

    if _looks_absolute(raw):
        raise PathRejectedError(
            f"Absolute paths are not allowed (got {path_arg!r}). "
            f"Use project-root-relative paths. "
            f"Example: 'core/tool_registry.py', not "
            f"'C:/Users/.../core/tool_registry.py'. "
            f"The project root is managed by the tool — never emit drive "
            f"letters or leading slashes."
        )

    # Normalize slashes, join to root, resolve '.' and '..' segments.
    candidate = (PROJECT_ROOT / raw.replace("\\", "/")).resolve()

    # Sandbox containment check. relative_to raises ValueError if candidate
    # isn't under PROJECT_ROOT (i.e. '..' climbed out).
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError:
        raise PathRejectedError(
            f"Path {path_arg!r} escapes the project root via '..' segments. "
            f"All paths must resolve within the project tree. "
            f"Remove '..' or use a valid subdirectory."
        )

    return candidate


def project_relative(p: Union[str, Path]) -> str:
    """
    Render a resolved path back as a project-root-relative string using
    forward slashes. Useful when tools format paths in their output so the
    model sees the relative form it should reuse in future calls.
    """
    try:
        rel = Path(p).resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        # Path is outside root — fall back to the absolute form; caller is
        # responsible for deciding whether that's acceptable.
        return str(Path(p).resolve()).replace("\\", "/")
    return str(rel).replace("\\", "/") or "."
