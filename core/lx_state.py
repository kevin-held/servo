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
# Design notes:
#   - ChromaDB init is try/wrapped so a missing chromadb install or a
#     corrupted index doesn't open the circuit. In degraded mode, commits
#     silently skip and query_success_vectors returns [] -- the loop still
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

# Phase D -- fixed embedding dimensionality for procedural_wins.
# Matches nomic-embed-text (the default OllamaClient.embed_model). The
# collection is append-only, so if a different embed model is ever
# introduced the existing rows and the new rows must share one dim:
# keep this constant in sync with the model in use, and migrate (drop +
# re-embed) rather than mix dims in place. chromadb raises on dim
# mismatch inside a single collection, so a regression here surfaces
# fast rather than silently corrupting NN queries later.
_EMBED_DIM = 768


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
        """Bootstrap the procedural_wins collection.

        Phase D pins the distance metric to cosine so the similarity floor
        in query_success_vectors is meaningful. For existing collections
        chromadb ignores the metadata arg (the metric is set at creation
        time and is immutable); a fresh collection is created with cosine,
        which is what we want for `nomic-embed-text` vectors. Default l2
        would still work for NN ranking but the similarity_floor literal
        (0.7) would be on a different, unbounded scale.
        """
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
        embedding: Optional[list] = None,
    ) -> bool:
        """Commit a Success Vector iff reward clears the threshold.

        Phase D: the caller (lx_Integrate) passes a real embedding computed
        via OllamaClient.embed(observation_signature). When `embedding` is
        None -- Ollama unavailable, embed() returned None, or the caller
        has no model -- we substitute a _EMBED_DIM zero vector so the row
        still lands and metadata-only queries keep working. The embedding
        is also dimension-checked so a caller passing a wrong-sized vector
        can't silently poison the collection. Wrong dim -> zero vector +
        metadata flag; the commit still succeeds so the reinforcement
        signal isn't lost.
        """
        if reward < self._COMMIT_THRESHOLD:
            return False
        if self._procedural_wins is None:
            return False
        try:
            # Normalize the embedding. Three failure modes collapse to the
            # same fallback (zero vector, flagged source) so downstream NN
            # queries can filter the real ones out via metadata.
            if embedding is None:
                vec = [0.0] * _EMBED_DIM
                embed_source = "zero"
            elif not isinstance(embedding, list) or len(embedding) != _EMBED_DIM:
                vec = [0.0] * _EMBED_DIM
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
                    "embed_dim": _EMBED_DIM,
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
        similarity_floor: float = 0.7,
    ) -> list:
        """Retrieve Success Vectors for a given observation.

        Phase D adds a semantic-search branch: when `obs_embedding` is a
        non-degenerate _EMBED_DIM vector, chromadb performs a kNN lookup
        using cosine distance and we return the top-`limit` rows whose
        similarity (= 1 - distance) clears `similarity_floor`. Rows with
        embed_source in {"zero","zero_dim_mismatch"} are dropped from the
        semantic branch -- their embedding is an all-zero vector and would
        otherwise rank artificially close to any non-zero query under
        cosine distance (or produce NaN distances, chromadb backend-
        dependent).

        When `obs_embedding` is None, degenerate, or wrong-sized, we fall
        back to the Phase C exact-match path on observation_signature,
        which keeps tests and Ollama-down deployments functional.

        The returned metadata dicts include a `_similarity` float in the
        semantic branch so lx_Reason._exploit can rank by a blended
        reward+similarity score if it chooses to. The exact-match branch
        omits that key (no similarity computed).
        """
        if self._procedural_wins is None:
            return []
        try:
            # Decide which branch. A zero (or near-zero) query vector must
            # fall through to exact-match -- cosine against zero is either
            # 0/0=NaN or undefined, and we would be searching on noise either
            # way.
            use_semantic = (
                isinstance(obs_embedding, list)
                and len(obs_embedding) == _EMBED_DIM
                and any(abs(float(x)) > 1e-12 for x in obs_embedding)
            )
            if use_semantic:
                res = self._procedural_wins.query(
                    query_embeddings=[obs_embedding],
                    n_results=max(int(limit), 1),
                )
                # chromadb.query returns lists-of-lists keyed by query index.
                # We sent exactly one query, so index [0] everywhere.
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
                    if similarity >= similarity_floor:
                        out.append({**m, "_similarity": similarity})
                return out

            # Fallback -- Phase C exact-match path.
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
