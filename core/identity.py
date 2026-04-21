import json
from pathlib import Path

_IDENTITY_PATH = Path(__file__).parent.parent / "configs" / "identity.json"
_DEFAULTS_PATH = Path(__file__).parent.parent / "configs" / "system_defaults.json"

def get_identity() -> dict:
    """Loads the core UI/prompt identity configuration."""
    try:
        with open(_IDENTITY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"agent_name": "Servo", "user_name": "Kevin"}

def get_system_defaults() -> dict:
    """Loads project-wide constants and safety bounds."""
    try:
        with open(_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
