import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

TOOL_NAME        = "context_dump"
TOOL_DESCRIPTION = (
    "Aggregate the agent's full current operational context into a single structured JSON object. "
    "Returns: active goals, working memory summary, system health (hardware, recent errors, tool status), "
    "active workspace path, last modified file, and a UTC timestamp. "
    "Use this to get a complete snapshot of the current state before making decisions."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {}   # No arguments needed — always dumps everything

_ROOT = Path(__file__).parent.parent.resolve()


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


def _last_modified_file(directory: Path) -> str:
    """Return the relative path of the most recently modified file in the workspace."""
    try:
        latest = max(
            (f for f in directory.rglob("*") if f.is_file()
             and ".git" not in f.parts
             and "__pycache__" not in f.parts
             and "state.db" not in f.name),
            key=lambda f: f.stat().st_mtime,
            default=None
        )
        return str(latest.relative_to(directory)) if latest else "N/A"
    except Exception:
        return "N/A"


def _get_hardware_status() -> dict:
    """Get current RAM/VRAM usage."""
    try:
        from core.hardware import get_resource_status
        return get_resource_status()
    except Exception:
        return {"status": "Unknown", "ram_percent": -1, "vram_percent": -1}


def _get_error_summary() -> dict:
    """Get recent error counts from the Sentinel log."""
    try:
        from core.sentinel_logger import get_logger
        logger = get_logger()
        recent_errors = logger.get_recent_errors(limit=5)
        error_counts = logger.get_error_counts(minutes=60, bucket_minutes=60)
        total_errors_1h = sum(d["count"] for d in error_counts)
        return {
            "errors_last_hour": total_errors_1h,
            "recent_errors": [
                {"level": e.get("level"), "component": e.get("component"),
                 "message": e.get("message", "")[:120], "timestamp": e.get("timestamp_utc", "")[:19]}
                for e in recent_errors
            ],
        }
    except Exception:
        return {"errors_last_hour": -1, "recent_errors": []}


def _get_loop_telemetry() -> dict:
    """
    Pull truncation / auto-continue / throttle counters from the running CoreLoop.
    Returns empty dict if the loop isn't reachable (e.g. called outside the GUI).
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return {}
        loop = None
        for widget in app.topLevelWidgets():
            if hasattr(widget, "loop"):
                loop = widget.loop
                break
        if loop is None:
            return {}
        return {
            "truncations_total":            getattr(loop, "truncations_total", 0),
            "followup_truncations_total":   getattr(loop, "followup_truncations_total", 0),
            "auto_continues_total":         getattr(loop, "auto_continues_total", 0),
            "auto_continue_give_ups_total": getattr(loop, "auto_continue_give_ups_total", 0),
            "hardware_throttle_total":      getattr(loop, "hardware_throttle_total", 0),
            "user_interrupts_total":        getattr(loop, "user_interrupts_total", 0),
            "history_compressions_total":   getattr(loop, "history_compressions_total", 0),
            "max_auto_continues":           getattr(loop, "max_auto_continues", 2),
            "conversation_history":         getattr(loop, "conversation_history", 0),
            "default_conversation_history": getattr(loop, "default_conversation_history", 0),
            "chain_limit":                  getattr(loop, "chain_limit", 0),
            "autonomous_loop_limit":        getattr(loop, "autonomous_loop_limit", 0),
            "grace_cycle_count":            getattr(loop, "_grace_cycle_count", 0),
            "max_consecutive_grace":        getattr(loop, "max_consecutive_grace", 0),
            "autonomous_cycle_count":       getattr(loop, "_autonomous_cycle_count", 0),
        }
    except Exception:
        return {}


def _get_tool_health() -> dict:
    """Scan tool registry to report loaded, disabled, and failed tools."""
    try:
        tools_dir = _ROOT / "tools"
        tool_files = [f.stem for f in tools_dir.glob("*.py") if not f.name.startswith("_")]

        # Try to get live registry data
        from core.tool_registry import ToolRegistry
        registry = ToolRegistry(str(tools_dir))
        loaded = registry.get_tool_descriptions()

        loaded_names = {t["name"] for t in loaded}
        enabled = [t["name"] for t in loaded if t.get("enabled", True)]
        disabled = [t["name"] for t in loaded if not t.get("enabled", True)]
        failed = [f for f in tool_files if f not in loaded_names]

        return {
            "total_files": len(tool_files),
            "loaded": len(loaded),
            "enabled": enabled,
            "disabled": disabled if disabled else [],
            "failed_to_load": failed if failed else [],
        }
    except Exception as e:
        return {"error": str(e)}


def execute() -> str:
    goals_raw = _read_goals()

    # Format goals the same way goal_manager:list does (human-friendly but still JSON-serializable)
    goals_summary = {}
    now = time.time()
    for name, meta in goals_raw.items():
        entry = {"type": meta.get("type"), "description": meta.get("description")}
        if meta.get("type") == "continuous":
            sched = meta.get("schedule_minutes", 60)
            last_run = meta.get("last_run", 0)
            remaining = sched * 60 - (now - last_run)
            entry["schedule_minutes"] = sched
            entry["status"] = "DUE NOW" if remaining <= 0 else f"snoozing ({max(0, int(remaining/60))} min left)"
        elif meta.get("type") == "finite":
            expires_at = meta.get("expires_at")
            if expires_at:
                mins_left = max(0, int((expires_at - now) / 60))
                entry["auto_expires_in_minutes"] = mins_left
        goals_summary[name] = entry

    mem = _read_working_memory()
    mem_summary = mem[:500] + ("... [truncated]" if len(mem) > 500 else "")

    hw = _get_hardware_status()
    errors = _get_error_summary()
    tools = _get_tool_health()
    loop_telemetry = _get_loop_telemetry()

    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "workspace": str(_ROOT),
        "last_modified_file": _last_modified_file(_ROOT),
        "goals": goals_summary,
        "working_memory_summary": mem_summary if mem_summary else "(empty)",
        "system_health": {
            "hardware": {
                "status": hw.get("status", "Unknown"),
                "ram_percent": hw.get("ram_percent", -1),
                "vram_percent": hw.get("vram_percent", -1),
            },
            "errors": errors,
            "tools": tools,
            "loop_telemetry": loop_telemetry if loop_telemetry else "(unavailable)",
        },
    }

    return json.dumps(payload, indent=2)

