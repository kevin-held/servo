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
TOOL_IS_SYSTEM   = True # Core State diagnostic
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


def _open_state_db(conn_factory=None):
    """Phase E (UPGRADE_PLAN_4 sec 4) -- centralize the state.db open so
    both helpers share the same injection point. When `conn_factory` is
    supplied by the Cognate surface, we use it; otherwise fall through
    to the Phase D literal (state/state.db relative to project root).
    Returns None if the legacy DB is missing (so read helpers can degrade
    gracefully), or the live connection otherwise.
    """
    if conn_factory is not None:
        try:
            return conn_factory()
        except Exception:
            return None
    db_path = _ROOT / "state" / "state.db"
    if not db_path.exists():
        return None
    return sqlite3.connect(str(db_path), check_same_thread=False)


def _read_working_memory(conn_factory=None) -> str:
    try:
        conn = _open_state_db(conn_factory)
        if conn is None:
            return ""
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.execute("SELECT value FROM state WHERE key = 'working_memory'")
            row = cur.fetchone()
        finally:
            conn.close()
        return row[0] if row else ""
    except Exception:
        return ""


def _find_notes_folder(conn_factory=None) -> Path:
    """
    Locate the model's scratch folder under workspace/. Falls back to a generic
    snapshots/ folder at the workspace root if the model can't be determined.
    """
    try:
        conn = _open_state_db(conn_factory)
        if conn is not None:
            try:
                cur = conn.execute("SELECT value FROM state WHERE key = 'current_model'")
                row = cur.fetchone()
            finally:
                conn.close()
            if row and row[0]:
                safe_name = row[0].replace(":", "_").replace(".", "_")
                folder = _ROOT / "workspace" / safe_name
                folder.mkdir(parents=True, exist_ok=True)
                return folder
    except Exception:
        pass
    fallback = _ROOT / "workspace" / "_snapshots"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def execute(label: str = "", *, conn_factory=None, tool_context=None) -> str:
    # Phase E (UPGRADE_PLAN_4 sec 4) -- conn_factory is forwarded to both
    # state.db-touching helpers so the Cognate surface can route this
    # tool's reads without the loop shim's sqlite3.connect interception.
    # When absent (legacy boot), helpers fall through to state/state.db.
    #
    # Phase F (UPGRADE_PLAN_5 sec 5) -- tool_context kwarg supersedes the
    # bare conn_factory pattern with a uniform ToolContext object that
    # carries state/config/telemetry/conn_factory/ollama. Resolution
    # order: explicit conn_factory wins (back-compat with Phase E
    # callers), then tool_context.conn_factory, then the legacy literal.
    # Duck-typed read via getattr so this file stays independent of
    # core/tool_context.py imports.
    if conn_factory is None and tool_context is not None:
        ctx_factory = getattr(tool_context, "conn_factory", None)
        if callable(ctx_factory):
            conn_factory = ctx_factory
    goals   = _read_goals()
    memory  = _read_working_memory(conn_factory=conn_factory)
    now_utc = datetime.now(timezone.utc)
    ts      = now_utc.strftime("%Y%m%d_%H%M%S")

    safe_label = label.strip().replace(" ", "_")[:40] if label.strip() else ""
    filename = f"snapshot_{ts}{'_' + safe_label if safe_label else ''}.json"

    notes_dir = _find_notes_folder(conn_factory=conn_factory)
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
