import sqlite3
import time
from pathlib import Path
import chromadb
from core.sentinel_logger import get_logger


class StateStore:
    """
    Persistent state. Everything the loop needs to survive across sessions.
    Six tables: conversation, conversation_summary, memory, trace, state
    (key/value), tasks.
    Plus: chroma vector database for episodic memory.
    """

    def __init__(self, db_path: str = "state/state.db", chroma_path: str = "state/chroma"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

        # Initialize Vector Database
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.memory_collection = self.chroma_client.get_or_create_collection(name="episodic_memory")

        # Perform a system backup before returning control to the loop
        self._backup_state(db_path)

    def _backup_state(self, db_path: str):
        """Silently duplicates the SQLite database to a .bak extension."""
        import os
        import shutil
        if os.path.exists(db_path):
            try:
                shutil.copy2(db_path, f"{db_path}.bak")
            except Exception:
                pass

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversation (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                role      TEXT    NOT NULL,
                content   TEXT    NOT NULL,
                timestamp REAL    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                content   TEXT    NOT NULL,
                timestamp REAL    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trace (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                step      TEXT    NOT NULL,
                message   TEXT    NOT NULL,
                timestamp REAL    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            -- Phase 2: INTEGRATE-time auto-compression of conversation history.
            -- Only the newest row matters to the runtime ([PRIOR CONTEXT] block
            -- in system prompt + message-list filter in _build_messages).
            -- Prior rows are retained as an audit trail.
            -- covers_from_id / covers_to_id reference conversation.id values;
            -- they are the inclusive range of raw turns this summary replaces
            -- in the model's view. See decisions.md D-20260419-01.
            CREATE TABLE IF NOT EXISTS conversation_summary (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                summary        TEXT    NOT NULL,
                covers_from_id INTEGER NOT NULL,
                covers_to_id   INTEGER NOT NULL,
                model_used     TEXT    NOT NULL,
                created_at     REAL    NOT NULL
            );
            -- v0.8.0: Task ledger. A persistent, ordered plan the model
            -- registers up-front via the `task` tool so a long chain of
            -- tool calls doesn't have to be re-derived from conversation
            -- history every turn. The loop renders pending tasks into an
            -- [ACTIVE TASKS] block in the system prompt (cursor on the
            -- first pending row) and uses pending-count to decide whether
            -- to nudge a stalled chain. See decisions.md D-20260419-12.
            -- Grain norm: one task per semantic milestone, not per tool
            -- call (a 3-block paginated read is one task, not three).
            CREATE TABLE IF NOT EXISTS tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                description  TEXT    NOT NULL,
                status       TEXT    NOT NULL DEFAULT 'pending',
                created_at   REAL    NOT NULL,
                completed_at REAL
            );
        """)
        self.conn.commit()

        # Safely attempt to upgrade schema for legacy databases
        try:
            self.conn.execute("ALTER TABLE conversation ADD COLUMN image TEXT")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass # Column already exists

    # ── Conversation ──────────────────────────────

    def add_conversation_turn(self, role: str, content: str, image: str = None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO conversation (role, content, image, timestamp) VALUES (?, ?, ?, ?)",
                (role, content, image, time.time()),
            )

    def get_conversation_history(self, limit: int = 10) -> list:
        # Returns the `limit` most-recent turns, oldest-first. The `id` field
        # was added in Phase 2 (D-20260419-01) so callers can filter turns
        # already covered by a conversation_summary. Existing callers that
        # only read role/content/image are unaffected.
        cur = self.conn.execute(
            "SELECT id, role, content, image FROM conversation ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [
            {"id": r[0], "role": r[1], "content": r[2], "image": r[3]}
            for r in reversed(cur.fetchall())
        ]

    # ── Conversation Summary (Phase 2 auto-compression) ────

    def get_latest_conversation_summary(self) -> dict | None:
        """Return the newest summary row, or None if none exists.

        This is the row the runtime actually reads when building the
        [PRIOR CONTEXT] block and when filtering the message list. Prior
        rows in the table are kept as an audit trail but never served.
        """
        cur = self.conn.execute(
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

    def save_conversation_summary(
        self,
        summary: str,
        covers_from_id: int,
        covers_to_id: int,
        model_used: str,
    ) -> int:
        """Append a new summary row. Returns its id.

        The compressor writes a new row on each successful compression
        rather than updating an existing one. `get_latest_conversation_summary`
        only serves the newest, so behavior is rollup-in-place; the prior
        rows are retained for diagnostics (e.g. 'when did the summary
        containing <phrase> get written?').
        """
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO conversation_summary "
                "(summary, covers_from_id, covers_to_id, model_used, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (summary, covers_from_id, covers_to_id, model_used, time.time()),
            )
        return cur.lastrowid

    def count_conversation_turns_since(self, conversation_id: int) -> int:
        """Count conversation rows with id > `conversation_id`.

        Used by the compression trigger to ask "how many raw turns have
        accumulated since the last summary cutoff?". Passing 0 counts the
        entire table (useful before the first summary exists).
        """
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM conversation WHERE id > ?", (conversation_id,)
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0

    def get_conversation_turns_range(self, from_id: int, to_id: int) -> list:
        """Fetch raw turns with from_id <= id <= to_id, oldest-first.

        This is what the compressor feeds to the summarization kernel —
        the raw turn stream that will be replaced by a summary row.
        Callers should pass the bounds they intend to cover so the saved
        summary's covers_from_id / covers_to_id match what was actually
        compressed.
        """
        cur = self.conn.execute(
            "SELECT id, role, content, image FROM conversation "
            "WHERE id >= ? AND id <= ? ORDER BY id ASC",
            (from_id, to_id),
        )
        return [
            {"id": r[0], "role": r[1], "content": r[2], "image": r[3]}
            for r in cur.fetchall()
        ]

    def get_newest_conversation_id(self) -> int | None:
        """Return MAX(id) from conversation, or None if the table is empty."""
        cur = self.conn.execute("SELECT MAX(id) FROM conversation")
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else None

    # ── Memory ────────────────────────────────────

    def add_memory(self, content: str):
        ts = time.time()
        with self.conn:
            self.conn.execute(
                "INSERT INTO memory (content, timestamp) VALUES (?, ?)",
                (content, ts),
            )

        # Add to vector memory
        self.memory_collection.add(
            documents=[content],
            ids=[str(ts)],
            metadatas=[{"timestamp": ts}]
        )
        self._prune_memory()

    def _prune_memory(self, limit: int = 1000):
        try:
            if self.memory_collection.count() > limit:
                res = self.memory_collection.get(include=["metadatas"])
                items = sorted(
                    zip(res['ids'], res['metadatas']),
                    key=lambda x: x[1].get('timestamp', float('inf')) if x[1] else float('inf')
                )
                num_to_delete = max(100, self.memory_collection.count() - limit + 50)
                ids_to_drop = [x[0] for x in items[:int(num_to_delete)]]
                if ids_to_drop:
                    self.memory_collection.delete(ids=ids_to_drop)
        except Exception:
            pass

    def get_recent_memory(self, limit: int = 5) -> list:
        cur = self.conn.execute(
            "SELECT content, timestamp FROM memory ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [{"content": r[0], "timestamp": r[1]} for r in cur.fetchall()]

    # ── Session Lifecycle ──
    def set_session_flag(self, key: str, value: str):
        self.set(f"session_{key}", value)

    def get_session_flag(self, key: str, default: str = None) -> str:
        return self.get(f"session_{key}", default)

    def get_relevant_memory(self, query: str, limit: int = 5) -> list:
        if not query:
            return self.get_recent_memory(limit)

        results = self.memory_collection.query(
            query_texts=[query],
            n_results=limit
        )

        if not results['documents'] or not results['documents'][0]:
            return []

        memories = []
        for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
            memories.append({"content": doc, "timestamp": meta["timestamp"]})

        # Sort by timestamp so the model sees them chronologically
        memories.sort(key=lambda x: x["timestamp"])
        return memories

    # ── Trace ─────────────────────────────────────

    def add_trace(self, step: str, message: str):
        with self.conn:
            self.conn.execute(
                "INSERT INTO trace (step, message, timestamp) VALUES (?, ?, ?)",
                (step, message, time.time()),
            )

        # Mirror every trace event into the structured log
        try:
            get_logger().log("INFO", f"loop.{step.lower()}", message)
        except Exception:
            pass

    # ── Log Query (delegates to SentinelLogger) ───

    def query_logs(self, **kwargs) -> list:
        return get_logger().query(**kwargs)

    # ── Key/Value State ───────────────────────────

    def set(self, key: str, value: str):
        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value)
            )

    def get(self, key: str, default: str = None) -> str:
        cur = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def get_all_state(self) -> dict:
        """Returns the entire key/value state table as a dictionary."""
        cur = self.conn.execute("SELECT key, value FROM state")
        return {r[0]: r[1] for r in cur.fetchall()}

    def clear_conversation(self):
        # Also wipe the summary table so the compressor doesn't serve a
        # [PRIOR CONTEXT] block pointing at id-ranges that no longer exist.
        # The table is recreated lazily on the next save_conversation_summary.
        # Tasks are NOT wiped here — they persist across conversation
        # clears because a user may /reset mid-plan and still want the
        # ledger intact. Use clear_tasks() explicitly to drop them.
        with self.conn:
            self.conn.execute("DELETE FROM conversation")
            self.conn.execute("DELETE FROM conversation_summary")

    # ── Tasks (v0.8.0 task ledger) ────────────────

    def create_task(self, description: str) -> int:
        """Insert a single pending task. Returns its row id.

        Thin wrapper around create_tasks([description]) — callers that
        register a plan should prefer the batch form so all rows share
        a timestamp and the ordering is deterministic.
        """
        ids = self.create_tasks([description])
        return ids[0]

    def create_tasks(self, descriptions: list) -> list:
        """Batch-insert pending tasks, preserving input order. Returns
        the list of row ids in the same order as `descriptions`.

        The task tool's `create` action calls this once with the full
        plan so the model can register a 20-step chain in a single
        tool call rather than 20 serial calls. Empty / whitespace-only
        entries are skipped silently — the tool layer is responsible
        for surfacing that as a validation error if it matters.
        """
        ts = time.time()
        ids = []
        with self.conn:
            for desc in descriptions:
                if not desc or not desc.strip():
                    continue
                cur = self.conn.execute(
                    "INSERT INTO tasks (description, status, created_at) "
                    "VALUES (?, 'pending', ?)",
                    (desc.strip(), ts),
                )
                ids.append(cur.lastrowid)
        return ids

    def mark_task_complete(self, task_id: int) -> bool:
        """Flip a task to 'completed' and stamp completed_at. Returns
        True iff a pending row with that id was updated.

        Idempotent on already-completed rows (returns False) so a
        double-complete from a retrying tool call doesn't raise.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (time.time(), task_id),
            )
        return cur.rowcount > 0

    def get_pending_tasks(self) -> list:
        """Return all pending tasks oldest-first. The first element is
        the cursor — the task the [ACTIVE TASKS] render marks with '▶'.
        """
        cur = self.conn.execute(
            "SELECT id, description, status, created_at, completed_at "
            "FROM tasks WHERE status = 'pending' ORDER BY id ASC"
        )
        return [
            {
                "id":           r[0],
                "description":  r[1],
                "status":       r[2],
                "created_at":   r[3],
                "completed_at": r[4],
            }
            for r in cur.fetchall()
        ]

    def get_all_active_tasks(self) -> list:
        """Return every task row (pending + completed), oldest-first.

        Used by the [ACTIVE TASKS] render so the model sees the whole
        plan in-flight with check-marks on finished items, not just
        what's left to do — the completed rows are the trail behind
        the cursor. `clear_tasks` is the only thing that drops rows.
        """
        cur = self.conn.execute(
            "SELECT id, description, status, created_at, completed_at "
            "FROM tasks ORDER BY id ASC"
        )
        return [
            {
                "id":           r[0],
                "description":  r[1],
                "status":       r[2],
                "created_at":   r[3],
                "completed_at": r[4],
            }
            for r in cur.fetchall()
        ]

    def clear_tasks(self):
        """Drop every task row. Called by the task tool's `clear` action
        when the model explicitly abandons / finishes a plan and wants a
        clean slate, or by tests between cases. Not called automatically
        — the ledger is deliberately sticky so a crash mid-plan doesn't
        lose the plan.
        """
        with self.conn:
            self.conn.execute("DELETE FROM tasks")
