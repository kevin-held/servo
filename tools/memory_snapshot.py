import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME        = "memory_snapshot"
TOOL_DESCRIPTION = (
    "Capture a frozen snapshot of the agent's current working memory and goal list and persist it as a "
    "timestamped JSON file in the model's notes folder. Use this to checkpoint context at a meaningful moment "
    "so it can be compared ('diffed') against future states to track evolution."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "label": {
        "type": "string",
        "description": "Optional short label to embed in the snapshot filename and metadata (e.g. 'before_refactor'). Defaults to empty."
    }
}

_ROOT = Path(__file__).parent.parent.resolve()
# Sandbox check boundary
_SANDBOX = _ROOT


def _read_goals() -> dict:
    try:
        goal_path = _ROOT / "goals.json"
        if not goal_path.exists():
            return {}
        return json.loads(goal_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_working_memory() -> str:
    try:
        db_path = _ROOT / "state" / "state.db"
        if not db_path.exists():
            return ""
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.execute("SELECT value FROM state WHERE key = 'working_memory'")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else ""
    except Exception:
        return ""


def _find_notes_folder() -> Path:
    """
    Locate the model's notes folder. Falls back to a generic snapshots/ folder
    in the workspace root if the model-specific folder can't be determined.
    """
    try:
        import sqlite3 as _sq
        db_path = _ROOT / "state" / "state.db"
        if db_path.exists():
            conn = _sq.connect(str(db_path), check_same_thread=False)
            cur = conn.execute("SELECT value FROM state WHERE key = 'current_model'")
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                safe_name = row[0].replace(":", "_").replace(".", "_")
                folder = _ROOT / f"{safe_name}_notes"
                folder.mkdir(parents=True, exist_ok=True)
                return folder
    except Exception:
        pass
    fallback = _ROOT / "snapshots"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def execute(label: str = "") -> str:
    goals   = _read_goals()
    memory  = _read_working_memory()
    now_utc = datetime.now(timezone.utc)
    ts      = now_utc.strftime("%Y%m%d_%H%M%S")

    safe_label = label.strip().replace(" ", "_")[:40] if label.strip() else ""
    filename = f"snapshot_{ts}{'_' + safe_label if safe_label else ''}.json"

    notes_dir = _find_notes_folder()
    out_path  = notes_dir / filename

    # Sandbox check
    if not str(out_path.resolve()).lower().startswith(str(_SANDBOX).lower()):
        return f"Error: Resolved path '{out_path}' is outside the workspace sandbox."

    snapshot = {
        "snapshot_label": safe_label or None,
        "timestamp_utc":  now_utc.isoformat(),
        "goals":          goals,
        "working_memory": memory if memory else "",
    }

    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    return (
        f"Snapshot saved: {out_path}\n"
        f"Goals captured: {len(goals)}\n"
        f"Working memory: {len(memory)} chars"
    )
