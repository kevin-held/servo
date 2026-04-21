"""
Sentinel Logger — The single source of truth for all system events.

Writes structured JSON log entries to logs/sentinel.jsonl (one JSON object per line).
Handles size-based rotation (5MB threshold), gzip archival, and 30-day retention.
Thread-safe via threading.Lock.
"""

import gzip
import json
import os
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.identity import get_system_defaults

# ── Constants ────────────────────────────────────────

_LOG_DIR_ENV = os.environ.get("SENTINEL_LOG_DIR")
if _LOG_DIR_ENV:
    _LOG_DIR = Path(_LOG_DIR_ENV)
else:
    _LOG_DIR = Path(__file__).parent.parent / "logs"

_DEFAULTS = get_system_defaults().get("logs", {})
_ARCHIVE_DIR     = _LOG_DIR / "archive"
_ACTIVE_LOG      = _LOG_DIR / "sentinel.jsonl"
_ROTATION_BYTES  = _DEFAULTS.get("ROTATION_BYTES", 5 * 1024 * 1024)
_RETENTION_DAYS  = _DEFAULTS.get("RETENTION_DAYS", 30)
_VALID_LEVELS    = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class SentinelLogger:
    """
    Centralized, structured, append-only logger.

    Usage:
        logger = SentinelLogger()
        logger.log("INFO", "core_loop", "Cycle started", {"loop_index": 1})
    """

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._write_lock = threading.Lock()

        # Ensure directories exist
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        # Purge stale archives on startup
        self._purge_old_archives()

        # Open (or create) the active log in append mode
        self._file = open(_ACTIVE_LOG, "a", encoding="utf-8")

    # ── Public API ────────────────────────────────────

    def log(self, level: str, component: str, message: str, context: dict = None):
        """
        Write a single structured log entry.
        """
        if os.environ.get("SENTINEL_SILENT") == "True":
            return

        level = level.upper()
        if level not in _VALID_LEVELS:
            level = "INFO"

        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "level":         level,
            "component":     component,
            "message":       message,
        }
        if context:
            entry["context"] = context

        line = json.dumps(entry, ensure_ascii=False) + "\n"

        with self._write_lock:
            self._file.write(line)
            self._file.flush()
            os.fsync(self._file.fileno())

            # Check rotation after each write
            try:
                if _ACTIVE_LOG.stat().st_size >= _ROTATION_BYTES:
                    self._rotate()
            except OSError:
                pass

    def query(
        self,
        level: str = None,
        search_term: str = None,
        start_time: str = None,
        end_time: str = None,
        limit: int = 50,
        tail: bool = False,
    ) -> list:
        """
        Query the active log file with optional filters.

        Returns a list of log entry dicts matching the criteria.
        """
        if not _ACTIVE_LOG.exists():
            return []

        # Parse time bounds once
        t_start = self._parse_iso(start_time) if start_time else None
        t_end   = self._parse_iso(end_time)   if end_time   else None
        level   = level.upper() if level else None

        if tail:
            return self._query_tail(level, search_term, t_start, t_end, limit)
        else:
            return self._query_forward(level, search_term, t_start, t_end, limit)

    def get_error_counts(self, minutes: int = 60, bucket_minutes: int = 5) -> list:
        """
        Return error+critical counts bucketed by time for the sparkline chart.

        Returns a list of dicts: [{"bucket": "HH:MM", "count": N}, ...]
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=minutes)
        num_buckets = minutes // bucket_minutes

        buckets = [0] * num_buckets
        bucket_labels = []
        for i in range(num_buckets):
            t = cutoff + timedelta(minutes=i * bucket_minutes)
            bucket_labels.append(t.strftime("%H:%M"))

        if not _ACTIVE_LOG.exists():
            return [{"bucket": bucket_labels[i], "count": 0} for i in range(num_buckets)]

        try:
            with open(_ACTIVE_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if entry.get("level") not in ("ERROR", "CRITICAL"):
                        continue

                    ts = self._parse_iso(entry.get("timestamp_utc", ""))
                    if ts is None or ts < cutoff:
                        continue

                    # Determine which bucket
                    delta_min = (ts - cutoff).total_seconds() / 60
                    idx = min(int(delta_min // bucket_minutes), num_buckets - 1)
                    buckets[idx] += 1
        except Exception:
            pass

        return [{"bucket": bucket_labels[i], "count": buckets[i]} for i in range(num_buckets)]

    def get_recent_errors(self, limit: int = 10) -> list:
        """Return the most recent ERROR/CRITICAL entries."""
        if not _ACTIVE_LOG.exists():
            return []

        errors = deque(maxlen=limit)
        try:
            with open(_ACTIVE_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("level") in ("ERROR", "CRITICAL"):
                        errors.append(entry)
        except Exception:
            pass

        return list(errors)

    def shutdown(self):
        """Flush and close the log file."""
        with self._write_lock:
            if self._file and not self._file.closed:
                self._file.flush()
                self._file.close()

    def clear(self):
        """Thread-safely truncate the log file and restart logging."""
        with self._write_lock:
            # 1. Close current handle
            if self._file and not self._file.closed:
                self._file.flush()
                self._file.close()
            
            # 2. Truncate file to zero
            with open(_ACTIVE_LOG, "w", encoding="utf-8") as f:
                f.truncate(0)
            
            # 3. Re-open in append mode
            self._file = open(_ACTIVE_LOG, "a", encoding="utf-8")
            
            # 4. Log the reset event
            entry = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "level":         "INFO",
                "component":     "sentinel_logger",
                "message":       "Log cleared by session reset",
            }
            self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._file.flush()

    # ── Internal ──────────────────────────────────────

    def _rotate(self):
        """Archive the active log and start a new one. Must be called under _write_lock."""
        self._file.flush()
        self._file.close()

        # Generate archive name
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = _ARCHIVE_DIR / f"log_{stamp}.json.gz"

        # Compress into gzip archive
        try:
            with open(_ACTIVE_LOG, "rb") as f_in:
                with gzip.open(archive_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        except Exception:
            pass

        # Truncate and reopen
        self._file = open(_ACTIVE_LOG, "w", encoding="utf-8")

        # Write rotation notice directly (avoid deadlock — we already hold _write_lock)
        entry = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "level": "INFO",
            "component": "sentinel_logger",
            "message": "Log rotated",
            "context": {"archived_to": str(archive_path)},
        }
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

        # Purge old archives after rotation
        self._purge_old_archives()

    def _purge_old_archives(self):
        """Delete archived logs older than _RETENTION_DAYS."""
        cutoff = time.time() - (_RETENTION_DAYS * 86400)
        try:
            for gz_file in _ARCHIVE_DIR.glob("log_*.json.gz"):
                if gz_file.stat().st_mtime < cutoff:
                    gz_file.unlink()
        except Exception:
            pass

    def _query_forward(self, level, search_term, t_start, t_end, limit) -> list:
        results = []
        try:
            with open(_ACTIVE_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    if len(results) >= limit:
                        break
                    entry = self._match_entry(line, level, search_term, t_start, t_end)
                    if entry:
                        results.append(entry)
        except Exception:
            pass
        return results

    def _query_tail(self, level, search_term, t_start, t_end, limit) -> list:
        results = deque(maxlen=limit)
        try:
            with open(_ACTIVE_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    entry = self._match_entry(line, level, search_term, t_start, t_end)
                    if entry:
                        results.append(entry)
        except Exception:
            pass
        return list(results)

    def _match_entry(self, line: str, level, search_term, t_start, t_end) -> dict | None:
        line = line.strip()
        if not line:
            return None
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return None

        if level and entry.get("level") != level:
            return None

        if search_term:
            search_lower = search_term.lower()
            msg_match = search_lower in entry.get("message", "").lower()
            ctx_match = search_lower in json.dumps(entry.get("context", {})).lower()
            if not (msg_match or ctx_match):
                return None

        if t_start or t_end:
            ts = self._parse_iso(entry.get("timestamp_utc", ""))
            if ts is None:
                return None
            if t_start and ts < t_start:
                return None
            if t_end and ts > t_end:
                return None

        return entry

    @staticmethod
    def _parse_iso(iso_str) -> datetime | None:
        if not iso_str:
            return None
        if isinstance(iso_str, datetime):
            return iso_str
        try:
            return datetime.fromisoformat(iso_str)
        except (ValueError, TypeError):
            return None


# ── Module-level convenience ─────────────────────────

_logger = None

def get_logger() -> SentinelLogger:
    """Get the singleton SentinelLogger instance."""
    global _logger
    if _logger is None:
        _logger = SentinelLogger()
    return _logger
