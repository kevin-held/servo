"""
analyst_runner — Analyst role auto-tool.

Replaces the old `filesystem:list workspace_folder` auto-tool with a purpose-
built briefing. Finds the newest change_proposal_<CP>.md in the Analyst's
workspace that lacks a matching critique_<CP>.md, reads the proposal, extracts
every file path it targets, and previews each target — flagging archived files
so the critique can reject proposals that touch superseded baselines.

The historical failure mode this addresses: gemma4:26b approved four out of
five CP-20260418-* proposals without ever reading the target files, and missed
that three of them targeted archived architecture reviews. See
codex/decisions.md D-20260418-07.

Payload shape:
{
    "workspace_folder":  "workspace/<model>",
    "target_proposal":   "workspace/<model>/change_proposal_CP-YYYYMMDD-NN.md",
    "proposal_text":     "<full text, truncated to _PROPOSAL_PREVIEW_MAX>",
    "proposal_mtime":    "ISO-8601",
    "target_files": [
        {
            "path":        "codex/role_manifests/sentinel.md",
            "exists":      true,
            "is_archived": false,
            "archived_reason": null,
            "preview":     "<first _TARGET_PREVIEW_CHARS chars>",
            "total_chars": 1527
        },
        ...
    ],
    "warnings":          ["TARGET ARCHIVED: ...", ...],
    "error":             null
}

Contract: standard agent tool — TOOL_NAME / TOOL_DESCRIPTION / TOOL_ENABLED /
TOOL_SCHEMA / execute().
"""

import json
import os
import re
import sys
import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import PROJECT_ROOT, project_relative

TOOL_NAME        = "analyst_runner"
TOOL_DESCRIPTION = (
    "Analyst role helper: locate the newest un-critiqued change_proposal_<CP>.md "
    "in workspace/<model>/, read it, and preview every file it targets — flagging "
    "archived/superseded targets so the critique can reject proposals that touch "
    "stale baselines. Returns a JSON payload with the proposal text, a target_files "
    "list (exists / is_archived / preview / total_chars for each), and any warnings. "
    "Designed to be invoked preemptively when the Analyst role is triggered so the "
    "model sees the target file contents in its nudge without having to issue a "
    "separate filesystem:read per target."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "workspace_folder": {
        "type": "string",
        "description": "(Optional) Project-relative path to the Analyst's "
                       "workspace folder, e.g. 'workspace/gemma4_26b'. If "
                       "omitted, the tool picks the workspace subdirectory "
                       "with the newest change_proposal_*.md file.",
    },
}

# Budgets. The whole payload ends up inside a role nudge so it competes with
# the rest of the system prompt for context; keep it tight.
_PROPOSAL_PREVIEW_MAX = 8000    # full proposal text, truncated with sentinel
_TARGET_PREVIEW_CHARS = 1500    # per-target file preview
_MAX_TARGETS          = 8       # dedupe and cap — more than this and the
                                # proposal is probably over-scoped anyway

# File-path extraction. We look for tokens with a known file extension and
# allow them to appear raw, in backticks, or inside markdown bold — the
# character class below matches path bodies without whitespace.
_PATH_EXTENSIONS = ("py", "md", "json", "jsonl", "txt", "yaml", "yml", "sh", "cfg", "ini")
_PATH_EXT_RE = re.compile(
    r"[A-Za-z0-9_\-./]+\.(?:" + "|".join(_PATH_EXTENSIONS) + r")",
)

# Pruned substrings in candidate paths. If a match contains any of these, it
# is almost certainly not a real target (e.g. someone wrote a URL or a code
# fragment inside prose).
_PATH_REJECT_SUBSTRINGS = ("http://", "https://", "://", "\\", " ")

# Archival signal patterns.
_OLD_STUFF_RE          = re.compile(r"(^|/)old_stuff(/|$)")
_ARCH_REVIEW_VERSION_RE = re.compile(r"architecture_review_v(\d+)\.md$")


