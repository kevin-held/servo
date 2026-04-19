import os
import re
import sys
import json
import time
import datetime
from pathlib import Path

# Use the single-anchor resolver so the scan is deterministic no matter where
# the process CWD happens to be. Previous version used os.walk('.'), which made
# it work only when run from the project root — brittle and easy to misread
# when invoked via the tool registry from somewhere else.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import PROJECT_ROOT, project_relative

TOOL_NAME        = "scholar_runner"
TOOL_DESCRIPTION = (
    "Scholar role helper: find the newest architecture_review_v<N>.md under "
    "workspace/<model>/ and scan the project for files modified since that "
    "review was last updated, plus the mandatory ledgers "
    "(codex/decisions.md, codex/history.md, codex/rejected_proposals.md) that "
    "the Scholar always re-reads for the closed-proposal sweep. Returns a JSON "
    "payload with the review's path + timestamp, the list of deltas "
    "(small files as plain path strings, oversized files as "
    "{path, summary, raw_line_count, raw_bytes} blocks from default-on "
    "pre-summarization), scan_stats + summarization_stats for diagnostics, "
    "and an authoritative next_version counter derived from the highest "
    "architecture_review_v<N>.md seen across BOTH the active workspace AND "
    "old_stuff/. The Scholar should always emit "
    "architecture_review_v<next_version>.md — never parse review_path and "
    "increment it — so the counter self-heals if a prior cycle archived the "
    "baseline without emitting the next review. Pre-summarization can be "
    "disabled per-call with summarize_deltas=false for workflows that need "
    "exact-string matching against ledger entries. Designed to be invoked "
    "preemptively when the Scholar role is triggered so the model sees the "
    "deltas without having to compute them."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "include_review_head": {
        "type": "boolean",
        "description": "(Optional) If true, include the current architecture "
                       "review's text (capped at ~8000 chars) as a review_head "
                       "field in the payload. The Architect role sets this so "
                       "the review lands in its nudge without a second "
                       "filesystem:read. Default false — the Scholar doesn't "
                       "need the payload to carry the review it's about to "
                       "rewrite.",
    },
    "summarize_deltas": {
        "type": "boolean",
        "description": "(Optional) If true (default), delta files exceeding "
                       f"{500} lines are pre-summarized through the shared "
                       "summarizer kernel before the payload lands. Oversized "
                       "deltas are emitted as {path, summary, raw_line_count, "
                       "raw_bytes} blocks alongside plain path strings for "
                       "small files. Set false to get the legacy plain-path "
                       "list for every delta (use when the Scholar needs to "
                       "do exact-string matching against ledger entries — "
                       "e.g. the closed-proposal sweep).",
    },
}

# Line-count threshold for default-on delta pre-summarization. Files with more
# than this many lines get run through the summarizer kernel before the payload
# is assembled; smaller files stay as plain path strings. 500 is large enough
# that small source files and short docs pass through verbatim, but small
# enough that the canonical growing ledgers (history.md, decisions.md) land as
# summaries once they exceed a release or two of accumulated entries.
_DELTA_SUMMARIZE_LINE_THRESHOLD = 500
# Cap on bytes of review text we inline into the payload. Sized to leave
# headroom under the registry's MAX_TOOL_OUTPUT=16000 cap after the rest of the
# JSON (deltas list, scan_stats, etc.) lands. If the current review is larger
# than this, we truncate and mark the cut with a [...TRUNCATED] sentinel so the
# model knows to issue a follow-up filesystem:read for the tail.
_REVIEW_HEAD_MAX_CHARS = 8000

# Directories that should never contribute to a delta scan: version-control
# metadata, bytecode caches, runtime state, logs, the local virtualenv, and
# anything under workspace/<model>/old_stuff/ (archived review history should
# not force new delta cycles). Kept in sync with tools/analyze_directory.py —
# both tools walk PROJECT_ROOT and should agree on what counts as noise.
_PRUNED_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__",
    "state", "logs",
    ".venv", "venv", "env", ".env",
    "node_modules", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "old_stuff",
}

