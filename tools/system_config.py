"""
system_config — Allow the agent to inspect and adjust its own runtime configuration.

Operations:
  - get:  Return current model config (temperature, max_tokens, conversation_history, etc.)
  - set:  Modify a specific parameter at runtime
"""

import json
from pathlib import Path
from core.identity import get_system_defaults

TOOL_NAME        = "system_config"
TOOL_DESCRIPTION = (
    "Inspect or adjust the agent's own runtime configuration. "
    "Use 'get' to see current settings (temperature, max_tokens, conversation_history, "
    "chain_limit, autonomous_loop_limit, max_auto_continues, verbosity, and summarization toggles). "
    "Use 'set' to change a parameter at runtime. "
    "Use 'set_bound' to adjust the safety limits (min_value, max_value) for a numeric parameter."
)
TOOL_ENABLED     = True
TOOL_IS_SYSTEM   = True # Core State management
TOOL_SCHEMA      = {
    "operation": {
        "type": "string",
        "enum": ["get", "set", "set_bound", "save", "load"],
        "description": "Operation to perform. 'save' and 'load' require a filename in the 'value' parameter.",
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
            "stream_enabled",
            "summarize_contextualize",
            "summarize_history_integrate",
            "summarize_tool_results",
            "history_compression_trigger",
            "history_compression_target_chars",
            "tool_result_compression_threshold",
            "tool_result_compression_target_chars",
            "hardware_throttling_enabled",
            "hardware_throttle_threshold_enter",
            "hardware_throttle_threshold_exit",
        ],
        "description": "The parameter name to inspect or modify (ignored for 'save'/'load').",
    },
    "value": {
        "type": "string",
        "description": "For 'set': the new value. For 'save'/'load': the filename (e.g. 'my_preset.json').",
    },
    "min_value": {
        "type": "string",
        "description": "(For 'set_bound') The new minimum safety limit.",
    },
    "max_value": {
        "type": "string",
        "description": "(For 'set_bound') The new maximum safety limit.",
    },
}


# Default safety bounds — loaded from system_defaults.json at runtime
def _get_default_bounds():
    return get_system_defaults().get("bounds", {
        "temperature":                         (0.0, 1.5),
        "max_tokens":                          (256, 16384),
        "conversation_history":                (3, 40),
        "chain_limit":                         (1, 20),
        "autonomous_loop_limit":               (0, 1000),
        "max_auto_continues":                  (0, 1000),
        "history_compression_trigger":         (1.0, 10.0),
        "history_compression_target_chars":    (100, 5000),
        "tool_result_compression_threshold":    (0, 50000),
        "tool_result_compression_target_chars": (50, 5000),
        "hardware_throttle_threshold_enter":    (50.0, 99.0),
        "hardware_throttle_threshold_exit":     (50.0, 99.0),
    })

_VERBOSITY_OPTIONS = {"Concise", "Normal", "Standard", "Detailed"}