def _pick_workspace() -> Path | None:
    """Return the workspace/<model>/ subdirectory with the newest
    change_proposal_*.md (not in old_stuff/), or None if no proposals exist.
    """
    ws_root = PROJECT_ROOT / "workspace"
    if not ws_root.exists():
        return None
    best_mtime = -1.0
    best_dir: Path | None = None
    for proposal in ws_root.glob("*/change_proposal_*.md"):
        try:
            mt = proposal.stat().st_mtime
        except OSError:
            continue
        if mt > best_mtime:
            best_mtime = mt
            best_dir = proposal.parent
    return best_dir


def _find_target_proposal(ws: Path) -> Path | None:
    """Return the newest change_proposal_*.md in ws/ that has no matching
    critique_*.md sibling. None if all are critiqued or there are no proposals.

    Matching rule: the proposal ID is the first CP-* token in the filename
    (everything between 'change_proposal_' and '.md'). A critique matches when
    it carries the same token.
    """
    proposals = [p for p in ws.glob("change_proposal_*.md") if p.is_file()]
    if not proposals:
        return None

    def _id_of(stem: str, prefix: str) -> str:
        return stem[len(prefix):] if stem.startswith(prefix) else stem

    critiqued_ids: set[str] = set()
    for c in ws.glob("critique_*.md"):
        critiqued_ids.add(_id_of(c.stem, "critique_"))

    uncritiqued = [
        p for p in proposals
        if _id_of(p.stem, "change_proposal_") not in critiqued_ids
    ]
    if not uncritiqued:
        return None
    return max(uncritiqued, key=lambda p: p.stat().st_mtime)


