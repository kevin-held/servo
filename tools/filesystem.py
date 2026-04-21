import sys
import shutil
from pathlib import Path

# Use the single-anchor resolver for all model-provided paths.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "filesystem"
TOOL_DESCRIPTION = "Read, write, append, list, move, or delete files and directories on disk"
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "operation": {"type": "string",
                  "enum": ["read", "write", "append", "list", "move", "delete"],
                  "description": "Operation to perform. 'append' adds content to end of file without overwriting. "
                                 "'move' renames/moves `path` to `dest` (intermediate folders auto-created). "
                                 "'delete' removes a file (directories are rejected to prevent accidental tree wipes)."},
    "path":      {"type": "string",
                  "description": "Project-root-relative file or directory path. "
                                 "Examples: 'codex/manifest.json', 'workspace/gemma4_26b/notes.md', "
                                 "'tools/log_query.py'. Absolute paths and drive letters are rejected - "
                                 "the project root is managed by the tool."},
    "dest":      {"type": "string",
                  "description": "(move only) Project-root-relative destination path. "
                                 "Example: 'workspace/gemma4_26b/old_stuff/change_proposal_001.md'. "
                                 "Must not already exist - overwrites are refused so archival never loses data."},
    "content":   {"type": "string", "description": "Content to write or append (write/append only)"},
    "max_lines": {"type": "integer", "description": "(Optional, read only) Cap lines returned from the top of the file. Ignored when `block` is specified."},
    "block":     {"type": "integer",
                  "description": "(Optional, read only) Zero-indexed 15000-char block to return when a file exceeds one read. "
                                 "block=0 returns chars 0..14999, block=1 returns 15000..29999, and so on. "
                                 "Omit (default 0) for the first chunk. The footer of each block names the exact "
                                 "`block` value to pass on the next call to continue reading."},
    "summarize": {"type": "boolean",
                  "description": "(Optional, read only) When true, the file's contents are run through the "
                                 "shared summarizer kernel (tools/summarizer.py) before being returned. "
                                 "The result is wrapped in [SUMMARY of <path> - <N> lines] ... [END SUMMARY] "
                                 "markers so the model knows it is looking at a condensed view rather than "
                                 "the verbatim file. Pagination (`block`) and `max_lines` are applied BEFORE "
                                 "summarization, so passing both gives a summary of the selected slice only. "
                                 "If the summarizer returns an empty response the raw content is returned "
                                 "instead, prefixed with [SUMMARIZER RETURNED EMPTY - returning raw content]. "
                                 "Default false."},
}
from core.identity import get_system_defaults

# Block size for paginated reads. Kept below the tool_registry MAX_TOOL_OUTPUT
# (16000) so the "[BLOCK N OF M]" footer never pushes the tool result past the
# registry cap - otherwise the model would see the block content twice
# truncated (once by us, again by the registry) and lose the navigation hint.
_BLOCK_SIZE = get_system_defaults().get("registry", {}).get("BLOCK_SIZE", 15000)


