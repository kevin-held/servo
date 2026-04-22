import os
import re
from pathlib import Path
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "map_project"
TOOL_DESCRIPTION = "Generate a symbol-aware map of a project directory (classes, functions, methods)."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "path": {"type": "string", "description": "Project-relative directory to map. Defaults to '.'."},
    "depth": {"type": "integer", "description": "(Optional) Maximum recursion depth. Default 2."},
}

# Regex patterns for symbol extraction
PATTERNS = {
    ".py": [
        (r"class\s+([a-zA-Z0-9_]+)", "CLASS"),
        (r"def\s+([a-zA-Z0-9_]+)\(", "FUNC"),
    ],
    ".js": [
        (r"class\s+([a-zA-Z0-9_]+)", "CLASS"),
        (r"function\s+([a-zA-Z0-9_]+)\(", "FUNC"),
        (r"const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", "ARROW"),
    ],
    # Add more as needed (md for headings, etc.)
}

_SKIP_DIRS = {
    "__pycache__", ".git", "node_modules", ".venv", "env", "venv", 
    "dist", "build", "old_stuff", ".pytest_cache"
}

def _extract_symbols(file_path: Path) -> list:
    ext = file_path.suffix.lower()
    if ext not in PATTERNS:
        return []
    
    symbols = []
    try:
        content = file_path.read_text(encoding="utf-8")
        for pattern, label in PATTERNS[ext]:
            matches = re.findall(pattern, content)
            for m in matches:
                symbols.append(f"{label}:{m}")
    except Exception:
        pass
    return symbols

def execute(path: str = ".", depth: int = 2) -> str:
    try:
        p = resolve(path)
    except PathRejectedError as e:
        return f"Error: {e}"

    if not p.is_dir():
        return f"Error: '{project_relative(p)}' is not a directory."

    lines = [f"=== PROJECT MAP: {project_relative(p)} ==="]
    root_str = str(p)

    for dirpath, dirnames, filenames in os.walk(root_str):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        
        rel_dir = Path(dirpath).relative_to(root_str)
        current_depth = len(rel_dir.parts)
        
        if depth != -1 and current_depth >= depth:
            dirnames[:] = []
            continue

        for f in sorted(filenames):
            if f.startswith(".") or f.startswith("_"): continue
            f_path = Path(dirpath) / f
            symbols = _extract_symbols(f_path)
            
            f_rel = f_path.relative_to(p)
            if symbols:
                sym_str = " | ".join(symbols[:10])
                if len(symbols) > 10: sym_str += " ..."
                lines.append(f"  {f_rel} -> [{sym_str}]")
            else:
                lines.append(f"  {f_rel}")

    return "\n".join(lines) or "(empty)"
