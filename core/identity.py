import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "configs" / "identity.json"

def get_identity() -> dict:
    """Loads the core UI/prompt identity configuration."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"agent_name": "Servo", "user_name": "Kevin"}
