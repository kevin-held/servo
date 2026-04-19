import os
import sys
import time
from pathlib import Path

# Route every model-provided path through the single-anchor resolver.
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from core.path_utils import resolve, PathRejectedError, project_relative

TOOL_NAME        = "analyze_directory"
TOOL_DESCRIPTION = "Analyze a directory structure by listing files, reading contents, and providing a summary of the project architecture. This tool streamlines directory exploration into a single call."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "directory":  {"type": "string",
                   "description": "Project-root-relative directory path to analyze. "
                                  "Examples: 'codex', 'tools', 'workspace/gemma4_26b'. "
                                  "Absolute paths and drive letters are rejected — "
                                  "the project root is managed by the tool."},
    "max_files":  {"type": "integer",
                   "description": "Maximum number of files to read in detail (default: 8). "
                                  "The tool also enforces a total output budget so files beyond "
                                  "the budget are listed but not previewed."},
    "recursive":  {"type": "boolean",
                   "description": "Whether to scan subdirectories recursively (default: false). "
                                  "Noise dirs like __pycache__, .git, old_stuff, node_modules, "
                                  ".venv are always pruned."},
}

# Directory names that are skipped during recursive traversal. These dump a lot
# of files but rarely contribute anything the model wants to reason about, and
# before pruning the tool could spend seconds stat'ing every compiled .pyc or
# every archived proposal in old_stuff/.
_PRUNED_DIRS = {
    "__pycache__", ".git", ".hg", ".svn", "node_modules",
    ".venv", "venv", "env", ".env",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "old_stuff",
}

# Output budget. Keeps the full report under the tool_registry's 16000-char
# MAX_TOOL_OUTPUT cap so the [SUMMARY] footer is never clipped. The budget is
# soft: we stop adding previews once we cross it, but always append the summary.
_OUTPUT_BUDGET = 12000
# Per-file preview caps. Smaller than the old (30 lines) default so that
# max_files=8 can't alone eat the whole budget.
_PREVIEW_LINES = 20
_PREVIEW_CHARS = 1500


def _walk_pruned(root):
    """Iterate (file_paths, dir_paths) under root with _PRUNED_DIRS skipped.

    Returns two lists of paths relative to root. Uses os.walk so we can mutate
    `dirnames` in place to prune subtrees before they're descended into —
    Path.rglob has no equivalent hook and would happily walk into
    workspace/<model>/old_stuff/ or .venv/.
    """
    files = []
    folders = []
    root_str = str(root)
    for dirpath, dirnames, filenames in os.walk(root_str):
        # Prune in place so os.walk never descends into noise dirs.
        dirnames[:] = [d for d in dirnames if d not in _PRUNED_DIRS]
        rel_dir = Path(dirpath).relative_to(root_str)
        for d in dirnames:
            folders.append(rel_dir / d if str(rel_dir) != "." else Path(d))
        for f in filenames:
            files.append(rel_dir / f if str(rel_dir) != "." else Path(f))
    return files, folders


def execute(directory: str, max_files: int = 8, recursive: bool = False) -> str:
    """
    Analyze directory structure and provide a comprehensive summary.

    Steps:
    1. List files/folders in the target directory (noise dirs pruned when recursive)
    2. Read up to max_files of key files, bounded by a total output budget
    3. Generate a structured analysis report
    """
    try:
        # Route through the single-anchor resolver. Rejection text is returned
        # to the model as the tool output — see decisions.md D-20260417-09.
        try:
            target_path = resolve(directory)
        except PathRejectedError as e:
            return f"Error: {e}"

        rel_display = project_relative(target_path)

        if not target_path.exists():
            return f"Error: Directory '{rel_display}' does not exist."

        if not target_path.is_dir():
            return f"Error: '{rel_display}' is not a directory."

        report = []
        report.append(f"=== DIRECTORY ANALYSIS: {rel_display} ===")
        report.append("")

        # Step 1: List structure
        report.append("[STRUCTURE]")

        if recursive:
            files, folders = _walk_pruned(target_path)
        else:
            files, folders = [], []
            for item in target_path.iterdir():
                if item.is_file():
                    files.append(Path(item.name))
                elif item.is_dir() and item.name not in _PRUNED_DIRS:
                    folders.append(Path(item.name))

        report.append(f"Folders ({len(folders)}): {', '.join(str(f) for f in sorted(folders, key=str)[:20])}")

        # Cap listing to avoid overflow. Still stat each listed file for mtime —
        # but only for the ones we actually render, not all N.
        sorted_files = sorted(files, key=str)
        listed = sorted_files[:50]
        report.append(f"Files ({len(files)}{', showing first 50' if len(files) > 50 else ''}):")
        for f in listed:
            full_path = target_path / f
            try:
                mtime = os.path.getmtime(full_path)
                mtime_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
                report.append(f"  - {f} (Modified: {mtime_str})")
            except OSError:
                report.append(f"  - {f}")
        report.append("")

        # Step 2: Read key files (prioritize common code/config extensions)
        priority_extensions = ('.py', '.json', '.md', '.txt', '.yaml', '.yml', '.toml', '.cfg', '.ini')
        priority_files = [f for f in sorted_files if str(f).lower().endswith(priority_extensions)]
        other_files    = [f for f in sorted_files if f not in priority_files]

        files_to_read = priority_files[:max_files] + other_files[:max(0, max_files - len(priority_files))]

        report.append(f"[FILE CONTENTS] (Reading up to {max_files} files, output budget {_OUTPUT_BUDGET} chars)")
        report.append("")

        files_read = 0
        budget_hit = False
        running_chars = sum(len(line) + 1 for line in report)

        for file_path in files_to_read:
            if files_read >= max_files:
                break
            if running_chars >= _OUTPUT_BUDGET:
                budget_hit = True
                break

            full_path = target_path / file_path

            try:
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.splitlines()
                line_count = len(lines)
                char_count = len(content)

                header = f"--- {file_path} ({line_count} lines, {char_count} chars) ---"
                preview = '\n'.join(lines[:_PREVIEW_LINES])
                if len(preview) > _PREVIEW_CHARS:
                    preview = preview[:_PREVIEW_CHARS] + f"\n... (char-truncated at {_PREVIEW_CHARS})"

                chunk_lines = [header, preview]
                if line_count > _PREVIEW_LINES:
                    chunk_lines.append(f"... (truncated, {line_count - _PREVIEW_LINES} more lines)")
                chunk_lines.append("")

                chunk_chars = sum(len(line) + 1 for line in chunk_lines)
                # Don't push over the budget mid-file — if this file would blow
                # it, stop here so the summary footer still lands.
                if running_chars + chunk_chars > _OUTPUT_BUDGET and files_read > 0:
                    budget_hit = True
                    break

                report.extend(chunk_lines)
                running_chars += chunk_chars
                files_read += 1

            except Exception as e:
                report.append(f"--- {file_path} ---")
                report.append(f"Error reading file: {e}")
                report.append("")

        if budget_hit:
            report.append(f"[NOTE] Output budget ({_OUTPUT_BUDGET} chars) reached — "
                          f"{files_read} of {len(files_to_read)} targeted files previewed. "
                          f"Use filesystem:read on specific paths above for the rest.")
            report.append("")

        # Step 3: Summary statistics
        report.append("[SUMMARY]")
        report.append(f"Total folders: {len(folders)}")
        report.append(f"Total files: {len(files)}")
        report.append(f"Files analyzed: {files_read}")
        report.append(f"Priority files found: {len(priority_files)}")
        report.append("")

        return '\n'.join(report)

    except Exception as e:
        return f"Error analyzing directory: {e}"
        
