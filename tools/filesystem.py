from pathlib import Path

TOOL_NAME        = "filesystem"
TOOL_DESCRIPTION = "Read, write, append, or list files and directories on disk"
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "operation": {"type": "string", "enum": ["read", "write", "append", "list"],
                  "description": "Operation to perform. 'append' adds content to end of file without overwriting."},
    "path":      {"type": "string", "description": "File or directory path"},
    "content":   {"type": "string", "description": "Content to write or append (write/append only)"},
    "max_lines": {"type": "integer", "description": "(Optional) Max lines to read. Use for large files to avoid context overflow."},
}


def execute(operation: str, path: str, content: str = "", max_lines: int = 0) -> str:
    try:
        p = Path(path).resolve()
    except Exception as e:
        return f"Error resolving path: {e}"
        
    base_dir = Path(__file__).parent.parent.resolve()
    
    # Enforce path sandbox (case-insensitive for Windows)
    if not str(p).lower().startswith(str(base_dir).lower()):
        return f"Error: Access denied. Path '{path}' is outside the allowed workspace sandbox."

    if operation == "read":
        if not p.exists():
            return f"Error: '{path}' does not exist"
        if p.is_dir():
            return f"Error: '{path}' is a directory — use list"

        text = p.read_text(encoding="utf-8")

        # Optional line cap for large files
        if max_lines and max_lines > 0:
            lines = text.splitlines()
            if len(lines) > max_lines:
                truncated = "\n".join(lines[:max_lines])
                return truncated + f"\n\n[Showing first {max_lines} of {len(lines)} total lines]"

        return text

    elif operation == "write":
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to '{path}'"

    elif operation == "list":
        if not p.exists():
            return f"Error: '{path}' does not exist"
        if p.is_file():
            return str(p)
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = []
        for entry in entries:
            prefix = "  " if entry.is_file() else "📁 "
            lines.append(f"{prefix}{entry.name}")
        return "\n".join(lines) or "(empty)"

    elif operation == "append":
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} chars to '{path}'"

    else:
        return f"Unknown operation: '{operation}'. Use read, write, append, or list."