# The only path the scan refuses to flag is the current architecture review
# itself — that's the baseline being compared against, not a delta.
#
# Previously this tool also self-skipped `tools/scholar_runner.py` on the
# theory that "every scholar cycle would include itself and the loop would
# never settle." That reasoning was wrong: nothing in a normal cycle writes
# to scholar_runner.py, so its mtime only advances when a human edits it —
# which is exactly when the Scholar should see it as a delta. The self-skip
# was silently hiding real edits to the scanning tool, which defeats the
# point of the scan. Removed 2026-04-18.
_WORKSPACE_REL    = "workspace"
# Matches only the canonical architecture_review_v<N>.md pattern. We used to
# accept architecture_review_*.md, but that also matched legacy
# architecture_review_part1.md / _part2.md files from bootstrap-era qwen runs,
# which could shadow a real v<N>.md baseline if their mtime was newer. The
# Scholar's versioning logic ("<v+1> is the next integer after <v>") is
# undefined for non-integer suffixes, so those files must not be treated as
# baselines.
_REVIEW_GLOB      = "architecture_review_v*.md"
# Ledgers that the Scholar's closed-proposal sweep (scholar.md step 4) must
# reconcile against every cycle, even if their mtime predates the current
# baseline. Without rejected_proposals.md here, the Scholar couldn't detect
# proposals that were closed via rejection.
_MANDATORY_FILES  = [
    "codex/decisions.md",
    "codex/history.md",
    "codex/rejected_proposals.md",
]

# Parses architecture_review_v<N>.md and extracts N. Anchored to the filename
# only (not the path) so it works for both active and archived reviews.
_VERSION_RE = re.compile(r"architecture_review_v(\d+)\.md$")


