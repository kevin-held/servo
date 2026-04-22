import os
import json
import re
from pathlib import Path
from core.identity import get_system_defaults

class ConfigRegistry:
    """
    Centralized Configuration Engine for Servo.
    
    Resolution Order:
    1. Environment Variables (SERVO_PARAMETER_NAME)
    2. Persistent Store (StateStore)
    3. System Defaults (system_defaults.json)
    
    Responsibilities:
    - Type Enforcement (int, float, bool, enum)
    - Safety Bounds (Min/Max checking)
    - Hot-Injecting parameters into the running Loop and Ollama clients.
    """

    def __init__(self, state, ollama_client):
        self.state = state
        self.ollama = ollama_client
        self.defaults = get_system_defaults()
        
        # v1.0.1 (D-20260421-16): Strictly use JSON bounds (no hardcoded fallbacks)
        self.bounds = self.defaults.get("bounds", {})
        
        # Build a type-map from the defaults to automate casting
        self._type_map = {k: type(v) for k, v in self.defaults.get("defaults", {}).items()}
        
        # Explicit overrides for keys that might not be in defaults or need special handling
        self._type_map.update({
            "stream_enabled": bool,
            "ui_show_thinking": bool,
            "hardware_throttling_enabled": bool
        })
        
        self.verbosity_options = {"Concise", "Normal", "Standard", "Detailed"}

    def get(self, key: str, fallback=None) -> any:
        """Resolves a parameter through the hierarchy."""
        # v1.0.1: If fallback is not provided, look it up in the JSON defaults
        if fallback is None:
            fallback = self.defaults.get("defaults", {}).get(key)

        # 1. Environment Variable Override (Tier 1)
        env_key = f"SERVO_{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return self._cast_value(key, env_val)

        # 2. State Store (Tier 2)
        state_val = self.state.get(key)
        if state_val is not None:
            return self._cast_value(key, state_val)

        # 3. Fallback / Defaults (Tier 3)
        return self._cast_value(key, fallback)

    def set(self, key: str, value: any, loop_ref=None) -> str:
        """
        Validates and persists a configuration change.
        Updates memory objects immediately if loop_ref is provided.
        """
        try:
            # 1. Type Casting & Normalization
            val = self._cast_value(key, value)
            
            # 2. Safety Bounds Check
            if key in self.bounds:
                bounds_pair = self.bounds[key]
                if isinstance(bounds_pair, list) and len(bounds_pair) == 2:
                    lo, hi = bounds_pair
                    # Allow dynamic overrides of bounds from state if they exist
                    lo = float(self.state.get(f"bound_min_{key}", str(lo)))
                    hi = float(self.state.get(f"bound_max_{key}", str(hi)))
                    
                    if not (lo <= val <= hi):
                        return f"Error: {key} out of bounds ({lo}-{hi}). Received {val}."

            # 3. Enum Validation
            if key == "verbosity" and val not in self.verbosity_options:
                return f"Error: verbosity must be one of {self.verbosity_options}."

            # 4. Persistence
            self.state.set(key, str(val))

            # 5. Immediate Live Injection (Memory Sync)
            if loop_ref:
                self._apply_to_memory(loop_ref, key, val)

            return f"✓ {key} calibrated to {val}"

        except Exception as e:
            return f"Error calibrating {key}: {e}"

    def _cast_value(self, key: str, value: any) -> any:
        """Coerces input into the expected type based on the JSON default's type."""
        if value is None: return None
        
        target_type = self._type_map.get(key, type(value))

        if target_type == bool:
            if isinstance(value, bool): return value
            return str(value).lower() in ("true", "1", "yes", "on")
        
        if target_type == float:
            return float(value)
            
        if target_type == int:
            return int(float(value))

        return str(value)

    def _apply_to_memory(self, loop, key, value):
        """Routes a validated value to the correct in-memory attribute."""
        # Special routing for Ollama settings
        if key == "temperature":
            loop.ollama.temperature = value
        elif key == "max_tokens":
            loop.ollama.num_predict = value
        # Standard kernel attributes
        else:
            if hasattr(loop, key):
                setattr(loop, key, value)
            
        # Emit signal for GUI sync (if loop has the signal)
        if hasattr(loop, "config_changed"):
            loop.config_changed.emit(key, value)
