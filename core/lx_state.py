# lx_state.py
#
# The Sovereign Ledger for the Servo Core — Phase C intelligence pass.
#
# Phase B shipped an in-memory stub. Phase C (UPGRADE_PLAN_2 §7 step 1)
# replaces that with:
#   - JSON mirror under state/lx_state_<profile>.json — byte-identical
#     to current_state after every apply_delta (Phase C acceptance gate).
#   - procedural_wins ChromaDB collection under state/chroma_procedural_wins_<profile>/
#     — Success Vectors committed by lx_Integrate when R >= 0.8.
#   - Read-only bridge to the legacy loop.py state.db for coexistence
#     (Kevin's Q3 sub-3: no-write policy on legacy assets).
#
# Design notes:
#   - ChromaDB init is try/wrapped so a missing chromadb install or a
#     corrupted index doesn't open the circuit. In degraded mode, commits
#     silently skip and query_success_vectors returns [] — the loop still
#     runs, just without the reinforcement signal.
#   - The JSON mirror is the primary durability layer. It is the source of
#     truth on restart; the in-memory dict is rebuilt from it at __init__.
#   - The legacy SQLite bridge opens in URI read-only mode so a shared
#     handle cannot be mutated through this path even accidentally.
#
# D-20260423.

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class lx_StateStore:
    """The Sovereign Ledger for the Servo Core."""

    _COMMIT_THRESHOLD = 0.8

    def __init__(
        self,
        profile: str = "lx_default",
        state_dir: Optional[str] = None,
        legacy_config_path: Optional[str] = None,
    ):
        self.profile = profile
        self._state_dir = Path(state_dir) if state_dir else (_PROJECT_ROOT / "state")
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = str(self._state_dir / f"lx_state_{profile}.json")
        self._legacy_config_path = (
            legacy_config_path or str(self._state_dir / "state.db")
        )
        self._legacy_conn_cache: Optional[sqlite3.Connection] = None
        self.current_state = self._load_mirror()
        self._chroma_client = None
        self._procedural_wins = None
        self._chroma_path = str(self._state_dir / f"chroma_procedural_wins_{profile}")
        self._init_chroma()

    def _load_mirror(self) -> dict:
        p = Path(self.profile_path)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {"current_step": "OBSERVE", "last_trace": None}

    def _init_chroma(self):
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=self._chroma_path)
            self._procedural_wins = self._chroma_client.get_or_create_collection(
                name="procedural_wins"
            )
        except Exception as e:
            self._chroma_client = None
            self._procedural_wins = None
            self.current_state.setdefault("_chroma_degraded", str(e))

    def get_active_profile(self) -> dict:
        return self.current_state

    def apply_delta(self, delta: dict):
        if not isinstance(delta, dict):
            return
        self.current_state.update(delta)
        self.sync_vector()

    def sync_vector(self):
        try:
            with open(self.profile_path, "w", encoding="utf-8") as f:
                json.dump(self.current_state, f, indent=2, default=str)
        except OSError:
            pass

    def commit_success_vector(
        self,
        observation_signature: str,
        tool_name: str,
        reward: float,
        outcome_snapshot: dict,
    ) -> bool:
        if reward < self._COMMIT_THRESHOLD:
            return False
        if self._procedural_wins is None:
            return False
        try:
            entry_id = hashlib.sha1(
                f"{observation_signature}|{tool_name}|{reward:.4f}".encode()
            ).hexdigest()[:16]
            self._procedural_wins.add(
                ids=[entry_id],
                documents=[json.dumps(outcome_snapshot, default=str)],
                embeddings=[[0.0, 0.0, 0.0, 0.0]],
                metadatas=[{
                    "observation_signature": observation_signature,
                    "tool_name": tool_name,
                    "reward": float(reward),
                    "timestamp": time.time(),
                }],
            )
            return True
        except Exception:
            return False

    def query_success_vectors(
        self,
        observation_signature: str,
        limit: int = 10,
    ) -> list:
        if self._procedural_wins is None:
            return []
        try:
            res = self._procedural_wins.get(
                where={"observation_signature": observation_signature},
                limit=limit,
            )
            metas = res.get("metadatas") or []
            return [m for m in metas if isinstance(m, dict)]
        except Exception:
            return []

    def count_success_vectors(self) -> int:
        if self._procedural_wins is None:
            return 0
        try:
            return int(self._procedural_wins.count())
        except Exception:
            return 0

    def get_legacy_config(
        self,
        key: str,
        default: Optional[str] = None,
    ) -> Optional[str]:
        p = Path(self._legacy_config_path)
        if not p.exists():
            return default
        try:
            uri = f"file:{p.as_posix()}?mode=ro"
            if self._legacy_conn_cache is None:
                self._legacy_conn_cache = sqlite3.connect(
                    uri, uri=True, check_same_thread=False
                )
            cur = self._legacy_conn_cache.execute(
                "SELECT value FROM state WHERE key = ?", (key,)
            )
            row = cur.fetchone()
            return row[0] if row else default
        except (sqlite3.Error, OSError):
            return default

    def reset(self):
        self.current_state = {"current_step": "OBSERVE", "last_trace": None}
        self.sync_vector()