def _get_loop_ref():
    """Resolve a reference to the running CoreLoop instance."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None: return None
        for widget in app.topLevelWidgets():
            if hasattr(widget, "loop"): return widget.loop
    except Exception: pass
    return None


def _get_bounds(loop, parameter: str) -> tuple[float, float]:
    """Load dynamic bounds from state, falling back to defaults."""
    default_min, default_max = _get_default_bounds().get(parameter, (None, None))
    if default_min is None: return None, None
    s_min = loop.state.get(f"bound_min_{parameter}", str(default_min))
    s_max = loop.state.get(f"bound_max_{parameter}", str(default_max))
    try:
        return float(s_min), float(s_max)
    except (ValueError, TypeError):
        return default_min, default_max


def _set_parameter(loop, parameter: str, value: str) -> str:
    """Delegates parameter management to the core Registry (v1.0.0)."""
    if not hasattr(loop, "config"):
        return f"Error: CoreLoop does not have a config registry."
    
    return loop.config.set(parameter, value, loop_ref=loop)


def execute(operation: str = "get", parameter: str = "", value: str = "",
            min_value: str = "", max_value: str = "", *, tool_context=None) -> str:
    # Phase F (UPGRADE_PLAN_5 sec 5) -- tool_context kwarg lets the
    # Cognate dispatch surface inject a CoreLoop-like reference directly,
    # superseding the lx_loop_shim's monkey-patch of _get_loop_ref. Resolution
    # order: tool_context.legacy_loop_ref (the LxLoopAdapter or a real
    # CoreLoop) wins; otherwise fall through to the legacy QApplication
    # discovery path. Reads are duck-typed so this file stays independent
    # of core/tool_context.py imports.
    #
    # Note: this tool reads the rich GUI-thread knobs (conversation_history,
    # chain_limit, ...) directly off the loop ref. Those still live on
    # ServoCoreThread / CoreLoop, not in tool_context's narrow surface, so
    # we still need a loop ref of some kind. Phase G+ may broaden the
    # context to carry those knobs natively.
    loop = None
    if tool_context is not None:
        legacy = getattr(tool_context, "legacy_loop_ref", None)
        if legacy is not None:
            loop = legacy
    if loop is None:
        loop = _get_loop_ref()
    if loop is None:
        return "Error: Could not access the running CoreLoop instance."

    operation = operation.lower().strip()
    parameter = parameter.lower().strip()

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
            "stream_enabled":        loop.stream_enabled,
            "summarize_contextualize":            loop.state.get("summarize_contextualize", "True"),
            "summarize_history_integrate":        loop.state.get("summarize_history_integrate", "True"),
            "summarize_tool_results":             loop.state.get("summarize_tool_results", "True"),
            "history_compression_trigger":        loop.state.get("history_compression_trigger", "2"),
            "history_compression_target_chars":   loop.state.get("history_compression_target_chars", "800"),
            "tool_result_compression_threshold":   loop.state.get("tool_result_compression_threshold", "4000"),
            "tool_result_compression_target_chars":  loop.state.get("tool_result_compression_target_chars", "500"),
            "hardware_throttling_enabled":        loop.hardware_throttling_enabled,
            "hardware_throttle_threshold_enter":  loop.hardware_throttle_threshold_enter,
            "hardware_throttle_threshold_exit":   loop.hardware_throttle_threshold_exit,
        }
        if parameter: # allow getting single key
            return json.dumps({parameter: config.get(parameter)}, indent=2)
        config["_safety_bounds"] = {k: _get_bounds(loop, k) for k in _get_default_bounds()}
        return json.dumps(config, indent=2)

    elif operation == "set":
        return _set_parameter(loop, parameter, value)

    elif operation == "set_bound":
        if not parameter: return "Error: 'parameter' is required."
        if parameter not in _get_default_bounds(): return "Error: Bounds not supported for this parameter."
        status = []
        if min_value:
            loop.state.set(f"bound_min_{parameter}", min_value)
            status.append(f"min={min_value}")
        if max_value:
            loop.state.set(f"bound_max_{parameter}", max_value)
            status.append(f"max={max_value}")
        loop.config_changed.emit(f"bound_{parameter}", _get_bounds(loop, parameter))
        return f"✓ safety bounds for '{parameter}' updated: " + ", ".join(status)

    elif operation == "save":
        if not value: return "Error: Filename required in 'value' parameter."
        if "/" in value or "\\" in value: return "Error: Filename only, no paths allowed."
        if not value.endswith(".json"): value += ".json"
        
        # Build config object (reuse get logic)
        config_raw = execute(operation="get")
        config = json.loads(config_raw)
        if "_safety_bounds" in config: del config["_safety_bounds"]
        
        try:
            config_dir = Path("configs")
            config_dir.mkdir(exist_ok=True)
            with open(config_dir / value, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return f"✓ Configuration saved to configs/{value}"
        except Exception as e:
            return f"Error saving config: {e}"

    elif operation == "load":
        if not value: return "Error: Filename required in 'value' parameter."
        if not value.endswith(".json"): value += ".json"
        path = Path("configs") / value
        if not path.exists(): return f"Error: Config file '{path}' not found."
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            results = []
            for k, v in data.items():
                if k == "model":
                    loop.ollama.model = str(v)
                    # We don't have a direct loop signal for model change yet, 
                    # main_window handles it but loop doesn't emit it.
                    results.append(f"model={v}")
                    continue
                res = _set_parameter(loop, k, str(v))
                results.append(res)
            
            return f"✓ Configuration loaded from {value}:\n" + "\n".join(results)
        except Exception as e:
            return f"Error loading config: {e}"

    return "Error: Unknown operation. Use 'get', 'set', 'set_bound', 'save', or 'load'."
