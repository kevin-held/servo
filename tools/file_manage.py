import shutil
import os
from pathlib import Path
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "file_manage"
TOOL_DESCRIPTION = "Move, rename, or delete files and directories."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "operation": {"type": "string", "enum": ["move", "delete"], 
                  "description": "Operation to perform. 'move' handles both rename and move."},
    "path":      {"type": "string", "description": "Project-relative path to the source file/folder."},
    "dest":      {"type": "string", "description": "(Move only) Project-relative destination path. Intermediate folders will be created."},
}

def execute(operation: str, path: str, dest: str = "") -> str:
    try:
        p = resolve(path)
    except PathRejectedError as e:
        return f"Error: {e}"

    rel = project_relative(p)
    if not p.exists():
        return f"Error: '{rel}' does not exist."

    if operation == "move":
        if not dest:
            return "Error: move requires a 'dest' argument."
        try:
            q = resolve(dest)
        except PathRejectedError as e:
            return f"Error: {e}"
        
        if q.exists():
            return f"Error: destination '{project_relative(q)}' already exists. Refuse to overwrite."
        
        q.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(p), str(q))
            return f"Moved '{rel}' -> '{project_relative(q)}'."
        except OSError as e:
            return f"Error moving: {e}"

    elif operation == "delete":
        try:
            if p.is_dir():
                shutil.rmtree(p)
                return f"Deleted directory '{rel}' and all its contents."
            else:
                p.unlink()
                return f"Deleted file '{rel}'."
        except OSError as e:
            return f"Error deleting: {e}"

    return f"Error: Unknown operation '{operation}'."
