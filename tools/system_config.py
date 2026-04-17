"""
system_config — Allow the agent to inspect and adjust its own runtime configuration.

Operations:
  - get:  Return current model config (temperature, max_tokens, context_limit, etc.)
  - set:  Modify a specific parameter at runtime
"""

import json
import sys
from pathlib import Path

TOOL_NAME        = "system_config"
TOOL_DESCRIPTION = (
    "Inspect or adjust the agent's own runtime configuration. "
    "Use 'get' to see current settings (temperature, max_tokens, context_limit, loop_limit). "
    "Use 'set' to change a parameter at runtime — useful when responses are being truncated "
    "(increase max_tokens) or when hardware is under pressure (decrease context_limit)."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "operation": {
        "type": "string",
        "enum": ["get", "set"],
        "description": "Either 'get' (read current config) or 'set' (change a value).",
    },
    "parameter": {
        "type": "string",
        "enum": ["temperature", "max_tokens", "context_limit", "loop_limit", "verbosity"],
        "description": "(For 'set') The parameter name to modify.",
    },
    "value": {
        "type": "string",
        "description": "(For 'set') The new value. Numbers should be passed as strings (e.g., '4096').",
    },
}

# Safe bounds to prevent the model from setting dangerous values
_BOUNDS = {
    "temperature":   (0.0, 1.5),
    "max_tokens":    (256, 16384),
    "context_limit": (3, 30),
    "loop_limit":    (1, 20),
}

_VERBOSITY_OPTIONS = {"Concise", "Normal", "Standard", "Detailed"}


def _get_loop_ref():
    """
    Resolve a reference to the running CoreLoop instance.
    The loop is started as a QThread from MainWindow, so we access it
    through the Qt application's widget tree.
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return None
        for widget in app.topLevelWidgets():
            if hasattr(widget, "loop"):
                return widget.loop
    except Exception:
        pass
    return None


def execute(operation: str = "get", parameter: str = "", value: str = "") -> str:
    loop = _get_loop_ref()
    if loop is None:
        return "Error: Could not access the running CoreLoop instance."

    if operation == "get":
        config = {
            "model":         loop.ollama.model,
            "temperature":   loop.ollama.temperature,
            "max_tokens":    loop.ollama.num_predict,
            "context_limit": loop.context_limit,
            "loop_limit":    loop.loop_limit,
            "verbosity":     loop.verbosity,
            "continuous_mode": loop.continuous_mode,
            "stream_enabled":  loop.stream_enabled,
        }
        return json.dumps(config, indent=2)

    elif operation == "set":
        if not parameter:
            return "Error: 'parameter' is required for 'set' operation."
        if not value:
            return "Error: 'value' is required for 'set' operation."

        parameter = parameter.lower().strip()

        try:
            if parameter == "temperature":
                new_val = float(value)
                lo, hi = _BOUNDS["temperature"]
                if not (lo <= new_val <= hi):
                    return f"Error: temperature must be between {lo} and {hi}. Got {new_val}."
                loop.ollama.temperature = new_val
                return f"✓ temperature set to {new_val}"

            elif parameter == "max_tokens":
                new_val = int(value)
                lo, hi = _BOUNDS["max_tokens"]
                if not (lo <= new_val <= hi):
                    return f"Error: max_tokens must be between {lo} and {hi}. Got {new_val}."
                loop.ollama.num_predict = new_val
                return f"✓ max_tokens set to {new_val}"

            elif parameter == "context_limit":
                new_val = int(value)
                lo, hi = _BOUNDS["context_limit"]
                if not (lo <= new_val <= hi):
                    return f"Error: context_limit must be between {lo} and {hi}. Got {new_val}."
                loop.context_limit = new_val
                return f"✓ context_limit set to {new_val}"

            elif parameter == "loop_limit":
                new_val = int(value)
                lo, hi = _BOUNDS["loop_limit"]
                if not (lo <= new_val <= hi):
                    return f"Error: loop_limit must be between {lo} and {hi}. Got {new_val}."
                loop.loop_limit = new_val
                return f"✓ loop_limit set to {new_val}"

            elif parameter == "verbosity":
                if value not in _VERBOSITY_OPTIONS:
                    return f"Error: verbosity must be one of {_VERBOSITY_OPTIONS}. Got '{value}'."
                loop.verbosity = value
                return f"✓ verbosity set to '{value}'"

            else:
                return f"Error: Unknown parameter '{parameter}'. Valid: temperature, max_tokens, context_limit, loop_limit, verbosity."

        except (ValueError, TypeError) as e:
            return f"Error: Invalid value '{value}' for {parameter}: {e}"

    else:
        return f"Error: Unknown operation '{operation}'. Use 'get' or 'set'."
