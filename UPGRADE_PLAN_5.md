# UPGRADE_PLAN_5.md
**Phase:** F — LLM-Driven REASON + Chat-as-Perception + Tool-Context Contract + USE_SERVO_CORE Retirement
**Status:** DRAFT — PENDING APPROVAL | **Priority:** HIGH
**Author:** Servo (Claude, in cooperation with Kevin)
**Date:** D-20260425
**Supersedes Scope-Of:** `UPGRADE_PLAN_4.md` (closed, Phase E landed as v1.6.0)
**Synced Commit:** post-D-20260424-01 (Phase E ADR accepted, v1.6.0 released)

---

## 1. Objective

Phase E moved seven literals into a registry, retired the memory-routing monkey-patch, enriched the cold-start signal, and put the GUI on `ServoCore` behind a default-true toggle. The autonomous benchmark circuit is closed and sharper, but the GUI's chat lane still falls back to a polite stub:

```python
# lx_servo_thread.py (Phase E):
self.response_ready.emit(
    "[Servo path] User-input dispatch is wired in Phase F. "
    "Set SERVO_CORE=0 to use the legacy CoreLoop for chat.",
    "",
)
```

A user typing into the GUI under `USE_SERVO_CORE=1` is talking to a placeholder. Phase F closes that gap with two architectural commitments — both resolved by Kevin during plan drafting (D-20260425):

1. **Chat-as-perception.** User input enters the cognate loop as an `lx_Observe` perception. Tool output from a previous ACT enters the same way. There is one cognate loop, not two; chat and (eventual) ambient activity ride the same OBSERVE→REASON→ACT→INTEGRATE rails.

2. **REASON is LLM-driven.** REASON's job in Phase F is no longer ε-greedy bandit selection over `procedural_wins`. It builds a system prompt containing the conversation history, the current observation, and the bandit's top-k tools-for-this-signature as a hint section, then calls Ollama. The LLM emits prose, an optional tool call, or both, in the same fenced-JSON schema the legacy CoreLoop already uses. Whether the loop continues or parks is the LLM's implicit decision: tool call present → ACT runs and the next cycle picks up the tool output → another REASON pass; tool call absent → nothing for ACT to do → next OBSERVE finds nothing pending → park.

The bandit doesn't retire — it becomes a **hint feeder**. `_exploit`'s ranking still computes per cycle, still consults `procedural_wins`, but its output goes into REASON's system prompt instead of directly to ACT. Procedural_wins still commits in INTEGRATE for actual dispatches, so the bandit keeps learning even though it no longer makes the final call. Kevin's framing: "as the models get smarter this will prove important."

Two pieces of Phase E scaffolding retire:

