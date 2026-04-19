import subprocess
import shlex
import os

TOOL_NAME        = "shell_exec"
TOOL_DESCRIPTION = ("Execute a shell command with standard shell semantics (quoting, "
                    "redirection, pipes). Restricted to allowed commands only: "
                    "dir, echo, type, ping, python, pytest, npm, npx, git.")
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "command": {"type": "string",  "description": "The shell command to run"},
    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
}

# Windows-native commands only — no Unix aliases (use 'dir' not 'ls', 'type' not 'cat')
ALLOWED_COMMANDS = {"dir", "echo", "type", "ping", "python", "pytest", "npm", "npx", "git"}


def execute(command: str, timeout: int = 30) -> str:
    # Parse only to validate the base command. We do NOT hand these tokens to
    # subprocess — on Windows, shlex.split(posix=False) preserves outer quotes
    # as part of the token, so `python -c "print('x')"` would send Python a
    # literal-quoted argv[2], which Python parses as a bare string literal
    # (no execution, no output, clean exit 0). That was the reported
    # "shell_exec returns no output" bug. Fix: let the actual shell parse
    # the command via shell=True, which handles quotes/redirects/pipes the
    # way the caller expects.
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as e:
        return f"Error parsing command: {e}"

    if not parts:
        return "(empty command)"

    base_cmd = parts[0].strip('"').lower()

    if base_cmd not in ALLOWED_COMMANDS:
        return (f"Error: Command '{base_cmd}' is not in the allowed list. "
                f"Valid commands: {', '.join(sorted(ALLOWED_COMMANDS))}.")

    try:
        result = subprocess.run(
            command,
            shell=True,
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
