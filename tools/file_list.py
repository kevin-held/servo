import os
from pathlib import Path
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "file_list"
TOOL_DESCRIPTION = "List files and directories to discover project structure."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "path":      {"type": "string", 
                  "description": "Project-root-relative directory path to list. Defaults to '.' (root)."},
    "recursive": {"type": "boolean", 
                  "description": "Whether to list subdirectories. Default false."},
    "depth":     {"type": "integer", 
                  "description": "(Optional) Maximum depth to recurse. Default infinity."},
}

_PRUNED_DIRS = {
    "__pycache__", ".git", ".hg", ".svn", "node_modules",
    ".venv", "venv", "env", ".env",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "old_stuff",
}

def execute(path: str = ".", recursive: bool = False, depth: int = -1) -> str:
    try:
        p = resolve(path)
    except PathRejectedError as e:
        return f"Error: {e}"

    if not p.exists():
        return f"Error: Path '{project_relative(p)}' does not exist."
    if not p.is_dir():
        return f"Error: Path '{project_relative(p)}' is a file. Use 'file_read' to inspect it."

    lines = []
    root_str = str(p)

    if not recursive:
        for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name)):
            prefix = "  " if item.is_file() else "FOLDER "
            lines.append(f"{prefix}{item.name}")
    else:
        for dirpath, dirnames, filenames in os.walk(root_str):
            # Prune in place
            dirnames[:] = [d for d in dirnames if d not in _PRUNED_DIRS]
            
            rel_dir = Path(dirpath).relative_to(root_str)
            current_depth = len(rel_dir.parts)
            
            if depth != -1 and current_depth >= depth:
                dirnames[:] = [] # stop recursing deeper
                
            sorted_dirs = sorted(dirnames)
            sorted_files = sorted(filenames)
            
            # Don't list the root folder itself in the lines
            if str(rel_dir) != ".":
                lines.append(f"FOLDER {rel_dir}")
                
            for f in sorted_files:
                f_path = rel_dir / f if str(rel_dir) != "." else Path(f)
                lines.append(f"  {f_path}")

    return "\n".join(lines) or "(empty)"
