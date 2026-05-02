"""
task.py — Persistent task-ledger tool (v0.8.0).

Purpose
-------
Gives the model a durable, ordered plan that survives across turns and
loop cycles. The ledger is rendered into the system prompt as an
[ACTIVE TASKS] block (cursor on the first pending row), and the pending
count drives a stuck-detection nudge in the outer loop. The intent is
to stop the model declaring "I'm done" halfway through a long chain
and to stop it re-deriving the plan from conversation history every
turn.

When to reach for it
--------------------
The task ledger is for plans that don't fit in a single chain run.
Short jobs — anything that can plausibly finish in a couple of tool
calls — should just chain tools directly; registering one or two tasks
is ledger bloat. Reach for `create` when either:

  - the plan has more steps than the chain limit (`chain_limit`,
    default 3) will let you finish in one go, OR
  - the plan will cross user turns and you want the next cycle to
    remember what's next without re-deriving it from history.

Rule of thumb: if you'd otherwise write "first I'll X, then Y, then Z"
in your response, and Z requires a new tool call after X and Y have
each returned results, register the plan as tasks. If it's "X then
reply", just chain.

Grain norm
----------
One task = one semantic milestone, NOT one tool call.

A three-block paginated file read is ONE task (pagination is handled
inside the task via the `[BLOCK N OF M — call with block=N+1]` footer
emitted by `filesystem:read`). Ten medium files with ~3 block calls
each is a 10-step plan, not a 30-step plan. This keeps the ledger
legible and keeps step counts tied to user-visible progress.

Actions
-------
  create   — register a plan. Accepts `tasks: list[str]` (batch) or
             `description: str` (single). Batch is preferred for the
             initial up-front plan.
  complete — mark a task finished by id. Call this as soon as the
             semantic milestone is met, not after every tool call.
  list     — return the full ledger (pending + completed, oldest-first)
             for diagnostic / read-back use. The [ACTIVE TASKS] block
             renders the same data, so you rarely need to call this.
  clear    — drop every task row. Only use when explicitly abandoning
             the plan or starting a fresh one. Completed rows are NOT
             auto-purged, so long-running sessions should `clear` once
             a plan is done if you want a clean slate next time.

Caps
----
A single `create` batch is capped at `_DEFAULT_MAX_TASKS` (default 20).
Exceeding the cap returns a rejection-as-teaching error rather than
truncating silently — the model either re-groups at a coarser grain
or registers the overflow in a follow-up batch.
"""

import os
import sqlite3
import time


TOOL_NAME        = "task"
TOOL_DESCRIPTION = (
    "Persistent task ledger for multi-step plans. "
    "WHEN TO USE: only register tasks when a plan exceeds the chain limit "
    "(default 3 tool calls per turn) OR will cross user turns. Short jobs "
    "that fit in a couple of chained tool calls should just chain directly "
    "— registering one or two tasks is ledger bloat. Rule of thumb: if "
    "you'd otherwise say \"first I'll X, then Y, then Z\" and Z needs a new "
    "tool call after X and Y return, register the plan; if it's \"X then "
    "reply,\" just chain. "
    "HOW TO USE: register the plan up-front with `create` (prefer the batch "
    "form `tasks: [...]` for multi-step plans), then call `complete` as "
    "each semantic milestone is met. Grain norm: ONE task per milestone, "
    "NOT one per tool call — a paginated read across 3 blocks is ONE task "
    "(pagination is handled via the [BLOCK N OF M] footer). The ledger is "
    "rendered into every system prompt as [ACTIVE TASKS] with a cursor on "
    "the first pending row, so you do not need to re-list the plan "
    "yourself. Use `clear` only when abandoning or restarting a plan."
)
TOOL_ENABLED     = True
TOOL_IS_SYSTEM   = True # System Prompt Ledger
TOOL_SCHEMA      = {
    "action": {
        "type": "string",
        "enum": ["create", "complete", "list", "clear"],
        "description": "create = register plan; complete = mark one done; list = dump ledger; clear = drop all.",
    },
    "tasks": {
        "type": "array",
        "items": {"type": "string"},
        "description": "create only (batch form, preferred). List of task descriptions, one per semantic milestone. Capped at 20 per call.",
    },
    "description": {
        "type": "string",
        "description": "create only (single form). A single task description; ignored if `tasks` is provided.",
    },
    "task_id": {
        "type": "integer",
        "description": "complete only. The integer id shown in the [ACTIVE TASKS] block.",
    },
}


# Soft cap on a single create batch. High enough that a 10-file read plan
# (10 tasks) or a medium multi-phase refactor fits; low enough that the
# model can't register a 200-step megaplan that no human would read. If a
# real plan needs more steps, the model can issue a follow-up `create`
# with the next chunk — the ledger preserves insertion order.
_DEFAULT_MAX_TASKS = 20


def _db_path() -> str:
    """Match the path convention used by tools/memory_manager.py so the
    tool works regardless of where Python was launched from."""
    return os.path.join(os.path.dirname(__file__), "..", "state", "state.db")