def execute(operation: str, path: str, content: str = "", max_lines: int = 0,
            dest: str = "", block: int = 0, summarize: bool = False) -> str:
    # Route every path through the single-anchor resolver. Rejection text is
    # surfaced to the model as the tool output so it can correct itself next
    # cycle - see decisions.md D-20260417-09.
    try:
        p = resolve(path)
    except PathRejectedError as e:
        return f"Error: {e}"

    # For user-facing messages, render the relative form so the model learns
    # the shape it should be emitting.
    rel = project_relative(p)

    if operation == "read":
        if not p.exists():
            return f"Error: '{rel}' does not exist"
        if p.is_dir():
            return f"Error: '{rel}' is a directory - use list"

        text = p.read_text(encoding="utf-8")
        total_len = len(text)

        # Block pagination. Two entry points:
        #   (a) caller passed block > 0 - they are explicitly asking for a
        #       later slice of a large file; honor it regardless of size.
        #   (b) caller passed block = 0 on a file larger than one block -
        #       auto-paginate the first chunk and tell the model how to
        #       fetch the next one. This way even a model that doesn't know
        #       about `block` gets an actionable hint instead of a silent
        #       truncation from the tool_registry cap.
        #
        # Semantics with `summarize=True`: pagination/max_lines run FIRST,
        # and the summarizer sees the slice that would otherwise be
        # returned. We summarize the body only - the `[BLOCK N OF M ...]`
        # footer is appended AFTER the summary so the model still gets the
        # navigation hint even when the body has been condensed.
        body = text
        footer = ""
        total_blocks = max(1, (total_len + _BLOCK_SIZE - 1) // _BLOCK_SIZE)
        if block > 0 or total_len > _BLOCK_SIZE:
            if block < 0 or block >= total_blocks:
                return (f"Error: block {block} out of range - '{rel}' has "
                        f"{total_blocks} block(s), valid indexes 0..{total_blocks - 1}")
            start = block * _BLOCK_SIZE
            end   = min(start + _BLOCK_SIZE, total_len)
            footer = (f"\n\n[BLOCK {block} OF {total_blocks - 1} - "
                      f"chars {start}..{end - 1} of {total_len}. ")
            if block + 1 < total_blocks:
                footer += (f"Call filesystem again with the same path and "
                           f"block={block + 1} to continue reading.]")
            else:
                footer += "This is the last block - read complete.]"
            body = text[start:end]
        elif max_lines and max_lines > 0:
            lines = text.splitlines()
            if len(lines) > max_lines:
                body = "\n".join(lines[:max_lines])
                footer = f"\n\n[Showing first {max_lines} of {len(lines)} total lines]"

        if summarize:
            body = _summarize_read_body(body, rel)

        return body + footer

    elif operation == "write":
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to '{rel}'"

    elif operation == "list":
        if not p.exists():
            return f"Error: '{rel}' does not exist"
        if p.is_file():
            return rel
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for entry in entries:
            prefix = "  " if entry.is_file() else "FOLDER "
            lines.append(f"{prefix}{entry.name}")
        return "\n".join(lines) or "(empty)"

    elif operation == "append":
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} chars to '{rel}'"

    elif operation == "move":
        # move = rename within the project root. Both endpoints go through the
        # resolver so a role can't smuggle an absolute path via `dest`.
        if not dest:
            return "Error: move requires a `dest` argument (project-relative target path)"
        try:
            q = resolve(dest)
        except PathRejectedError as e:
            return f"Error: {e}"
        dest_rel = project_relative(q)
        if not p.exists():
            return f"Error: source '{rel}' does not exist"
        if q.exists():
            # Refuse overwrite - archival should never silently destroy an
            # existing file. If the role really wants to replace, it must
            # delete the destination first as a separate, explicit step.
            return f"Error: destination '{dest_rel}' already exists - refuse to overwrite"
        q.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(p), str(q))
        except OSError as e:
            return f"Error: move failed - {e}"
        return f"Moved '{rel}' -> '{dest_rel}'"

    elif operation == "delete":
        if not p.exists():
            return f"Error: '{rel}' does not exist"
        if p.is_dir():
            # Directory deletion is deliberately not supported here. If a role
            # needs to remove a directory, it should empty it file-by-file
            # first - that makes the log a reviewable audit trail instead of
            # a single rm -rf that destroys state in one call.
            return f"Error: '{rel}' is a directory - filesystem:delete only removes files"
        try:
            p.unlink()
        except OSError as e:
            return f"Error: delete failed - {e}"
        return f"Deleted '{rel}'"

    else:
        return f"Unknown operation: '{operation}'. Use read, write, append, list, move, or delete."


# --------------------------------------------------------------------------
# Read-time summarization helper (Phase 3, D-20260419-04)
# --------------------------------------------------------------------------
#
# When a caller passes `summarize=True` to a read, the verbatim body is fed
# through the shared summarizer kernel (tools/summarizer.py) and replaced
# with a wrapped condensed view. Empty-kernel responses fall through to the
# raw body with an inline marker so the caller never gets silently empty
# output - that was the failure mode that burned the log_summarizer pilot
# (see decisions.md D-20260418-10).
#
# The system_rules block below is intentionally file-type-agnostic: a
# filesystem:read summarize call might target source code, a markdown doc,
# a JSON config, or a log excerpt. Callers that want a code-structure view
# versus a prose-outline view should pre-trim the body themselves or
# invoke the kernel directly with custom rules; this helper's job is to
# give a reasonable default for ad-hoc model-issued summarize reads.
_READ_SUMMARY_SYSTEM_RULES = (
    "You are condensing the contents of a file so a reader can understand "
    "its purpose and structure without needing the verbatim bytes. Produce "
    "a compact narrative description: what the file is for, the major "
    "sections or components it contains, the key identifiers (functions, "
    "classes, headings, config keys, top-level JSON keys - whichever apply), "
    "and any cross-references to other parts of the system that a reader "
    "would need to know about. Skip implementation detail, boilerplate, "
    "imports, license headers, and decorative formatting. Preserve any "
    "explicit TODO / FIXME / WARN markers verbatim. One to three paragraphs; "
    "no bullet lists unless the file itself is a list. Return only the "
    "summary text - no preamble, no sign-off."
)


def _summarize_read_body(body: str, rel: str) -> str:
    """Run `body` through the summarizer kernel and wrap the result.

    On non-empty kernel response, returns:
        [SUMMARY of <rel> - <N> lines]
        <summary>
        [END SUMMARY]

    On empty kernel response, falls back to the raw body prefixed with:
        [SUMMARIZER RETURNED EMPTY - returning raw content]

    Any exception raised by the kernel (network error, missing Ollama,
    etc.) is caught and rendered as a fallback header so the read never
    crashes the tool-call path.
    """
    line_count = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
    try:
        # Lazy import so the filesystem tool doesn't drag the Ollama client
        # into module-load scope for every non-summarize read.
        from tools.summarizer import summarize as _kernel_summarize
        summary, _model = _kernel_summarize(body, _READ_SUMMARY_SYSTEM_RULES)
    except Exception as e:                    # pragma: no cover - defensive
        return (f"[SUMMARIZER FAILED - {e} - returning raw content]\n{body}")

    if not summary:
        return (f"[SUMMARIZER RETURNED EMPTY - returning raw content]\n{body}")

    return (f"[SUMMARY of {rel} - {line_count} lines]\n"
            f"{summary}\n"
            f"[END SUMMARY]")
