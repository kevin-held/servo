"""
system_config — Allow the agent to inspect and adjust its own runtime configuration.

Operations:
  - get:  Return current model config (temperature, max_tokens, conversation_history, etc.)
  - set:  Modify a specific parameter at runtime
"""

import json
from pathlib import Path

TOOL_NAME        = "system_config"
TOOL_DESCRIPTION = (
    "Inspect or adjust the agent's own runtime configuration. "
    "Use 'get' to see current settings (temperature, max_tokens, conversation_history, "
    "chain_limit, autonomous_loop_limit, max_auto_continues, verbosity). "
    "Use 'set' to change a parameter at runtime — useful when responses are being truncated "
    "(increase max_tokens or max_auto_continues), when hardware is under pressure "
    "(decrease conversation_history), or when continuous-mode runs should auto-pause "
    "after N cycles (set autonomous_loop_limit > 0)."
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
        "enum": [
            "temperature",
            "max_tokens",
            "conversation_history",
            "chain_limit",
            "autonomous_loop_limit",
            "max_auto_continues",
            "verbosity",
        ],
        "description": "(For 'set') The parameter name to modify.",
    },
    "value": {
        "type": "string",
        "description": "(For 'set') The new value. Numbers should be passed as strings (e.g., '4096').",
    },
}

# Safe bounds to prevent the model from setting dangerous values
_BOUNDS = {
    "temperature":             (0.0, 1.5),
    "max_tokens":              (256, 16384),
    "conversation_history":    (3, 30),
    "chain_limit":             (1, 20),
    "autonomous_loop_limit":   (0, 50),   # 0 = unbounded continuous mode
    "max_auto_continues":      (0, 5),
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
            "model":                 loop.ollama.model,
            "temperature":           loop.ollama.temperature,
            "max_tokens":            loop.ollama.num_predict,
            "conversation_history":  loop.conversation_history,
            "chain_limit":           loop.chain_limit,
            "autonomous_loop_limit": loop.autonomous_loop_limit,
            "max_auto_continues":    loop.max_auto_continues,
            "verbosity":             loop.verbosity,
            "continuous_mode":       loop.continuous_mode,
            "stream_enabled":        loop.stream_enabled,
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
                loop.config_changed.emit("temperature", new_val)
                return f"✓ temperature set to {new_val}"

            elif parameter == "max_tokens":
                new_val = int(value)
                lo, hi = _BOUNDS["max_tokens"]
                if not (lo <= new_val <= hi):
                    return f"Error: max_tokens must be between {lo} and {hi}. Got {new_val}."
                loop.ollama.num_predict = new_val
                loop.config_changed.emit("max_tokens", new_val)
                return f"✓ max_tokens set to {new_val}"

            elif parameter == "conversation_history":
                new_val = int(value)
                lo, hi = _BOUNDS["conversation_history"]
                if not (lo <= new_val <= hi):
                    return f"Error: conversation_history must be between {lo} and {hi}. Got {new_val}."
                loop.conversation_history = new_val
                loop.config_changed.emit("conversation_history", new_val)
                return f"✓ conversation_history set to {new_val}"

            elif parameter == "chain_limit":
                new_val = int(value)
                lo, hi = _BOUNDS["chain_limit"]
                if not (lo <= new_val <= hi):
                    return f"Error: chain_limit must be between {lo} and {hi}. Got {new_val}."
                loop.chain_limit = new_val
                loop.config_changed.emit("chain_limit", new_val)
                return f"✓ chain_limit set to {new_val}"

            elif parameter == "autonomous_loop_limit":
                new_val = int(value)
                lo, hi = _BOUNDS["autonomous_loop_limit"]
                if not (lo <= new_val <= hi):
                    return f"Error: autonomous_loop_limit must be between {lo} and {hi}. Got {new_val}."
                loop.autonomous_loop_limit = new_val
                loop.config_changed.emit("autonomous_loop_limit", new_val)
                if new_val == 0:
                    return "✓ autonomous_loop_limit set to 0 (unbounded continuous mode)"
                return f"✓ autonomous_loop_limit set to {new_val} cycles before pause"

            elif parameter == "max_auto_continues":
                new_val = int(value)
                lo, hi = _BOUNDS["max_auto_continues"]
                if not (lo <= new_val <= hi):
                    return f"Error: max_auto_continues must be between {lo} and {hi}. Got {new_val}."
                loop.max_auto_continues = new_val
                loop.config_changed.emit("max_auto_continues", new_val)
                return f"✓ max_auto_continues set to {new_val}"

            elif parameter == "verbosity":
                if value not in _VERBOSITY_OPTIONS:
                    return f"Error: verbosity must be one of {_VERBOSITY_OPTIONS}. Got '{value}'."
                loop.verbosity = value
                loop.config_changed.emit("verbosity", value)
                return f"✓ verbosity set to '{value}'"

            else:
                return (
                    f"Error: Unknown parameter '{parameter}'. "
                    "Valid: temperature, max_tokens, conversation_history, chain_limit, "
                    "autonomous_loop_limit, max_auto_continues, verbosity."
                )

        except (ValueError, TypeError) as e:
            return f"Error: Invalid value '{value}' for {parameter}: {e}"

    else:
        return f"Error: Unknown operation '{operation}'. Use 'get' or 'set'."
