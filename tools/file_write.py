import os
from pathlib import Path
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "file_write"
TOOL_DESCRIPTION = "Create, overwrite, or append content to a file."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "path":    {"type": "string", "description": "Project-root-relative path to the file."},
    "content": {"type": "string", "description": "Text to write to the file."},
    "append":  {"type": "boolean", "description": "If true, add to end of file instead of overwriting. Default false."},
}

def execute(path: str, content: str, append: bool = False) -> str:
    try:
        p = resolve(path)
    except PathRejectedError as e:
        return f"Error: {e}"

    rel = project_relative(p)
    p.parent.mkdir(parents=True, exist_ok=True)

    try:
        if append:
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended {len(content)} chars to '{rel}'."
        else:
            p.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} chars to '{rel}'."
    except Exception as e:
        return f"Error writing to '{rel}': {e}"
