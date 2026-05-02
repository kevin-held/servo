# lx_state.py
#
# The Sovereign Ledger for the Servo Core -- Phase C intelligence pass.
#
# Phase B shipped an in-memory stub. Phase C (UPGRADE_PLAN_2 sec 7 step 1)
# replaces that with:
#   - JSON mirror under state/lx_state_<profile>.json -- byte-identical
#     to current_state after every apply_delta (Phase C acceptance gate).
#   - procedural_wins ChromaDB collection under state/chroma_procedural_wins_<profile>/
#     -- Success Vectors committed by lx_Integrate when R >= 0.8.
#   - Read-only bridge to the legacy loop.py state.db for coexistence
#     (Kevin's Q3 sub-3: no-write policy on legacy assets).
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

_EMBED_DIM = 768


class lx_StateStore:
    """The Sovereign Ledger for the Servo Core."""

    _COMMIT_THRESHOLD = 0.8

    def __init__(
        self,
        profile: str = "lx_default",
        state_dir: Optional[str] = None,
        legacy_config_path: Optional[str] = None,
        config=None,
    ):
        self.profile = profile
        self._state_dir = Path(state_dir) if state_dir else (_PROJECT_ROOT / "state")
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = str(self._state_dir / f"lx_state_{profile}.json")
        self._legacy_config_path = (
            legacy_config_path or str(self._state_dir / "state.db")
        )
        self._legacy_conn_cache: Optional[sqlite3.Connection] = None
        self._config = config
        self.current_state = self._load_mirror()
        self._chroma_client = None
        self._procedural_wins = None
        self._chroma_path = str(self._state_dir / f"chroma_procedural_wins_{profile}")
        self._env_snapshots = None
        self._chroma_env_path = str(self._state_dir / f"chroma_env_snapshots_{profile}")
        self._init_chroma()

    def _cfg_get(self, key: str, fallback):
        cfg = self._config
        if cfg is None:
            return fallback
        try:
            val = cfg.get(key)
        except Exception:
            return fallback
        return val if val is not None else fallback

    def _load_mirror(self) -> dict:
        p = Path(self.profile_path)
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data.pop("halt", None)
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {"current_step": "OBSERVE", "last_trace": None}

    def _init_chroma(self):
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=self._chroma_path)
            self._procedural_wins = self._chroma_client.get_or_create_collection(
                name="procedural_wins",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            self._chroma_client = None
            self._procedural_wins = None
            self.current_state.setdefault("_chroma_degraded", str(e))

        try:
            import chromadb
            self._env_chroma_client = chromadb.PersistentClient(path=self._chroma_env_path)
            self._env_snapshots = self._env_chroma_client.get_or_create_collection(
                name="env_snapshots",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            self._env_chroma_client = None
            self._env_snapshots = None
            self.current_state.setdefault("_env_chroma_degraded", str(e))

    def get_active_profile(self) -> dict:
        return self.current_state

    # ------------------------------------------------------------------
    # Key-value helpers — compatible with legacy StateStore.set / .get
    # that history_compressor and tool_result_compressor rely on.
    # ------------------------------------------------------------------

    def set(self, key: str, value: str) -> None:
        self.current_state[key] = value
        self.sync_vector()

    def get(self, key: str, default=None):
        return self.current_state.get(key, default)

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
        embedding: Optional[list] = None,
    ) -> bool:
        commit_threshold = self._cfg_get("commit_threshold", self._COMMIT_THRESHOLD)
        embed_dim = int(self._cfg_get("embed_dim", _EMBED_DIM))
        if reward < commit_threshold:
            return False
        if self._procedural_wins is None:
            return False
        try:
            if embedding is None:
                vec = [0.0] * embed_dim
                embed_source = "zero"
            elif not isinstance(embedding, list) or len(embedding) != embed_dim:
                vec = [0.0] * embed_dim
                embed_source = "zero_dim_mismatch"
            else:
                vec = [float(x) for x in embedding]
                embed_source = "ollama"

            entry_id = hashlib.sha1(
                f"{observation_signature}|{tool_name}|{reward:.4f}".encode()
            ).hexdigest()[:16]
            self._procedural_wins.add(
                ids=[entry_id],
                documents=[json.dumps(outcome_snapshot, default=str)],
                embeddings=[vec],
                metadatas=[{
                    "observation_signature": observation_signature,
                    "tool_name": tool_name,
                    "reward": float(reward),
                    "timestamp": time.time(),
                    "embed_source": embed_source,
                    "embed_dim": embed_dim,
                }],
            )
            return True
        except Exception:
            return False

    def query_success_vectors(
        self,
        observation_signature: str,
        obs_embedding: Optional[list] = None,
        limit: int = 10,
        similarity_floor: Optional[float] = None,
    ) -> list:
        if self._procedural_wins is None:
            return []
        try:
            embed_dim = int(self._cfg_get("embed_dim", _EMBED_DIM))
            floor = (
                similarity_floor
                if similarity_floor is not None
                else self._cfg_get("nn_similarity_floor", 0.7)
            )
            use_semantic = (
                isinstance(obs_embedding, list)
                and len(obs_embedding) == embed_dim
                and any(abs(float(x)) > 1e-12 for x in obs_embedding)
            )
            if use_semantic:
                res = self._procedural_wins.query(
                    query_embeddings=[obs_embedding],
                    n_results=max(int(limit), 1),
                )
                metas_grid = res.get("metadatas") or [[]]
                dist_grid = res.get("distances") or [[]]
                metas = metas_grid[0] if metas_grid else []
                dists = dist_grid[0] if dist_grid else []
                out: list = []
                for m, d in zip(metas, dists):
                    if not isinstance(m, dict):
                        continue
                    if m.get("embed_source") in ("zero", "zero_dim_mismatch"):
                        continue
                    try:
                        distance = float(d)
                    except (TypeError, ValueError):
                        continue
                    similarity = 1.0 - distance
                    if similarity >= floor:
                        out.append({**m, "_similarity": similarity})
                return out

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

    # ------------------------------------------------------------------
    # Phase G (UPGRADE_PLAN_6 sec 3a-3b) -- env_snapshots commit/query.
    # ------------------------------------------------------------------

    def commit_env_snapshot(
        self,
        env_audit: dict,
        embedding: Optional[list],
        tool_name: str,
        reward: float,
    ) -> bool:
        commit_threshold = self._cfg_get("commit_threshold", self._COMMIT_THRESHOLD)
        embed_dim = int(self._cfg_get("embed_dim", _EMBED_DIM))
        if reward < commit_threshold:
            return False
        if self._env_snapshots is None:
            return False
        try:
            if embedding is None:
                vec = [0.0] * embed_dim
                embed_source = "zero"
            elif not isinstance(embedding, list) or len(embedding) != embed_dim:
                vec = [0.0] * embed_dim
                embed_source = "zero_dim_mismatch"
            else:
                vec = [float(x) for x in embedding]
                embed_source = "ollama"

            audit_blob = json.dumps(env_audit, default=str, sort_keys=True)
            entry_id = hashlib.sha1(
                f"{audit_blob}|{tool_name}|{reward:.4f}".encode()
            ).hexdigest()[:16]
            self._env_snapshots.add(
                ids=[entry_id],
                documents=[audit_blob],
                embeddings=[vec],
                metadatas=[{
                    "tool_name": tool_name,
                    "reward": float(reward),
                    "timestamp": time.time(),
                    "embed_source": embed_source,
                    "embed_dim": embed_dim,
                }],
            )
            return True
        except Exception:
            return False

    def query_env_snapshots(
        self,
        obs_embedding: Optional[list] = None,
        limit: int = 5,
        similarity_floor: Optional[float] = None,
    ) -> list:
        if self._env_snapshots is None:
            return []
        try:
            embed_dim = int(self._cfg_get("embed_dim", _EMBED_DIM))
            floor = (
                similarity_floor
                if similarity_floor is not None
                else self._cfg_get("env_snapshot_similarity_floor", 0.6)
            )
            use_semantic = (
                isinstance(obs_embedding, list)
                and len(obs_embedding) == embed_dim
                and any(abs(float(x)) > 1e-12 for x in obs_embedding)
            )
            if not use_semantic:
                return []
            res = self._env_snapshots.query(
                query_embeddings=[obs_embedding],
                n_results=max(int(limit), 1),
            )
            metas_grid = res.get("metadatas") or [[]]
            dist_grid = res.get("distances") or [[]]
            metas = metas_grid[0] if metas_grid else []
            dists = dist_grid[0] if dist_grid else []
            out: list = []
            for m, d in zip(metas, dists):
                if not isinstance(m, dict):
                    continue
                if m.get("embed_source") in ("zero", "zero_dim_mismatch"):
                    continue
                try:
                    distance = float(d)
                except (TypeError, ValueError):
                    continue
                similarity = 1.0 - distance
                if similarity >= floor:
                    out.append({**m, "_similarity": similarity})
            return out
        except Exception:
            return []

    def count_env_snapshots(self) -> int:
        if self._env_snapshots is None:
            return 0
        try:
            return int(self._env_snapshots.count())
        except Exception:
            return 0

    def get_legacy_config(
        self,
        key: str,
        default=None,
    ):
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

    # ------------------------------------------------------------------
    # Phase F (UPGRADE_PLAN_5 sec 6) -- conversation persistence.
    # ------------------------------------------------------------------

    def _turns_db_path(self) -> str:
        return str(self._state_dir / f"lx_turns_{self.profile}.db")

    def _ensure_turns_schema(self, conn) -> None:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS turns ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " perception_text TEXT NOT NULL,"
            " observation_kind TEXT NOT NULL,"
            " response_text TEXT NOT NULL,"
            " tool_name TEXT NOT NULL,"
            " status TEXT NOT NULL,"
            " timestamp REAL NOT NULL"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_timestamp "
            "ON turns (timestamp)"
        )
        # Phase G (UPGRADE_PLAN_6 sec 2.b) -- conversation summary table
        conn.execute(
            "CREATE TABLE IF NOT EXISTS conversation_summary ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " summary TEXT NOT NULL,"
            " covers_from_id INTEGER NOT NULL,"
            " covers_to_id INTEGER NOT NULL,"
            " model_used TEXT NOT NULL,"
            " created_at REAL NOT NULL"
            ")"
        )

    def record_turn(
        self,
        perception_text: str = "",
        observation_kind: str = "",
        response_text: str = "",
        tool_name: str = "",
        status: str = "",
        timestamp: Optional[float] = None,
    ) -> bool:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return False
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            self._ensure_turns_schema(conn)
            ts = float(timestamp) if timestamp is not None else time.time()
            conn.execute(
                "INSERT INTO turns "
                "(perception_text, observation_kind, response_text, "
                " tool_name, status, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(perception_text or ""),
                    str(observation_kind or ""),
                    str(response_text or ""),
                    str(tool_name or ""),
                    str(status or ""),
                    ts,
                ),
            )
            conn.commit()
            return True
        except sqlite3.Error:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def query_turns(self, limit: int = 50) -> list:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return []
        try:
            self._ensure_turns_schema(conn)
            cur = conn.execute(
                "SELECT id, perception_text, observation_kind, "
                "response_text, tool_name, status, timestamp "
                "FROM turns ORDER BY id DESC LIMIT ?",
                (max(int(limit), 1),),
            )
            rows = cur.fetchall()
        except sqlite3.Error:
            rows = []
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return [
            {
                "id": r[0],
                "perception_text": r[1],
                "observation_kind": r[2],
                "response_text": r[3],
                "tool_name": r[4],
                "status": r[5],
                "timestamp": r[6],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Phase G (UPGRADE_PLAN_6 sec 2.b) -- conversation history compression.
    # ------------------------------------------------------------------

    def get_latest_conversation_summary(self) -> dict | None:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return None
        try:
            self._ensure_turns_schema(conn)
            cur = conn.execute(
                "SELECT id, summary, covers_from_id, covers_to_id, model_used, created_at "
                "FROM conversation_summary ORDER BY id DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id":             row[0],
                "summary":        row[1],
                "covers_from_id": row[2],
                "covers_to_id":   row[3],
                "model_used":     row[4],
                "created_at":     row[5],
            }
        except sqlite3.Error:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def save_conversation_summary(
        self,
        summary: str,
        covers_from_id: int,
        covers_to_id: int,
        model_used: str,
    ) -> int:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return 0
        try:
            self._ensure_turns_schema(conn)
            cur = conn.execute(
                "INSERT INTO conversation_summary "
                "(summary, covers_from_id, covers_to_id, model_used, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (summary, covers_from_id, covers_to_id, model_used, time.time()),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.Error:
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def count_conversation_turns_since(self, conversation_id: int) -> int:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return 0
        try:
            self._ensure_turns_schema(conn)
            cur = conn.execute(
                "SELECT COUNT(*) FROM turns WHERE id > ?", (conversation_id,)
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_conversation_turns_range(self, from_id: int, to_id: int) -> list:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return []
        try:
            self._ensure_turns_schema(conn)
            cur = conn.execute(
                "SELECT id, perception_text, response_text FROM turns "
                "WHERE id >= ? AND id <= ? ORDER BY id ASC",
                (from_id, to_id),
            )
            # Adapt the turns format to what the compressor expects 
            # The compressor expects [{"role":..., "content":...}, ...]
            rows = []
            for r in cur.fetchall():
                # Tool outputs and user inputs go in 'user' role for the compressor
                if r[1]:
                    rows.append({"id": r[0], "role": "user", "content": r[1]})
                if r[2]:
                    rows.append({"id": r[0], "role": "assistant", "content": r[2]})
            return rows
        except sqlite3.Error:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_newest_conversation_id(self) -> int | None:
        try:
            conn = sqlite3.connect(self._turns_db_path(), check_same_thread=False)
        except sqlite3.Error:
            return None
        try:
            self._ensure_turns_schema(conn)
            cur = conn.execute("SELECT MAX(id) FROM turns")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else None
        except sqlite3.Error:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass
