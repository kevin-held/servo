import sys
from pathlib import Path
from core.path_utils import resolve, PathRejectedError, project_relative
from core.identity import get_system_defaults

TOOL_NAME        = "file_read"
TOOL_DESCRIPTION = "Read the contents of a file with support for pagination and summarization."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "path":      {"type": "string", "description": "Project-root-relative path to the file."},
    "max_lines": {"type": "integer", "description": "(Optional) Cap lines returned from the top. Ignored if 'block' is used."},
    "block":     {"type": "integer", "description": "(Optional) Zero-indexed 15000-char block to return for large files. Default 0."},
    "summarize": {"type": "boolean", "description": "(Optional) Return a semantic summary instead of raw text. Default false."},
}

_BLOCK_SIZE = get_system_defaults().get("registry", {}).get("BLOCK_SIZE", 15000)

def execute(path: str, max_lines: int = 0, block: int = 0, summarize: bool = False) -> str:
    try:
        p = resolve(path)
    except PathRejectedError as e:
        return f"Error: {e}"

    rel = project_relative(p)
    if not p.exists():
        return f"Error: '{rel}' does not exist."
    if p.is_dir():
        return f"Error: '{rel}' is a directory. Use 'file_list' instead."

    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading '{rel}': {e}"

    total_len = len(text)
    body = text
    footer = ""
    
    # 1. Pagination Logic
    total_blocks = max(1, (total_len + _BLOCK_SIZE - 1) // _BLOCK_SIZE)
    if block > 0 or total_len > _BLOCK_SIZE:
        if block < 0 or block >= total_blocks:
            return f"Error: block {block} out of range (0..{total_blocks-1})."
        start = block * _BLOCK_SIZE
        end = min(start + _BLOCK_SIZE, total_len)
        body = text[start:end]
        footer = f"\n\n[BLOCK {block} OF {total_blocks-1} - chars {start}..{end-1} of {total_len}]"
        if block + 1 < total_blocks:
            footer += f"\nCall 'file_read' with block={block+1} to continue."
    
    # 2. Max Lines (only if not paginating)
    elif max_lines > 0:
        lines = text.splitlines()
        if len(lines) > max_lines:
            body = "\n".join(lines[:max_lines])
            footer = f"\n\n[Showing first {max_lines} of {len(lines)} lines]"

    # 3. Summarization
    if summarize:
        body = _summarize_body(body, rel)

    return body + footer

def _summarize_body(body: str, rel: str) -> str:
    line_count = body.count("\n") + 1
    try:
        # Lazy import
        from tools.summarizer import summarize as _kernel_summarize
        rules = "Summarize the purpose, structure, and key components of this file. Paragraph form. No preamble."
        summary, _ = _kernel_summarize(body, rules)
        if not summary:
            return f"[SUMMARIZER EMPTY - returning raw]\n{body}"
        return f"[SUMMARY of {rel} - {line_count} lines]\n{summary}\n[END SUMMARY]"
    except Exception as e:
        return f"[SUMMARIZER FAILED: {e} - returning raw]\n{body}"
