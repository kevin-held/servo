import sqlite3
import time
from pathlib import Path
import chromadb
from core.sentinel_logger import get_logger


class StateStore:
    """
    Persistent state. Everything the loop needs to survive across sessions.
    Four tables: conversation, memory, trace, state (key/value).
    Plus: chroma vector database for episodic memory
    """

    def __init__(self, db_path: str = "state/state.db", chroma_path: str = "state/chroma"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        
        # Initialize Vector Database
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.memory_collection = self.chroma_client.get_or_create_collection(name="episodic_memory")

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
        cur = self.conn.execute(
            "SELECT role, content, image FROM conversation ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [{"role": r[0], "content": r[1], "image": r[2]} for r in reversed(cur.fetchall())]

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

    def clear_conversation(self):
        with self.conn:
            self.conn.execute("DELETE FROM conversation")