def _connect(conn_factory=None) -> sqlite3.Connection:
    # Phase E (UPGRADE_PLAN_4 sec 4) -- conn_factory injection. When the
    # Cognate surface supplies a zero-arg callable returning a sqlite3
    # connection, we use it; otherwise fall through to the Phase D
    # literal path (state/state.db). The PRAGMA + idempotent CREATE
    # TABLE stay here so the factory stays schema-agnostic.
    if conn_factory is not None:
        conn = conn_factory()
    else:
        path = _db_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    # Idempotent create: if the loop hasn't booted StateStore yet (e.g.
    # tool is executed in isolation during a test) we still want a
    # working table. The schema MUST stay in sync with core/state.py.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            description  TEXT    NOT NULL,
            status       TEXT    NOT NULL DEFAULT 'pending',
            created_at   REAL    NOT NULL,
            completed_at REAL
        )
    """)
    return conn


def _render_ledger(conn: sqlite3.Connection) -> str:
    """Format the full ledger as a plain-text list the model can read back.
    Same visual style as the [ACTIVE TASKS] block so `list` output and
    the system-prompt render don't drift."""
    cur = conn.execute(
        "SELECT id, description, status FROM tasks ORDER BY id ASC"
    )
    rows = cur.fetchall()
    if not rows:
        return "No active tasks."
    pending_seen = False
    lines = []
    for task_id, desc, status in rows:
        if status == "completed":
            lines.append(f"  [x] #{task_id}  {desc}")
        else:
            # Cursor on the first pending row only.
            marker = "▶" if not pending_seen else " "
            pending_seen = True
            lines.append(f"  {marker} [ ] #{task_id}  {desc}")
    return "\n".join(lines)


def _create(conn: sqlite3.Connection, tasks: list, description: str) -> str:
    # Normalize: `tasks` batch wins; fall back to single `description`.
    if tasks:
        if not isinstance(tasks, list):
            return "Error: `tasks` must be a list of strings."
        descs = [str(t).strip() for t in tasks if str(t).strip()]
    elif description and description.strip():
        descs = [description.strip()]
    else:
        return (
            "Error: `create` requires either `tasks` (list of strings, "
            "preferred for multi-step plans) or `description` (single string)."
        )

    if not descs:
        return "Error: no non-empty task descriptions provided."

    if len(descs) > _DEFAULT_MAX_TASKS:
        return (
            f"Error: batch of {len(descs)} tasks exceeds cap of "
            f"{_DEFAULT_MAX_TASKS}. Re-group at a coarser grain (remember: "
            f"one task per semantic milestone, not per tool call — a "
            f"paginated read is ONE task) or split into follow-up `create` "
            f"calls."
        )

    ts = time.time()
    ids = []
    with conn:
        for d in descs:
            cur = conn.execute(
                "INSERT INTO tasks (description, status, created_at) "
                "VALUES (?, 'pending', ?)",
                (d, ts),
            )
            ids.append(cur.lastrowid)

    header = f"Registered {len(ids)} task(s) (ids {ids[0]}..{ids[-1]}):"
    return header + "\n" + _render_ledger(conn)


def _complete(conn: sqlite3.Connection, task_id) -> str:
    if task_id is None:
        return "Error: `complete` requires `task_id` (integer)."
    try:
        tid = int(task_id)
    except (TypeError, ValueError):
        return f"Error: `task_id` must be an integer, got {task_id!r}."

    cur = conn.execute(
        "SELECT status, description FROM tasks WHERE id = ?", (tid,)
    )
    row = cur.fetchone()
    if not row:
        return f"Error: no task with id {tid}. Use `list` to see active ids."
    status, desc = row
    if status == "completed":
        return f"Task #{tid} ('{desc}') was already completed — no change."

    with conn:
        conn.execute(
            "UPDATE tasks SET status = 'completed', completed_at = ? "
            "WHERE id = ?",
            (time.time(), tid),
        )

    # Count what's left so the model gets a proximate sense of progress
    # without having to diff the render.
    cur = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
    remaining = cur.fetchone()[0]
    trail = f"Completed #{tid} ('{desc}'). {remaining} task(s) remaining."
    if remaining == 0:
        trail += " Plan complete — call `task` with action=`clear` if you want a fresh slate."
    return trail + "\n" + _render_ledger(conn)


def _list(conn: sqlite3.Connection) -> str:
    return _render_ledger(conn)


def _clear(conn: sqlite3.Connection) -> str:
    cur = conn.execute("SELECT COUNT(*) FROM tasks")
    n = cur.fetchone()[0]
    with conn:
        conn.execute("DELETE FROM tasks")
    return f"Cleared {n} task row(s). Ledger is empty."


def execute(action: str = "", tasks: list = None, description: str = "",
            task_id=None, *, conn_factory=None, tool_context=None) -> str:
    # Phase E (UPGRADE_PLAN_4 sec 4) -- optional conn_factory injection
    # forwarded to _connect so the Cognate surface can route task-ledger
    # I/O without the loop shim's sqlite3.connect interception. Legacy
    # boot (loop.py) passes nothing and the Phase D literal is unchanged.
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
    if not action:
        return (
            "Error: `action` is required. Valid actions: create, complete, "
            "list, clear."
        )

    conn = _connect(conn_factory=conn_factory)
    try:
        if action == "create":
            return _create(conn, tasks or [], description or "")
        if action == "complete":
            return _complete(conn, task_id)
        if action == "list":
            return _list(conn)
        if action == "clear":
            return _clear(conn)
        return (
            f"Error: unknown action {action!r}. Valid actions: "
            f"create, complete, list, clear."
        )
    except Exception as e:
        return f"Task tool error: {e}"
    finally:
        conn.close()
