"""
log_query — Agent tool for programmatic inspection of the structured system log.

Allows the agent to filter and search the JSONL log by level, time range,
search term, and to tail recent entries.
"""

import json
import os
from pathlib import Path

TOOL_NAME        = "log_query"
TOOL_DESCRIPTION = (
    "Query the structured system log. Filter by log level, search term, time range, "
    "or tail the most recent entries. Returns a JSON array of matching log entries."
)
TOOL_ENABLED     = True
TOOL_SCHEMA      = {
    "level":       {"type": "string", "enum": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                    "description": "(Optional) Filter by log level."},
    "search_term": {"type": "string", "description": "(Optional) Substring to match in message or context."},
    "start_time":  {"type": "string", "description": "(Optional) ISO 8601 lower bound for timestamp filter."},
    "end_time":    {"type": "string", "description": "(Optional) ISO 8601 upper bound for timestamp filter."},
    "limit":       {"type": "integer", "description": "(Optional) Max entries to return. Default 50."},
    "tail":        {"type": "boolean", "description": "(Optional) If true, return the N most recent matching entries."},
}

# Resolve logger import relative to project root
import sys
_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


def execute(
    level: str = "",
    search_term: str = "",
    start_time: str = "",
    end_time: str = "",
    limit: int = 50,
    tail: bool = True,
) -> str:
    try:
        from core.sentinel_logger import get_logger
        logger = get_logger()

        results = logger.query(
            level=level if level else None,
            search_term=search_term if search_term else None,
            start_time=start_time if start_time else None,
            end_time=end_time if end_time else None,
            limit=int(limit) if limit else 50,
            tail=bool(tail),
        )

        if not results:
            return "No log entries match the given filters."

        return json.dumps(results, indent=2, ensure_ascii=False)

    except Exception as e:
        return f"Error querying logs: {e}"