- **`_get_loop_ref` monkey-patch.** `system_config` and `context_dump` still reach for `loop.state` / `loop.config` / `loop.telemetry` via the `LxLoopAdapter` shim. A uniform `tool_context` kwarg (the natural extension of Phase E's `conn_factory`) closes that hole. `ServoCore.run_cycle` no longer installs the shim.
- **`USE_SERVO_CORE` toggle.** Phase E shipped default-true with a one-flip rollback. Phase F's release gate (v1.7.0) drops the toggle entirely. `core/loop.py` itself stays untouched — that's the No-Write file — but `gui/main_window.py` no longer constructs it.

What's explicitly **not** in Phase F per Kevin's drafting note: auto-action on environmental signals (error logs, manifest staleness, file drift). The loop continues to *observe* env drift and the bandit still consults it for hint construction, but in the GUI context the loop never wakes itself up to dispatch a tool the user didn't request. That capability — ambient agency — is a Phase G+ design with its own scoping decisions (rate limiting, action filtering, kill-switch UX). Phase F's loop is strictly user-driven (or, equivalently, tool-output-followup-driven once a user request kicks off a chain).

The Cognate contract stays frozen at the four-class level. `procedural_wins` schema stays frozen. `loop.py` stays untouched at the source level. `ATOMIC_PRIMITIVES` stays at eleven — there is no `respond_to_user` primitive; the response *is* the LLM's prose output, emitted to chat directly out of REASON.

---

## 2. Scope

**In-Scope:**
- **Chat-as-perception input lane.** `ServoCore` gains a `_pending_user_inputs` deque populated by a new `submit_user_input(text, image_b64)` method. `ServoCoreThread.submit_input` delegates to it.
- **Tool-output perception.** ACT writes its output to `state["pending_tool_output"]`. The next OBSERVE notices the pending output, builds a tool-output perception, and advances to REASON without parking. INTEGRATE clears the pending key after persisting the conversation turn.
- **OBSERVE park/wake gate.** OBSERVE checks two state slots in order: (a) pending tool output → tool-output perception, advance; (b) pending user input → user-input perception, advance; (c) neither → park. Park semantics: the loop blocks on a condition variable that `submit_user_input` notifies. No env-audit snapshot, no bandit ranking, no cycle work happens while parked.
- **LLM-driven REASON.** A new `_reason_via_llm` method builds the system prompt (history + observation + bandit top-k hint), calls `OllamaClient.generate`, and returns the raw response. The existing `_explore` / `_exploit` helpers stay alive but are repurposed to build the hint section rather than make the final pick.
- **Tool-call parser as shared module.** `core/tool_call_parser.py` carries a free function `parse_tool_call(text) -> dict | None` that is a deliberate copy of `core.loop.CoreLoop._parse_tool_call`. Drift discipline: `loop.py` is No-Write, so its copy is effectively frozen; the new module is the canonical Phase F+ version. A comment cross-references both sites.
- **ACT shrinks.** `lx_Act.execute` reads the parsed tool call from state. Tool call present → registry dispatch + lexicon gate, exactly as Phase E. Tool call absent → no-op skip with `outcome.status == "no_tool_call"`, no lexicon scan (the prose response is destined for chat, not for tool-output evaluation; lexicon gating chat output is a Phase G+ judge concern).
- **INTEGRATE persistence.** When the perception was user-input or tool-output, INTEGRATE writes the relevant turns to `lx_StateStore.add_conversation_turn`. Reward computation only fires for actual tool dispatches (skip means no commit), keeping the procedural_wins schema clean.
- **Tool-context contract.** A new `core/tool_context.py` exposing a `ToolContext` dataclass holding `state`, `config`, `telemetry`, `conn_factory`, `ollama`. `system_config`, `context_dump`, `memory_manager`, `memory_snapshot`, and `task` all accept an optional `tool_context` kwarg; legacy `_get_loop_ref` and `conn_factory` paths preserved as fallbacks.
- **`_get_loop_ref` retirement.** `core/lx_loop_shim.py` stays in the file (legacy CoreLoop boot still uses it), but `ServoCore.run_cycle` no longer calls `lx_loop_shim.install`.
- **Benchmark Ollama stub.** `benchmark/lx_ollama_fixture.py` (new) exposes a stub client whose `generate(messages)` reads the bandit hint section from the system prompt and emits a fenced-JSON tool call for the bandit's top-1. Phase A's deterministic ranking still drives benchmark behavior end-to-end; the LLM-REASON code path is exercised without network or model dependencies.
- **ConfigRegistry hot-reload.** `ConfigRegistry.maybe_reload()` compares `os.path.getmtime(self._path)` to the cached mtime and re-reads on change. `ServoCore.run_cycle` calls it once per OBSERVE entry.
- **`USE_SERVO_CORE` retirement.** Step 9 of the execution order drops the toggle from `gui/main_window.py`. The legacy `CoreLoop` construction path is removed from `main_window`; the import comes out too. `core/loop.py` stays compilable and importable, just unconstructed by any first-class entry point. v1.7.0 release gate.

**Stub-Only / Deferred to Phase G+:**
- **Auto-action on environmental signals** (error logs, manifest staleness, file drift). Per Kevin's drafting note, ambient agency is its own scoping concern. The loop observes env drift via the existing `_snapshot_environment` and `_observation_signal` paths but does not autonomously dispatch tools based on it.
- **Multiple tool calls per LLM output.** Phase F's parser accepts the legacy single-tool-call schema. The LLM emitting an array of tool calls would require ACT to iterate, INTEGRATE to commit per-dispatch, and a queueing discipline; deferred per Kevin's drafting note.
- **Skip-INTEGRATE / skip-OBSERVE shortcuts.** Phase F runs every cycle as a full four-step rotation. The model dropping straight from ACT back to REASON without OBSERVE/INTEGRATE in between is a future change with its own design.
- **Streamed token-level response emission.** `_reason_via_llm` calls `OllamaClient.generate` synchronously and emits the full response in one `response_ready` payload. Streaming via `stream_chunk` requires a callback path through the LLM client; deferred.
- **Lexicon gate on chat prose.** Phase F's lexicon scan runs only on tool output. A poisoned chat response (FAIL_PATTERNS in the prose) reaches the user. A Phase G+ judge cognate is the right shape for this — a regex on chat is the wrong tool.
- **Image input through chat-as-perception.** `submit_user_input(text, image_b64)` accepts an image; the perception payload carries it forward, but `_reason_via_llm` only sends text to the LLM. Multimodal generation is Phase G+.
- **kNN cold-start over historical env_audit snapshots in ChromaDB.** Phase E §11 candidate; deferred again.
- **Telemetry-driven tuning of `nn_similarity_floor`.** Phase E carryover; deferred again.

---

## 3. Constraints Inherited from Prior Decisions

- **No-Write on `core/loop.py`** (confirmed Phase E, reaffirmed Phase F) — remains active. `USE_SERVO_CORE` retirement removes the toggle from `gui/main_window.py`; `loop.py` stays byte-identical. The acceptance gate re-checks `git diff`.
- **Reference preservation of `loop.py`** — unchanged. Even after the toggle drops, `from core.loop import CoreLoop` continues to work; the GUI just doesn't call it. The legacy `_parse_tool_call` and `_strip_tool_calls` methods stay in `loop.py` as the canonical reference; `core/tool_call_parser.py` is a deliberate Phase F copy with the No-Write file as the textual source of truth.
- **Atomic-primitive contract** — frozen at eleven. No `respond_to_user`. Chat is the LLM's prose output, not a tool dispatch.
- **No-Write on legacy SQLite `state/state.db`** — unchanged. Re-runs sha256-identical check (Phase E Step 4 pattern).
- **Lexicon compliance gate** — narrowed in scope. Phase F runs the scan only on tool-output paths; chat prose is exempt (Phase G+ judge concern).
- **Polymorphic contract `OBSERVE → REASON → ACT → INTEGRATE`** — frozen. Park/wake happens *at* OBSERVE entry; the four-step rotation itself is unchanged within any cycle that fires.
- **`procedural_wins` schema** — frozen. Reward commits only when ACT actually dispatched (no commits for skip outcomes).
- **`ConfigRegistry` overlay-not-replace semantics** — unchanged. Hot-reload preserves keys absent from the new file.

---

## 4. Chat-as-Perception + LLM-Driven REASON (Architecture)

### 4.1 Two perception kinds + OBSERVE park/wake gate

`lx_Observe.execute` becomes a three-branch dispatcher:

```python
def execute(self, state: dict) -> dict:
    # (1) Tool-output followup -- next REASON sees the tool result.
    pending_output = state.get("pending_tool_output")
    if pending_output:
        return self._observe_tool_output(pending_output, state)

    # (2) User input -- next REASON sees the user message.
    pending_inputs = getattr(self.core, "_pending_user_inputs", None)
    if pending_inputs:
        entry = pending_inputs.popleft()
        return self._observe_user_input(entry, state)

    # (3) Park. Block until submit_user_input notifies.
    self.core._wait_for_perception()  # condition-variable block
    # Re-enter with one of the two slots populated.
    return self.execute(state)
```

`_observe_user_input` builds a delta carrying:
- `observation_kind: "user_input"`
- `user_input_text` (transient — INTEGRATE clears)
- `observation_signature` derived from `f"user|{text}"` (partitioned from env signatures)
- `observation_embedding` (Ollama embed of the user text)
- `env_audit` (ambient context, computed via existing `_snapshot_environment` — informational, not signal)

`_observe_tool_output` builds a delta carrying:
- `observation_kind: "tool_output"`
- `last_tool_output` (from the previous ACT)
- `observation_signature` derived from `f"tool|{tool_name}|{user_signature_of_originating_input}"` so a tool output is anchored to the user request that triggered it
- `observation_embedding` (Ollama embed of the tool output, truncated to a sane length)

`_wait_for_perception` is a `threading.Condition` block. `ServoCore.submit_user_input` notifies it. The benchmark path never hits this (the test fixture pre-populates the deque before each cycle).

### 4.2 LLM-driven REASON

`lx_Reason.execute` branches on `observation_kind`. For `user_input` and `tool_output` perceptions, REASON runs the LLM path:

```python
def _reason_via_llm(self, state: dict) -> dict:
    messages = self._build_messages(state)
    raw = self.core.ollama.generate(messages=messages)
    tool_call = parse_tool_call(raw)               # core.tool_call_parser
    prose     = strip_tool_calls(raw)              # core.tool_call_parser

    return {
        "current_step": "ACT",
        "raw_llm_response": raw,
        "response_text": prose,
        "planned_tool":   (tool_call or {}).get("tool"),
        "planned_args":   (tool_call or {}).get("args", {}),
        "decision_mode":  "llm",
        "last_trace": f"REASON: tool={tool_call and tool_call.get('tool')!r}",
    }
```

`_build_messages` assembles:
1. System prompt: persona + tool registry + bandit hint section + ambient context summary.
2. Conversation history slice: `lx_StateStore.get_conversation_history(limit=N)` where `N = config.get("reason_history_turns", 6)`.
3. Current turn: the user input (for user-input perceptions) or a tool-output report (for tool-output perceptions).

The **bandit hint section** is what keeps procedural_wins relevant. `_exploit` continues to compute the top-k tools for the current `observation_signature`, but instead of returning a single pick, it returns up to `config.get("bandit_hint_topk", 3)` candidates. They land in the system prompt as:

```
Recent successful dispatches for similar observations:
  - file_read (avg reward 0.91, last similarity 0.84)
  - map_project (avg reward 0.78, last similarity 0.81)
  - file_list (avg reward 0.72, last similarity 0.79)
You are not required to use these. They are statistical priors, not commands.
```

The LLM is free to pick a tool not in the hint section, or to emit prose only and skip the tool call. The bandit's role is to surface recent reward signal; the model's role is to decide.

### 4.3 ACT shrinks

`lx_Act.execute` becomes:

```python
def execute(self, state: dict) -> dict:
    tool = state.get("planned_tool")

    # No tool call -- the LLM emitted prose only.
    if not tool:
        outcome = ToolOutcome.skip("<none>", "no tool call from REASON")
        return self._wrap_delta(outcome, halt=False, pending_tool_output=None)

    # Existing dispatch path (registry + lexicon gate + procedural_wins commit).
    # ... unchanged ...

    # Phase F addition -- stash the outcome for the next OBSERVE to pick up.
    return self._wrap_delta(outcome, halt=halt, pending_tool_output=outcome.to_dict())
```

The `_wrap_delta` method gains a `pending_tool_output` parameter; when non-None, it goes into the delta so the next OBSERVE sees it. INTEGRATE clears the slot after persisting the conversation turn.

### 4.4 INTEGRATE persistence + reward

```python
def execute(self, state: dict) -> dict:
    kind = state.get("observation_kind")

    if kind == "user_input":
        user_text = state.get("user_input_text", "")
        response  = state.get("response_text", "")
        store.add_conversation_turn("user", user_text, "")
        if response:
            store.add_conversation_turn("assistant", response, "")
            self._emit_response_ready_hook(response)  # ServoCoreThread bridge

    elif kind == "tool_output":
        # Tool output already lived in conversation history via the previous
        # cycle's ACT-wrapped tool_called signal. No double-write here.
        pass

    # Reward commit -- only when ACT actually dispatched (procedural_wins
    # stays clean of "no_tool_call" skip rows).
    outcome = state.get("last_outcome") or {}
    if outcome.get("status") not in (None, "skip", "no_tool_call"):
        # ... existing reward computation + commit ...

    # Cache audit snapshot for next REASON's drift detection (preserved from Phase E).
    self.core._prior_audit_snapshot = state.get("env_audit")

    # Clear the pending_tool_output so OBSERVE doesn't loop on it.
    return {"current_step": "OBSERVE", "pending_tool_output": None, ...}
```

`_emit_response_ready_hook` is a callable on `lx_Integrate` that `ServoCoreThread.__init__` sets to `lambda txt: self.response_ready.emit(str(txt or ""), "llm")`. Same pattern as Phase E's `_lx_dispatch_hook` and the rejected `_lx_response_hook`.

### 4.5 Tool-call parsing reuse

`core/tool_call_parser.py` exposes:

```python
def parse_tool_call(text: str) -> dict | None: ...  # 4-fallback strategy
def strip_tool_calls(text: str) -> str: ...
```

These are textually copied from `core/loop.py._parse_tool_call` and `_strip_tool_calls`. Drift discipline: `loop.py` is No-Write; its copy can never diverge. The new module is the canonical Phase F+ source; Phase G+ may unify them if No-Write lifts.

### 4.6 Loop control is the LLM's

The cycle's continue/park decision falls out of the LLM's output — no explicit controller logic anywhere in the cognates:

| LLM output | ACT | Next OBSERVE |
|---|---|---|
| Prose only | Skip | No pending_tool_output, no pending user_input → park |
| Prose + tool call | Dispatch tool | pending_tool_output set → tool-output perception → REASON sees result |
| Tool call only | Dispatch tool | Same as above |

A user typing "hello" with the loop parked: `submit_user_input` notifies the condition variable, OBSERVE wakes with the user-input deque populated, REASON calls Ollama, the model emits "Hi!" with no tool call, ACT skips, INTEGRATE persists the turn and emits `response_ready`, OBSERVE re-enters and finds nothing pending, parks. One cycle, one response.

A user typing "what's in the codex folder?" with the loop parked: same wake path, REASON calls Ollama, the model emits prose plus `{"tool": "file_list", "args": {"path": "codex/"}}`, ACT dispatches, INTEGRATE persists the user turn and the prose response, OBSERVE wakes again with `pending_tool_output` set, REASON gets called again with the tool result in messages, the model emits a follow-up prose response based on the listing, ACT skips, INTEGRATE persists, OBSERVE parks. Two cycles, two assistant turns visible to the user.

### 4.7 Why bandit-as-hint, not bandit-only or LLM-only

The rejected alternatives:

- **Bandit-only REASON** (Phase E behavior, kept as-is): the LLM doesn't see chat. This is what shipped in v1.6.0 with the polite stub. Closes the autonomous loop but leaves chat broken.
- **LLM-only REASON** (no bandit): the LLM picks tools cold every time. Procedural_wins becomes write-only — committed but never read. Defeats Phase D's whole semantic-NN investment.
- **Bandit-as-hint** (Phase F): the LLM picks, the bandit informs. Procedural_wins keeps growing and keeps being read. The hint is a soft prior, not a hard rail. As models get sharper, the hint has less leverage but stays useful as a "what worked recently" signal.

The deciding property, articulated by Kevin during planning: the harness should validate plumbing, not judgment. The bandit is plumbing — a deterministic ranker over committed rewards. The LLM is judgment. Phase F keeps both, in their respective lanes.

---

## 5. Tool-Context Contract (Architecture)

### 5.1 Current state (Phase E)

Five tools currently reach for runtime context:

```python
# tools/system_config.py: loop = _get_loop_ref()
# tools/context_dump.py:  loop = _get_loop_ref()
# tools/memory_manager.py + tools/memory_snapshot.py: conn_factory kwarg (Phase E)
# tools/task.py: conn_factory kwarg (Phase E)
```

The `conn_factory` pattern is uniform and works. The `_get_loop_ref` pattern depends on `lx_loop_shim` monkey-patching `tools.system_config._get_loop_ref` and `tools.context_dump._get_loop_ref` to return an `LxLoopAdapter`. Two things are unsatisfying:
- Runtime sys.modules mutation, the kind of shim Phase E set out to retire.
- It's the only remaining reason `lx_loop_shim` exists as a runtime install in `ServoCore.run_cycle`. Drop it, and the shim becomes legacy-CoreLoop-only.

### 5.2 Phase F refactor

A new module `core/tool_context.py`:

```python
@dataclass
class ToolContext:
    state: Any                         # lx_StateStore or CoreLoop.state
    config: Any                        # ConfigRegistry or CoreLoop.config dict
    telemetry: Any                     # counters facade
    conn_factory: Optional[Callable]   # sqlite3.Connection factory
    ollama: Any                        # OllamaClient
    legacy_loop_ref: Optional[Any] = None  # escape hatch for CoreLoop boot path
```

Five tools accept `tool_context: Optional[ToolContext] = None` as keyword-only:
- `system_config` — reads `tool_context.state` / `.config`. Falls back to `_get_loop_ref()` when None.
- `context_dump` — same pattern.
- `memory_manager`, `memory_snapshot`, `task` — accept `tool_context` *in addition to* `conn_factory`. When `tool_context` is provided and `conn_factory` is omitted, derive from `tool_context.conn_factory`. Phase E callers continue to work unchanged.

`lx_Act._build_tool_context` (new helper) constructs the context once per dispatch from `self.core` plus the existing `_build_conn_factory` result.

### 5.3 Shim retirement (partial)

`core/lx_loop_shim.py` stays in the file. `LxLoopAdapter` and the `_get_loop_ref` patching surface remain importable for the legacy `CoreLoop` boot path. `ServoCore.run_cycle` removes the `lx_loop_shim.install` call. After Phase F:
- `lx_loop_shim.install` is called by `core/loop.py`'s boot path (if any).
- `lx_loop_shim.install` is **not** called by `core/core.py` at all.

Cleanest possible retirement under No-Write: delete a call site, not a module.

### 5.4 Tool schema compatibility

`tool_context` is keyword-only and optional. Procedural_wins entries, default-args dicts, and the `_default_args_for` table all stay schema-identical. The context is injected at dispatch time by `lx_Act`, never appears in the planned-args dict. Same discipline as `conn_factory` in Phase E.

---

## 6. ConfigRegistry Hot-Reload (Architecture)

### 6.1 Current state (Phase E)

`ConfigRegistry.__init__` reads `config.json` once. `reload()` exists but no caller invokes it during a run. A user editing `config.json` mid-run sees no effect until process restart.

### 6.2 Phase F addition

```python
def __init__(self, path: Optional[Path] = None):
    ...
    self._mtime: float = 0.0
    self.reload()  # populates _mtime

def reload(self) -> None:
    try:
        if not self._path.exists():
            self._mtime = 0.0
            return
        self._mtime = self._path.stat().st_mtime
        ...  # existing overlay logic
    except Exception:
        return

def maybe_reload(self) -> bool:
    """Re-read iff mtime changed since last reload."""
    try:
        if not self._path.exists():
            if self._mtime != 0.0:
                self._mtime = 0.0
                self._values = dict(self._DEFAULTS)
                return True
            return False
        current_mtime = self._path.stat().st_mtime
        if current_mtime != self._mtime:
            self.reload()
            return True
        return False
    except Exception:
        return False
```

`ServoCore.run_cycle` calls `self.config.maybe_reload()` once per loop iteration. Cost: one stat call per cycle. Telemetry: reload count surfaces via `as_dict()` snapshots if Phase G+ wants it.

### 6.3 Atomic-overlay safety

A user editing `config.json` non-atomically could be observed mid-write — `reload` parses an incomplete JSON, hits the silent-fail except, falls back to the prior in-memory state. The next valid mtime change re-reads and recovers. Atomic editor saves are not racing: the overlay applies in-memory and the previous values are preserved in `self._values` until a new overlay parses successfully.

---

## 7. USE_SERVO_CORE Retirement (Release Gate)

### 7.1 Current state (Phase E)

`gui/main_window.py` resolves `USE_SERVO_CORE` from env var or `config.json`, defaults true, branches construction between `ServoCoreThread` and `CoreLoop`.

### 7.2 Phase F retirement

After all other Phase F gates pass, **Step 9** retires the toggle:
- `_resolve_use_servo_core` and `_load_config_use_servo_core` deleted.
- `USE_SERVO_CORE` constant deleted.
- `MainWindow.__init__` constructs `ServoCoreThread` unconditionally.
- `from core.loop import CoreLoop` removed from `main_window.py`. The import in `core/loop.py` itself stays (No-Write).
- `codex/manifests/config.json` may keep a `use_servo_core` key for backward-compat; no code reads it.

v1.7.0 release gate. After v1.7.0:
- Running the GUI on `CoreLoop` requires checking out v1.6.0.
- The cognate loop is the production path. `core/loop.py` stays compilable and importable for reference, but no first-class entry point constructs it.

### 7.3 Conditions for the gate

Each must be green at §9 acceptance:
- LLM-driven REASON works end-to-end on a real GUI smoke test (not a fixture).
- `tool_context` has landed and `_get_loop_ref` is no longer called by `ServoCore.run_cycle`.
- ConfigRegistry hot-reload round-trip verified with a running loop.
- 100-cycle bench under the Ollama fixture confirms park/wake gating doesn't deadlock and `procedural_wins` commits cleanly.

If any signal is yellow, Step 9 defers to v1.7.1 and Phase F lands as v1.7.0-rc1 (toggle preserved, all other Phase F work shipped).

---

## 8. Execution Order (Nine Steps)

Dependency-driven; each step lands cleanly (incl. Phase A audit green where applicable) before the next.

1. **Add `core/tool_context.py` with `ToolContext` dataclass.** Pure addition; no behavior change. Verify: import + instantiation with all-None succeed.
2. **Refactor `system_config`, `context_dump`, `memory_manager`, `memory_snapshot`, `task` to accept `tool_context` kwarg.** Legacy `_get_loop_ref` and `conn_factory` paths preserved as fallbacks. Verify: standalone tool tests pass; Phase A audit green.
3. **Add `core/tool_call_parser.py` (parse + strip).** Textual copy of `core/loop.py._parse_tool_call` and `_strip_tool_calls`. Verify: unit tests against the same fixture corpus the legacy parser handles (fenced JSON, trailing brackets, Windows paths, multiline strings).
4. **LLM-driven REASON + benchmark Ollama fixture.** Add `_reason_via_llm`, `_build_messages`, repurpose `_exploit` to return top-k for hint construction. Add `benchmark/lx_ollama_fixture.py` exposing a `StubOllama` whose `generate()` parses the bandit-hint section and returns the top-1 as a fenced-JSON tool call. Phase A audit harness wired to use the stub. Verify: full audit green under stub; LLM-REASON code path exercised end-to-end without network.
5. **Two perception kinds + OBSERVE park/wake gate.** Add `_pending_user_inputs` deque + `submit_user_input` to `ServoCore`. Add `_observe_user_input` and `_observe_tool_output` branches. Add `_wait_for_perception` condition-variable block. Verify: synthetic test with empty deque blocks; `submit_user_input` wakes; user-input perception advances; tool-output perception advances after a tool dispatch.
6. **ACT shrinks + INTEGRATE persists + response_ready hook.** ACT skips cleanly on no-tool-call; INTEGRATE persists user/assistant turns; `_emit_response_ready_hook` wired by `ServoCoreThread`. Verify: GUI smoke test under `USE_SERVO_CORE=1` types "hello" and gets a real LLM response in the chat panel.
7. **Retire `_get_loop_ref` shim install.** Remove `lx_loop_shim.install` call from `core/core.py.run_cycle`. Verify: 100-cycle bench, sha256(state/state.db) byte-identical, no `_get_loop_ref` AttributeError, `system_config` and `context_dump` still work via `tool_context`.
8. **ConfigRegistry hot-reload.** Add `maybe_reload()`; wire into `run_cycle`. Verify: edit config.json with the loop running, observe next cycle pick up the new value.
9. **Drop `USE_SERVO_CORE` toggle (v1.7.0 release gate).** Remove resolver + constant + branch + `CoreLoop` import from `gui/main_window.py`. Verify: GUI boots and runs chat unconditionally on `ServoCoreThread`. §9 acceptance gates pass.

---

## 9. Acceptance Gate

Phase F is **complete** iff:

- `python -m benchmark.lx_audit_manager` exits 0 with `Overall Pass: True` under the new `StubOllama` fixture.
- A synthetic user-input cycle produces an LLM-driven REASON pass, a parsed tool call (or skip), and — when a tool dispatched — a follow-up cycle whose REASON sees the tool output as new context. Specifically: `core.submit_user_input("what's in codex/?"); core.run_cycle(store)` advances OBSERVE → REASON → ACT → INTEGRATE → OBSERVE → REASON → ACT → INTEGRATE under the stub, with `response_text` populated on the second pass.
- A real GUI smoke test under `USE_SERVO_CORE=1` (before Step 9) types "hello" into the chat panel and observes a real Ollama response within normal latency budget. No fallback placeholder text.
- OBSERVE park/wake gate works: with empty deques and no `pending_tool_output`, the loop blocks on the condition variable; `submit_user_input` notifies and the next cycle fires. Verified by a `threading.Thread`-driven test.
- Bandit hint construction: under `observation_kind == "user_input"`, the system prompt sent to the LLM contains the top-k tools for the current `observation_signature` (k = `config.get("bandit_hint_topk", 3)`). Verified by capturing the messages payload during a synthetic cycle.
- `tool_context` accepted by all five tools as keyword-only; standalone tests pass with both `tool_context` injected and `tool_context=None`.
- `core/lx_loop_shim.py.install` is **not called** by `core/core.py` (verified by grep). The `_get_loop_ref` monkey-patch no longer fires under the ServoCore path.
- `ConfigRegistry.maybe_reload()` round-trips: write `{"epsilon_0": 0.42}` to a running registry's config.json, call `maybe_reload()`, observe `get("epsilon_0") == 0.42`. Delete config.json, call `maybe_reload()`, observe defaults restored.
- `sha256(state/state.db)` byte-identical before/after a 100-cycle bench run with all eleven primitives dispatched (Phase E Step 4 pattern, re-run with `tool_context` path).
- `git diff --ignore-cr-at-eol core/loop.py` empty.
- `gui/main_window.py` no longer imports `core.loop.CoreLoop`. Unconditional `ServoCoreThread` construction. (Step 9 gate.)
- `procedural_wins` retains all Phase E entries and accepts new entries — both `env|`-prefixed and `user|`-prefixed signatures — with unchanged metadata schema.
- No new file larger than 300 lines. (`tool_context.py` ~60 lines, `tool_call_parser.py` ~80 lines, `lx_ollama_fixture.py` ~80 lines.)

Any single failure re-opens the circuit; no partial credit. Step 9 conditionally defers to v1.7.1 if any chat-as-perception or LLM-REASON gate is yellow at the v1.7.0 audit.

---

## 10. Open Questions

These are flagged for Kevin's review during plan approval. Phase F execution proceeds with the resolutions baked in.

- **Q1 — Bandit hint top-k.** Default proposal: 3. Trade-off: more candidates surface more reward signal but dilute the prior; fewer are sharper but risk burying a useful tool. Three feels like the right starting point; ConfigRegistry key (`bandit_hint_topk`) makes it tunable.
- **Q2 — Conversation history slice for REASON.** Default proposal: ConfigRegistry key `reason_history_turns` with default 6. Same trade-off space as Phase E's compression triggers; 6 turns covers a typical multi-turn exchange without bloating the prompt.
- **Q3 — Tool-output perception signature anchoring.** Default proposal: `f"tool|{tool_name}|{originating_user_signature}"`. The originating user signature is stashed in state at the user-input cycle and propagated forward. This keeps `procedural_wins` neighborhood searches coherent — a tool output following a "list files" request is a different observation than a tool output following "read X". Worth confirming.
- **Q4 — Park-wake on env drift.** Phase F's gate parks on no-input, no-tool-output. Should significant env drift (the Phase E `drift_detected` signal) also wake the loop? Default proposal: **no**, per Kevin's drafting note. Env drift is observed when a cycle fires for a user reason; it does not autonomously trigger cycles. Auto-action stays a Phase G+ design.
- **Q5 — Lexicon gate scope.** Default proposal: scan tool output only. Chat prose is exempt. A poisoned chat response reaches the user; this is the LLM's bug, not Servo's. A Phase G+ judge cognate is the right shape for chat quality gating.
- **Q6 — Image_b64 carry-forward.** Default proposal: store in perception payload, ignored by `_reason_via_llm` in Phase F. State payload growth bounded by `deque(maxlen=64)`. Multimodal generation is Phase G+.
- **Q7 — Step 9 firmness.** Default proposal: ship Steps 1-8 as v1.7.0; Step 9 lands as v1.7.0 only if the smoke tests pass cleanly on first run. A flaky smoke test bumps Step 9 to v1.7.1. Same risk-management posture as Phase E's `USE_SERVO_CORE=true` default.
- **Q8 — Stub fixture sophistication.** The `StubOllama` parses the bandit hint and returns the top-1 as a tool call. Should it also exercise the prose-only branch (no tool call) for some fraction of synthetic cycles? Default proposal: yes, parameterizable — the audit harness can set `prose_only_fraction` to validate the park path on tool-call-absent outputs. Default 0.0 (always-tool-call) for the headless audit so existing Phase A coverage is preserved.

---

## 11. Intellectual Honesty Notes

- **The bandit becomes a hint, not a decider.** This is a deliberate epistemic downgrade for the bandit and an upgrade for the loop's overall coherence. v1.6.0 had the bandit pretending to be a planner because there was no LLM in the cognate loop; v1.7.0 puts the LLM where it belongs and lets the bandit do what it's actually good at — surfacing recent reward signal as a soft prior. As models get sharper, the hint matters less but still costs nothing to produce.
- **Park/wake is a deliberate retreat from continuous autonomy.** v1.6.0 ran the bandit on every available tick, which made the GUI session technically autonomous (the loop dispatched Phase E's read-mostly defaults whenever no one was looking). v1.7.0 only fires cycles when there's a reason — user input or pending tool output. This trades continuous learning for predictable resource use and removes the substrate for ambient agency until that capability gets a proper safety design.
- **`respond_to_user` was the wrong shape and didn't survive the design review.** The original v5.0 draft proposed it as a twelfth atomic primitive. Kevin's pushback ("why are we adding another atomic primitive") surfaced that a chat response isn't a tool dispatch — it's the LLM's terminal output for the cycle. Wrapping it in tool ceremony added complexity without earning anything, and worse, exposed a bug surface where post-cold-start e-greedy ranking could pick `summarizer` over `respond_to_user` and silently mis-route chat. Removing it kept the primitive count at eleven and put the response where it actually belongs: the prose half of REASON's LLM output.
- **The harness shouldn't be as smart as the LLM** (Kevin, D-20260425). Test infrastructure validates plumbing — the dispatch surface, the parser, the bandit, the persistence — but does not try to replace the model's judgment. Phase F's `StubOllama` reads the bandit hint and emits the top-1 as a deterministic tool call, exercising the LLM-REASON code path without claiming the stub *is* the reasoning surface. As models improve, the harness stays stable; the LLM does the harder work, and the test suite ages well rather than ossifying around model-specific behaviors.
- **Tool-call parser is a deliberate copy, not a refactor.** `core/loop.py` is No-Write; its `_parse_tool_call` is effectively frozen. `core/tool_call_parser.py` is the Phase F+ canonical version. They cannot drift because one of them cannot change. Phase G+ may unify the two if No-Write lifts.
- **Conversation history reach uses one knob across modes.** `reason_history_turns` works the same for chat-driven and (eventual) ambient-driven LLM-REASON. Tuning it for one tunes it for both, which is the right coupling — the LLM's context window doesn't care which signal class triggered the cycle.
- **`_get_loop_ref` retirement closes Phase E's plumbing thread.** Tool-context generalizes the `conn_factory` pattern. After Phase F, the only remaining shim install path is the legacy `CoreLoop` boot, which the GUI no longer constructs.
- **No-Write on `loop.py` remains the cornerstone.** Phase F removes one call site to `lx_loop_shim.install` from `core/core.py` and removes the `from core.loop import CoreLoop` import from `gui/main_window.py`. Neither edit touches `loop.py`. The acceptance gate re-checks `git diff` on it.
- **Multi-tool-call output and skip-INTEGRATE/OBSERVE shortcuts are deferred deliberately.** Both are natural Phase G+ extensions (Kevin: "i do think i will incorportate a way for the model to skip integrate or observe directly later"). Phase F runs every cycle as a full four-step rotation with single tool calls, which is the simplest correct shape and the right baseline for whatever optimizations come next.

---

*Plan Version: 5.1.0 (D-20260425, draft pending review — supersedes the v5.0 draft that included `respond_to_user`)*
*Prepared after Phase E landing (v1.6.0). Await explicit approval before execution.*