def _extract_paths(proposal_text: str) -> list[str]:
    """Pull likely project-relative file paths out of the proposal body.
    Dedupes while preserving first-appearance order; caps at _MAX_TARGETS.

    The regex's char class does not include ':' so URLs get broken at the
    scheme — the substring reject list can't see the '://' that survives only
    in the original text. We defend by checking the two characters immediately
    preceding each match: if the match is prefixed by '/' or ':', it's part of
    a URL (`https://example.com/foo.py` matches as `example.com/foo.py`
    preceded by `//`), and we drop it.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _PATH_EXT_RE.finditer(proposal_text):
        raw = match.group(0)
        start = match.start()
        # Pre-context guard: URLs and shell paths show up as match-prefix chars
        # '/' or ':'. A legitimate markdown target path is preceded by
        # whitespace, a backtick, a bullet char, '(', or start-of-string.
        prev_chars = proposal_text[max(0, start - 2):start]
        if prev_chars.endswith("/") or prev_chars.endswith(":"):
            continue
        # Strip leading './' or '/' noise.
        candidate = raw.lstrip("./").lstrip("/")
        if any(s in candidate for s in _PATH_REJECT_SUBSTRINGS):
            continue
        # Skip the archive markers the proposal author may mention in prose
        # (e.g. `old_stuff/architecture_review_v5.md`) — we still report them
        # as targets because the analyst needs to flag them; no filter here.
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
        if len(ordered) >= _MAX_TARGETS:
            break
    return ordered


def _current_baseline_version() -> int:
    """Return the highest architecture_review_v<N>.md integer in any live
    workspace folder (active only, not old_stuff/). 0 if none.
    """
    ws_root = PROJECT_ROOT / "workspace"
    if not ws_root.exists():
        return 0
    best = 0
    for p in ws_root.glob("*/architecture_review_v*.md"):
        m = _ARCH_REVIEW_VERSION_RE.search(p.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > best:
            best = n
    return best


def _classify_path(rel: str, baseline: int) -> tuple[bool, str | None]:
    """Return (is_archived, reason) for a candidate target path.

    A path is archived if:
      * it contains an 'old_stuff/' segment, OR
      * it matches architecture_review_v<N>.md where N < baseline.
    """
    if _OLD_STUFF_RE.search(rel):
        return True, f"path contains old_stuff/ segment — archived"
    m = _ARCH_REVIEW_VERSION_RE.search(rel)
    if m:
        n = int(m.group(1))
        if baseline and n < baseline:
            return True, (
                f"architecture_review_v{n}.md is superseded by current baseline "
                f"v{baseline} — archived (critique should REJECT if this is "
                f"the target of a modification)"
            )
    return False, None


def _preview_file(rel: str) -> dict:
    """Return an entry for target_files: exists, is_archived, preview, total_chars."""
    abs_path = (PROJECT_ROOT / rel).resolve()
    # Guard against path escape — if resolving escapes PROJECT_ROOT, treat as
    # nonexistent rather than reading.
    try:
        abs_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return {"path": rel, "exists": False, "is_archived": False,
                "archived_reason": None, "preview": None, "total_chars": 0}
    if not abs_path.exists() or not abs_path.is_file():
        return {"path": rel, "exists": False, "is_archived": False,
                "archived_reason": None, "preview": None, "total_chars": 0}
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"path": rel, "exists": True, "is_archived": False,
                "archived_reason": None,
                "preview": f"[ERROR reading: {e}]", "total_chars": 0}
    preview = text[:_TARGET_PREVIEW_CHARS]
    if len(text) > _TARGET_PREVIEW_CHARS:
        preview += f"\n\n[...TRUNCATED — {len(text) - _TARGET_PREVIEW_CHARS} more chars]"
    return {"path": rel, "exists": True, "is_archived": False,
            "archived_reason": None, "preview": preview,
            "total_chars": len(text)}


def _run(workspace_folder: str = "") -> dict:
    results: dict = {
        "workspace_folder": None,
        "target_proposal":  None,
        "proposal_text":    None,
        "proposal_mtime":   None,
        "target_files":     [],
        "warnings":         [],
        "error":            None,
    }

    # Resolve the workspace folder — either the caller-provided one or the
    # auto-picked one.
    if workspace_folder:
        ws = (PROJECT_ROOT / workspace_folder).resolve()
        try:
            ws.relative_to(PROJECT_ROOT)
        except ValueError:
            results["error"] = (
                f"workspace_folder '{workspace_folder}' escapes project root"
            )
            return results
        if not ws.exists() or not ws.is_dir():
            results["error"] = (
                f"workspace_folder '{workspace_folder}' does not exist or is "
                f"not a directory"
            )
            return results
    else:
        ws = _pick_workspace()
        if ws is None:
            results["error"] = (
                "No workspace subdirectory has any change_proposal_*.md. "
                "Either the Architect has not emitted a proposal yet or the "
                "workspace/ tree is empty."
            )
            return results

    results["workspace_folder"] = project_relative(ws)

    proposal = _find_target_proposal(ws)
    if proposal is None:
        results["error"] = (
            f"No un-critiqued change_proposal_*.md found in "
            f"{results['workspace_folder']}. Either all proposals have "
            f"matching critiques or the folder is empty."
        )
        return results

    results["target_proposal"] = project_relative(proposal)
    results["proposal_mtime"]  = datetime.datetime.fromtimestamp(
        proposal.stat().st_mtime).isoformat()

    try:
        text = proposal.read_text(encoding="utf-8")
    except OSError as e:
        results["error"] = f"Cannot read {results['target_proposal']}: {e}"
        return results

    if len(text) > _PROPOSAL_PREVIEW_MAX:
        cut = _PROPOSAL_PREVIEW_MAX
        results["proposal_text"] = (
            text[:cut]
            + f"\n\n[...TRUNCATED — {len(text) - cut} more chars; "
              f"issue filesystem:read on {results['target_proposal']} "
              f"block=2 for the tail]"
        )
    else:
        results["proposal_text"] = text

    # Extract and classify every candidate target.
    baseline = _current_baseline_version()
    candidates = _extract_paths(text)
    for rel in candidates:
        entry = _preview_file(rel)
        archived, reason = _classify_path(rel, baseline)
        entry["is_archived"]     = archived
        entry["archived_reason"] = reason
        results["target_files"].append(entry)
        if archived:
            results["warnings"].append(
                f"TARGET ARCHIVED: {rel} — {reason}. Reject proposals that "
                f"modify archived artifacts; they are not live system state."
            )

    if not candidates:
        results["warnings"].append(
            "No file paths matching a known extension were extracted from the "
            "proposal body. The Analyst should read the proposal text and "
            "verify targets manually before critiquing."
        )

    return results


def execute(workspace_folder: str = "") -> str:
    """Tool entry point — returns the briefing as a JSON string."""
    return json.dumps(_run(workspace_folder=workspace_folder), indent=2)


if __name__ == "__main__":
    # Manual smoke-test: `python tools/analyst_runner.py [workspace/<model>]`
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    print(execute(workspace_folder=arg))