def _find_latest_review() -> Path | None:
    """Return the newest architecture_review_<v>.md across all workspace/<model>/
    folders, or None if no versioned review exists yet.

    Tie-breaks on mtime (newest wins). We look across all model folders because
    scholar_runner has no schema inputs — template substitution for a specific
    {workspace_folder} would bind the tool to one model, but this tool is
    invoked from auto_tool with empty args and needs to find whichever active
    workspace produced the most recent review.
    """
    ws_root = PROJECT_ROOT / _WORKSPACE_REL
    if not ws_root.exists():
        return None

    candidates = list(ws_root.glob(f"*/{_REVIEW_GLOB}"))
    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def _find_highest_version() -> tuple[int, Path | None]:
    """Return (N, path) for the highest architecture_review_v<N>.md seen
    anywhere under workspace/ — active folders AND old_stuff/ subfolders — or
    (0, None) if no versioned review exists.

    This is the authoritative counter for next_version. It exists so the
    Scholar can recover cleanly from a prior cycle that archived the baseline
    before emitting the next review: without this sweep of old_stuff/, the
    version scan would see an empty active folder and regress to v1.
    """
    ws_root = PROJECT_ROOT / _WORKSPACE_REL
    if not ws_root.exists():
        return 0, None

    # Active reviews AND archived ones both count toward the version counter.
    candidates = (
        list(ws_root.glob(f"*/{_REVIEW_GLOB}"))
        + list(ws_root.glob(f"*/old_stuff/{_REVIEW_GLOB}"))
    )

    best_n = 0
    best_path: Path | None = None
    for p in candidates:
        m = _VERSION_RE.search(p.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > best_n:
            best_n = n
            best_path = p
    return best_n, best_path


# system_rules for pre-summarized deltas. Deliberately different from the
# generic filesystem:read summarize prompt: the Scholar needs a delta-centric
# view ("what changed, what does this file do now, what does a reviewer need
# to know") rather than a file-as-standalone-artifact summary. Preserving
# explicit markers (TODO / FIXME / decision IDs / version bumps) is critical
# because the Scholar's closed-proposal sweep matches against those strings.
_DELTA_SUMMARY_SYSTEM_RULES = (
    "You are condensing a project file so the Scholar role can reason about "
    "architectural drift without rereading every line. Produce a dense "
    "narrative that covers: the file's current purpose, its top-level "
    "structure (modules / classes / functions / headings / config keys — "
    "whichever apply), any cross-references to other project files it "
    "depends on or is depended on by, and anything a code reviewer would "
    "flag. Preserve verbatim: decision IDs (D-YYYYMMDD-NN), change-proposal "
    "IDs (CP-YYYYMMDD-NN), version strings (v0.X.Y), TODO / FIXME / WARN "
    "markers, and any section headings that appear to name a release or "
    "architectural phase. Skip implementation detail, imports, boilerplate, "
    "and license headers. Two to four paragraphs. Return only the summary "
    "text — no preamble, no sign-off."
)


def _summarize_delta(rel_path: str, abs_path: Path) -> dict | None:
    """Attempt to pre-summarize a single delta file. Returns a payload dict
    on success, or None on any error (caller should fall back to plain
    string).

    The returned dict shape is:
        {"path": rel_path, "summary": <wrapped summary>,
         "raw_line_count": int, "raw_bytes": int}

    The summary is pre-wrapped in [SUMMARY of <rel> — <N> lines] ... [END
    SUMMARY] markers so the Scholar sees the same envelope whether the
    summary came from pre-summarization here or from a manual
    filesystem:read with summarize=true.
    """
    try:
        text = abs_path.read_text(encoding="utf-8")
    except OSError:
        return None
    raw_bytes = len(text.encode("utf-8"))
    line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    if line_count <= _DELTA_SUMMARIZE_LINE_THRESHOLD:
        return None

    # Lazy import — avoid dragging the Ollama client into module scope for
    # callers that pass summarize_deltas=False.
    try:
        from tools.summarizer import summarize as _kernel_summarize
        summary, _model = _kernel_summarize(text, _DELTA_SUMMARY_SYSTEM_RULES)
    except Exception:
        return None

    if not summary:
        # Empty kernel response — fall back to plain string so the Scholar
        # knows to read the raw file itself. Signaled by returning None.
        return None

    wrapped = (f"[SUMMARY of {rel_path} — {line_count} lines]\n"
               f"{summary}\n"
               f"[END SUMMARY]")
    return {
        "path": rel_path,
        "summary": wrapped,
        "raw_line_count": line_count,
        "raw_bytes": raw_bytes,
    }


def _run_scan(include_review_head: bool = False,
              summarize_deltas: bool = True) -> dict:
    results: dict = {
        "review_path": None,
        "last_review_update": None,
        "next_version": 1,
        "highest_version_seen": None,
        "highest_version_path": None,
        "deltas": [],
        "scan_stats": {},
        "summarization_stats": {
            "files_summarized": 0,
            "files_skipped_small": 0,
            "files_summarize_failed": 0,
            "time_seconds": 0.0,
            "enabled": bool(summarize_deltas),
        },
        "warning": None,
        "error": None,
        "review_head": None,
    }

    # Version counter scan is always populated — it draws from both active and
    # archived reviews, so it's meaningful even when the active baseline is
    # missing.
    highest_n, highest_path = _find_highest_version()
    if highest_n:
        results["next_version"]         = highest_n + 1
        results["highest_version_seen"] = highest_n
        results["highest_version_path"] = project_relative(highest_path) if highest_path else None

    arch_review_path = _find_latest_review()
    if arch_review_path is None:
        # Split the empty-active-folder case: if old_stuff already has a
        # versioned review, this is a prior-cycle archive-without-emit — the
        # Scholar should resume at highest_n+1, NOT bootstrap at v1.
        if highest_n:
            results["warning"] = (
                f"Active workspace has no architecture_review_v*.md, but "
                f"old_stuff/ contains v{highest_n} "
                f"({results['highest_version_path']}). A prior cycle archived "
                f"the baseline without emitting the next review. Resume at "
                f"v{highest_n + 1} — do not bootstrap at v1."
            )
        else:
            results["error"] = (
                "CRITICAL: no architecture_review_v*.md found under "
                f"{_WORKSPACE_REL}/<model>/ (active or old_stuff). The "
                "Scholar must emit an initial review before deltas can be "
                "computed."
            )
        # Even without a baseline we still run the delta scan below so the
        # caller sees what's in the tree; everything counts as "newer than
        # last_review_update=None", so we use mtime 0 as the threshold.
        last_mod_time = 0.0
        review_rel = None
    else:
        review_rel = project_relative(arch_review_path)
        last_mod_time = arch_review_path.stat().st_mtime
        results["review_path"] = review_rel
        results["last_review_update"] = datetime.datetime.fromtimestamp(last_mod_time).isoformat()
        # Opt-in inline of the review text so the Architect (or any caller that
        # opts in) sees the full baseline in its nudge without issuing a second
        # filesystem:read. Truncate with an explicit sentinel so the model
        # knows to fetch the tail if it needs it.
        if include_review_head:
            try:
                text = arch_review_path.read_text(encoding="utf-8")
                if len(text) > _REVIEW_HEAD_MAX_CHARS:
                    cut = _REVIEW_HEAD_MAX_CHARS
                    results["review_head"] = (
                        text[:cut]
                        + f"\n\n[...TRUNCATED — {len(text) - cut} more chars; "
                          f"issue filesystem:read on {review_rel} block=2 for the tail]"
                    )
                else:
                    results["review_head"] = text
            except OSError as e:
                results["review_head"] = f"[ERROR reading {review_rel}: {e}]"

    delta_set: set[str] = set()
    files_scanned = 0
    newest_mtime = 0.0
    newest_path: str | None = None

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Prune internal directories in-place so os.walk doesn't descend into them.
        dirs[:] = [d for d in dirs if d not in _PRUNED_DIRS]

        for file in files:
            abs_path = Path(root) / file
            rel_path = project_relative(abs_path)

            # Skip the current review file — that's the baseline being compared
            # against, not a delta. Everything else (including this tool itself)
            # is fair game.
            if rel_path == review_rel:
                continue

            try:
                mtime = abs_path.stat().st_mtime
            except OSError:
                continue

            files_scanned += 1
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_path = rel_path

            if mtime > last_mod_time:
                delta_set.add(rel_path)

    mtime_delta_count = len(delta_set)

    # Mandatory files get re-read every cycle regardless of mtime — they're the
    # Scholar's running ledger and should always be reconciled against the
    # architecture review.
    for m_file in _MANDATORY_FILES:
        delta_set.add(m_file)

    sorted_deltas = sorted(delta_set)

    # Default-on pre-summarization pass. For each delta path:
    #   - if summarize_deltas=False: keep the plain path string (legacy shape)
    #   - else if file is small (<= threshold) or missing: keep the plain path
    #   - else: run the kernel and replace with a {path, summary, raw_line_count,
    #           raw_bytes} block. Kernel failures or empty responses fall back
    #           to the plain path so the Scholar always has SOMETHING it can
    #           act on.
    deltas_out: list = []
    if summarize_deltas:
        t0 = time.monotonic()
        for rel_path in sorted_deltas:
            abs_path = PROJECT_ROOT / rel_path
            if not abs_path.exists() or not abs_path.is_file():
                deltas_out.append(rel_path)
                continue
            # Cheap pre-check: peek at line count before paying for the
            # kernel call. We read the file twice on the summarize path
            # (once here, once inside _summarize_delta), but the files we
            # hit this path for are already > 500 lines and the re-read is
            # negligible next to the 60-120s summarizer chat.
            try:
                with open(abs_path, "r", encoding="utf-8") as fh:
                    # Count lines cheaply without loading the whole file twice
                    # into memory — we do still read the whole file, but the
                    # line_count path is O(bytes) and the summarizer call is
                    # O(minutes), so the duplicate read is in the noise.
                    text = fh.read()
            except OSError:
                deltas_out.append(rel_path)
                continue
            line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            if line_count <= _DELTA_SUMMARIZE_LINE_THRESHOLD:
                deltas_out.append(rel_path)
                results["summarization_stats"]["files_skipped_small"] += 1
                continue

            summarized = _summarize_delta(rel_path, abs_path)
            if summarized is None:
                # Either an I/O error, a kernel exception, or an empty kernel
                # response. Fall back to plain path so the Scholar can still
                # read it manually if it chooses to.
                deltas_out.append(rel_path)
                results["summarization_stats"]["files_summarize_failed"] += 1
            else:
                deltas_out.append(summarized)
                results["summarization_stats"]["files_summarized"] += 1
        results["summarization_stats"]["time_seconds"] = round(time.monotonic() - t0, 2)
    else:
        deltas_out = list(sorted_deltas)

    results["deltas"] = deltas_out
    # Diagnostic block — gives the caller (human or model) a quick read on
    # whether the scan actually saw anything recent. If mtime_delta_count is 0
    # and newest_file_mtime is older than last_review_update, no tool/codex
    # edits have landed since the baseline — either the baseline really is
    # current, or file mtimes on the filesystem aren't tracking edits (OneDrive
    # sync can stamp files with cloud mtimes rather than local edit times).
    results["scan_stats"] = {
        "files_scanned": files_scanned,
        "mtime_delta_count": mtime_delta_count,
        "mandatory_count": len(_MANDATORY_FILES),
        "newest_file": newest_path,
        "newest_file_mtime": (
            datetime.datetime.fromtimestamp(newest_mtime).isoformat()
            if newest_mtime else None
        ),
    }
    return results


def execute(include_review_head: bool = False,
            summarize_deltas: bool = True) -> str:
    """Tool entry point — returns the scan result as a JSON string.

    include_review_head: if true, inline the current review's text (capped at
    _REVIEW_HEAD_MAX_CHARS) as a review_head field. Used by the Architect role
    so the baseline review lands in its nudge without a follow-up read.

    summarize_deltas: if true (default), delta files exceeding
    _DELTA_SUMMARIZE_LINE_THRESHOLD lines are pre-summarized through the
    shared summarizer kernel and emitted as {path, summary, raw_line_count,
    raw_bytes} blocks instead of plain path strings. Pass false to get the
    legacy plain-path shape for every delta.
    """
    return json.dumps(
        _run_scan(
            include_review_head=bool(include_review_head),
            summarize_deltas=bool(summarize_deltas),
        ),
        indent=2,
    )


if __name__ == "__main__":
    # Manual smoke-test entry: `python tools/scholar_runner.py`
    print(execute())
