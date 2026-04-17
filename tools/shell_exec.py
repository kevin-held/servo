import subprocess
import shlex
import os

TOOL_NAME        = "shell_exec"
TOOL_DESCRIPTION = "Execute a shell command. Restricted to allowed commands only: dir, echo, type, ping, python, pytest, npm, npx, git."
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "command": {"type": "string",  "description": "The shell command to run"},
    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
}

# Windows-native commands only — no Unix aliases (use 'dir' not 'ls', 'type' not 'cat')
ALLOWED_COMMANDS = {"dir", "echo", "type", "ping", "python", "pytest", "npm", "npx", "git"}

# Windows cmd.exe builtins — these are not standalone .exe files and require shell=True
_WINDOWS_BUILTINS = {"echo", "dir", "type", "cd", "set", "cls", "copy", "del", "ren"}

def execute(command: str, timeout: int = 30) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as e:
        return f"Error parsing command: {e}"

    if not parts:
        return "(empty command)"

    base_cmd = parts[0].lower()
    
    if base_cmd not in ALLOWED_COMMANDS:
        return f"Error: Command '{base_cmd}' is not in the allowed list. Valid commands: {', '.join(sorted(ALLOWED_COMMANDS))}."

    # On Windows, built-in commands (echo, dir, type) exist inside cmd.exe,
    # not as standalone executables. They require shell=True to resolve.
    use_shell = (os.name == "nt" and base_cmd in _WINDOWS_BUILTINS)

    try:
        result = subprocess.run(
            command if use_shell else parts,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return f"Error: Command '{base_cmd}' could not be found. Is it installed and on PATH?"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        return f"Execution error: {e}"
    out = result.stdout
    if result.stderr:
        out += f"\nSTDERR:\n{result.stderr}"
    if result.returncode != 0:
        out += f"\n[exit code {result.returncode}]"
    return out.strip() or "(no output)"

