import os
from pathlib import Path

TOOL_NAME = "analyze_directory"
TOOL_DESCRIPTION = "Analyze a directory structure by listing files, reading contents, and providing a summary of the project architecture. This tool streamlines directory exploration into a single call."
TOOL_ENABLED = True
TOOL_SCHEMA = {
    "directory": {"type": "string", "description": "The directory path to analyze (e.g., 'C:/Users/kevin/OneDrive/Desktop/ai')"},
    "max_files": {"type": "integer", "description": "Maximum number of files to read in detail (default: 10)"},
    "recursive": {"type": "boolean", "description": "Whether to scan subdirectories recursively (default: false)"}
}

def execute(directory: str, max_files: int = 10, recursive: bool = False) -> str:
    """
    Analyze directory structure and provide a comprehensive summary.
    
    Steps:
    1. List all files/folders in the target directory
    2. Read up to max_files of key files (prioritizing .py, .json, .md, .txt)
    3. Generate a structured analysis report
    """
    try:
        target_path = Path(directory)
        
        if not target_path.exists():
            return f"Error: Directory '{directory}' does not exist."
        
        if not target_path.is_dir():
            return f"Error: '{directory}' is not a directory."
        
        report = []
        report.append(f"=== DIRECTORY ANALYSIS: {directory} ===")
        report.append("")
        
        # Step 1: List structure
        report.append("[STRUCTURE]")
        files = []
        folders = []
        
        if recursive:
            for item in target_path.rglob("*"):
                if item.is_file():
                    files.append(item.relative_to(target_path))
                elif item.is_dir() and item.name != target_path.name:
                    folders.append(item.relative_to(target_path))
        else:
            for item in target_path.iterdir():
                if item.is_file():
                    files.append(item.name)
                elif item.is_dir():
                    folders.append(item.name)
        
        report.append(f"Folders ({len(folders)}): {', '.join(sorted(folders)[:20])}")
        report.append(f"Files ({len(files)}): {', '.join(sorted(files)[:20])}")
        report.append("")
        
        # Step 2: Read key files (prioritize common code/config extensions)
        priority_extensions = ['.py', '.json', '.md', '.txt', '.yaml', '.yml', '.toml', '.cfg', '.ini']
        priority_files = [f for f in files if any(str(f).endswith(ext) for ext in priority_extensions)]
        other_files = [f for f in files if f not in priority_files]
        
        files_to_read = priority_files[:max_files] + other_files[:max(0, max_files - len(priority_files))]
        
        report.append(f"[FILE CONTENTS] (Reading up to {max_files} files)")
        report.append("")
        
        files_read = 0
        for file_path in files_to_read:
            if files_read >= max_files:
                break
                
            full_path = target_path / file_path
            
            try:
                content = full_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.split('\n')
                line_count = len(lines)
                char_count = len(content)
                
                report.append(f"--- {file_path} ({line_count} lines, {char_count} chars) ---")
                
                # Show first 30 lines or full content if shorter
                preview_lines = min(30, line_count)
                preview = '\n'.join(lines[:preview_lines])
                report.append(preview)
                
                if line_count > 30:
                    report.append(f"... (truncated, {line_count - 30} more lines)")
                
                report.append("")
                files_read += 1
                
            except Exception as e:
                report.append(f"--- {file_path} ---")
                report.append(f"Error reading file: {e}")
                report.append("")
        
        # Step 3: Summary statistics
        report.append(f"[SUMMARY]")
        report.append(f"Total folders: {len(folders)}")
        report.append(f"Total files: {len(files)}")
        report.append(f"Files analyzed: {files_read}")
        report.append(f"Priority files found: {len(priority_files)}")
        report.append("")
        
        return '\n'.join(report)
        
    except Exception as e:
        return f"Error analyzing directory: {e}"
