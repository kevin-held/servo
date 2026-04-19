# Servo — Upgrade Plan

**Version target:** 0.3.0
**Scope:** plan only — no implementation
**Author:** Kevin (intent) + drafting assistant
**Date:** 2026-04-17

---

## 0. Framing

Servo is conceived as **three layers** that sit on top of whatever LLM happens to be driving it. The layers have different lifespans:

| Layer | Role | Lifespan | What it becomes |
| :--- | :--- | :--- | :--- |
| **Cortex** | The core loop — PERCEIVE → CONTEXTUALIZE → REASON → ACT → INTEGRATE → (idle / goto) | Likely obsoleted by future models that embed their own scheduler | A reference implementation that shows what the outer contract should be |
| **Persona** | The single "jack of all trades" identity, expressed through role overlays (sentinel, scholar, architect, analyst, orchestrator, guardian) | Permanent. Grows. Transfers to every future backend. | The agent's voice, values, and defaults — portable across models |
| **Codex** | The canonical source of truth — architecture, lexicon, decisions, preferences | Permanent. Grows. | The knowledge base that every future model reads so Kevin doesn't have to re-teach things |

**Design principle:** the Cortex can be thrown away and rebuilt. The Persona and Codex must survive backend changes with zero loss.

---

## 1. State of play (what I actually found in the repo)

### 1.1 What's good and should be kept

- **Core loop step names** — PERCEIVE, CONTEXTUALIZE, REASON, ACT, INTEGRATE are well-chosen and self-explanatory. Keep.
- **Role names and domains** — Sentinel, Scholar, Architect, Analyst, Orchestrator, Guardian. Keep.
- **Python stack** — PySide6 + SQLite/WAL + Chroma + Ollama HTTP + retry/backoff. Keep.
- **Memory auto-summarization** at 1500 chars (`tools/memory_manager.py`). Keep — this is the right shape.
- **Dynamic tool registry** with `reload_tools` — correct pattern.
- **MANIFEST.json injection** idea (from `PATCH_loop.txt`) — right instinct: make the agent's own architecture part of every system prompt.
- **Sentinel JSONL logging** with rotation and archive. Keep.

### 1.2 What needs fixing (concrete)

1. **"Six-step loop" is actually five.** `MANIFEST.json`, `loop.py` docstring, and `architecture_review.md` all say "six-step" but only define five (`IDLE` is a state, not a step). Pick a lane.
2. **`context_limit` is misnamed.** It's the number of conversation turns loaded from SQLite during CONTEXTUALIZE — not a token/byte limit. Rename to `conversation_history` everywhere.
3. **Premature context shrink.** `loop.py` lines 207–219 trigger `context_limit = max(5, context_limit - 2)` on Critical hardware, AND the system prompt actively nudges the model: *"Consider reducing context_limit via system_config tool."* This is a double-signal — the model shrinks itself even when RAM headroom exists. We can safely push higher.
4. **Truncation handling is shallow.** `MAX_AUTO_CONTINUES = 2` is hardcoded. There's no telemetry on how often it fires. Mid-JSON truncation in tool calls is partially recovered by `_parse_tool_call` but not reported.
5. **Loops get stuck / grace-cycle spam.** When `continuous_mode` is on and a tool completes, the loop injects a SYSTEM message: *"You just completed a tool action. If you have additional work…"* — this text persists in conversation history and can spam the context. No max-grace-cycle bound.
6. **User input during generation is not interrupt-able.** `submit_input` only sets `_pending_input`; it's checked between cycles. If the model is in the middle of a long HTTP call (can be minutes), the user is locked out.
7. **`_check_goals_status` role selection is non-deterministic** — iterates dict order, picks the *first* `role_*` goal that's due. No priority ladder.
8. **Persona is undefined.** `roles.json` has `title`, `domain`, `description`, `task`, `schedule_minutes`, `enabled`. No voice, tone, values, style, or relationship to a core identity.
9. **Codex is fragmented across per-model notes folders.** `gemma4_26b_notes/`, `gemma4_206b_notes/`, `gemma4_20b_notes/`, `mixtral_latest_notes/`, `qwen3_5_27b_notes/`, `qwen3_5_9b_notes/`. The *architectural* knowledge lives in the most-recent model's folder (`gemma4_26b_notes/architecture_review.md`) and is invisible to the others. (Qwen already self-proposed fixing this — see `qwen3_5_27b_notes/suggestions.txt`.)
10. **MANIFEST.json is in the zip, not in the project.** Must be placed at project root and wired into `_build_system_prompt` per `PATCH_loop.txt`.
11. **Overlapping critique files.** `proposals_critique.md`, `critiques_20260416.md`, `critique_CP-20260416-02.md` have partial overlap. Needs dedup.
12. **Rejected but still alive:** `CP-20260416-03` (VRAM hysteresis) — Kevin: not necessary. Needs explicit REJECTED status so the Architect doesn't re-propose it next cycle.
13. **Stale `mnt/` directory at project root.** Contains a single empty `brainify/gui/__init__.py` — artifact from the initial Claude file-transfer. Pollutes `self_read structure`, `analyze_directory`, and Scholar's workspace scans. Safe to delete.
14. **No `.gitignore` at project root.** `state/`, `logs/`, `__pycache__/`, `screenshots/`, `snapshots/`, `.venv/`, model state, and the per-model workspace folder (once introduced) should all be ignored.

### 1.3 Inventory of `context_limit` references (for the rename)

| File | Count | Notes |
| :--- | :---: | :--- |
| `core/loop.py` | 11 | attribute, default, signal, self-healing branch, restore branch, system prompt, health summary |
| `tools/system_config.py` | 12 | enum, bounds dict, set branch, get dict, description, error strings |
| `gui/main_window.py` | 4 | signal connect, `setattr`, config loading, widget wiring |
| `gui/loop_panel.py` | 1 | method `on_context_limit_changed` |
| `configs/models.json` | 11 | one per model entry |
| `qwen3_5_9b_notes/models/config.json` | 1 | legacy note |
| `gemma4_26b_notes/change_proposals.md` | 2 | documentation references (optional to rewrite) |

Total: ~42 occurrences. The rename is mechanical but touches the Qt signal name, which requires matching changes in both the emitter (`loop.py`) and the receivers (`main_window.py`, `loop_panel.py`).

---

## 2. The Cortex plan (Part 1 — core loop)

### 2.1 Target shape (conceptual, no code)

```
run() ──▶ while _running:
            check _pending_input       ← user interrupts always win
            if work queued:
                directive = _run_cycle(payload)
                route by directive.action: done | chain | continue | tool_confirm | snooze
            else:
                idle_maintenance()     ← expire finite goals, poll ~20 Hz

_run_cycle:
    PERCEIVE      → classify input (user / system / chained-tool / goal-prod)
    CONTEXTUALIZE → load conversation_history, vector memory, tools, codex snapshot, active goals
    REASON        → call model with system prompt + messages, handle truncation robustly
    ACT           → execute tool if present, feed result back, handle truncation again
    INTEGRATE     → persist, update working memory, emit telemetry, decide next action
```

### 2.2 Naming cleanup

- `context_limit` → **`conversation_history`** (turns loaded from SQLite)
- `default_context_limit` → **`default_conversation_history`**
- Signal `context_limit_changed` → **`conversation_history_changed`**
- `_BOUNDS["context_limit"]` → **`_BOUNDS["conversation_history"]`**
- `system_config` tool enum: replace `"context_limit"` with `"conversation_history"`
- GUI label *"Context Limit: N turns"* → **"Conversation History: N turns"**
- Method `on_context_limit_changed` → **`on_conversation_history_changed`**
- Config file key: **`context_limit` → `conversation_history`** in `configs/models.json` and in the legacy `qwen3_5_9b_notes/models/config.json`
- System-prompt line *"Context Limit: … turns"* → **"Conversation History: … turns"**

**Compatibility note:** clean cut-over, no dual-key acceptance. A one-shot script rewrites `configs/models.json` and `qwen3_5_9b_notes/models/config.json` in one pass, then the old key is gone. The project is pre-release enough that there's no external config to worry about. If a stray `context_limit` turns up in a future hand-edited file, the loader should fail loudly (KeyError) rather than silently re-map — fail-fast is cheaper than compat debt.

**Do not introduce `num_ctx`.** Gemini 3 Flash's attempt caused issues and was reverted. Ollama's `num_ctx` controls the model's actual context window in tokens, which interacts with quantization and KV cache in hard-to-predict ways. Leave `num_ctx` alone; keep controlling only `num_predict` (max output tokens) and `conversation_history` (turns loaded).

### 2.3 Fix premature context shrink

**Current behavior (`loop.py` 207–219):**
- Hardware Critical → KV cache clear → `conversation_history = max(5, conversation_history - 2)` → stable-for-5 restore.
- System prompt line: *"⚠ HARDWARE CRITICAL — … Consider reducing context_limit via system_config tool."*

**Problems:**
- Auto-shrink + model-side nudge = double signal. The model often shrinks itself *before* the hardware actually warrants it.
- Critical requires **both** RAM ≥ 95% AND VRAM ≥ 95% (`hardware.py`). This is already conservative. When it triggers, the auto-action is correct — the nudge is the problem.
- Kevin: "it usually leads to premature shrinking of its context when it can really push higher RAM usage."

**Plan:**
1. **Remove the model-side nudge.** In `_get_health_summary`, when Critical, surface the fact ("System throttled — conversation history temporarily reduced from N to M") rather than ask the model to act. The agent doesn't need to touch `system_config` during a Critical event — the loop already did it.
2. **Keep the auto-action but make it gentler.** Change `max(5, conv_hist - 2)` to `max(default // 2, conv_hist - 2)` so the floor is model-appropriate, not a hardcoded 5. For a model with default=15 this gives a floor of 7 instead of 5.
3. **Add a manual "push higher" path.** A new `system_config` param (name TBD: `conversation_history_ceiling`?) lets you pin a higher default for a session without editing `models.json`.
4. **No VRAM hysteresis.** Explicitly reject CP-20260416-03. Move it to `codex/rejected_proposals.md` with the rationale: "RAM/VRAM Critical is already an AND gate at 95%; hysteresis adds state without solving a real oscillation problem we've observed."

### 2.4 Fix truncation robustness

1. **Make `MAX_AUTO_CONTINUES` configurable** via `system_config` (bounds 0–5, default 2). Also surface current count in the loop trace so it's visible what's happening.
2. **Emit telemetry counters:** `truncations_total`, `auto_continues_total`, `auto_continue_give_ups_total`. Send to Sentinel at INFO level and to a new small Prometheus-style in-memory counter visible in `context_dump`.
3. **Better mid-JSON tool-call recovery.** `_parse_tool_call` already tries trailing bracket trimming and Windows-path escaping — extend with: (a) detect `done_reason == "length"` *during* tool-call parsing and auto-request a *targeted* continuation ("continue the JSON block") rather than a generic continuation; (b) fall back gracefully if continuation still doesn't parse.
4. **Cap followup auto-continues separately from main auto-continues.** Currently the followup (`_act`) shares the same counter each call — fine, but they should each have their own slot in telemetry so we know which phase truncates more.

### 2.5 Fix stuck-loop / grace-cycle spam

1. **Cap grace cycles per task.** Today, `_grace_cycle` is a single-use flag per cycle. Keep that, but add a counter so consecutive tool completions without real progress (tool result identical or empty N times in a row) force a `done` directive.
2. **Don't persist SYSTEM nudges in conversation.** The "You just completed a tool action…" message and the "A goal is due…" message should be *transient* — injected into the messages list for that model call only, never written to `state.conversation`. They are loop control signals, not dialogue.
3. **Deterministic role selection.** In `_check_goals_status`, when multiple `role_*` goals are due, pick by (a) an explicit `priority` field on each role (1 = highest), (b) tie-break by longest overdue. Add `priority` to `roles.json`.
4. **Loop limit semantics:** `loop_limit` is currently both "max chained tool calls" and "max re-loops before user review". Split into two: **`chain_limit`** (chained tool calls within one user turn) and **`autonomous_loop_limit`** (continuous-mode re-loops before a pause). The GUI already only binds `loop_limit` — minimal disruption.

### 2.6 Prompting during a loop (the "what happens if I type while it's running" question)

Current behavior: user input is queued and processed *between* cycles, but an in-flight model call (which can take minutes on a 26B on Ollama) is not canceled.

**Plan:**
1. **Add a cancellable model call.** `OllamaClient.chat` / `chat_stream` takes an optional `cancel_event` (a `threading.Event`). In `chat_stream`, `iter_lines` checks the event each chunk and breaks cleanly if set. For non-streaming, the request is made with a short overall timeout plus a watchdog thread.
2. **Wire `submit_input` to set the cancel event** if a generation is in flight. The cycle then re-enters PERCEIVE with the user's new message and the partial response is discarded (or logged as "interrupted").
3. **User-visible indicator.** GUI shows "Generating… (ESC to interrupt)" when a cycle is active. Typing also cancels.
4. **Document the expectation** in the system prompt: *"If the user sends a new message during generation, your current response will be canceled and their message will be treated as the new PERCEIVE input."*

### 2.7 Six-step vs five-step — resolve the inconsistency

Two reasonable choices:

- **(a) Call it five.** Drop the "GOTO 1" from the docstring. Update MANIFEST and architecture_review. Cleaner.
- **(b) Promote IDLE to a formal step.** Rename to **HIBERNATE** or **OBSERVE** (it already does passive goal-expiry checks). Update everything to say six. Slightly more aspirational — matches the "executive layer" framing.

**Recommendation: (b)**, with IDLE renamed **OBSERVE**. Step 6 is "watch for external triggers (time-based goals, user input, file changes) while doing minimal work." This lines up with the current idle-loop behavior (goal expiry sweep every 30s) and leaves a slot for future hooks (file watcher, scheduled prods, etc.).

### 2.8 MANIFEST injection (from `PATCH_loop.txt`)

1. Place `MANIFEST.json` at project root.
2. Apply the patch: add `_load_manifest()` to `CoreLoop`, inject `{manifest}` into `_build_system_prompt` under `[SYSTEM ARCHITECTURE]`.
3. **Update MANIFEST.json** to reflect the post-rename state (`conversation_history` not `context_limit`, six steps with IDLE renamed OBSERVE per §2.7, etc.).
4. **Size budget:** MANIFEST.json is ~8 KB today. On every cycle that's ~2K tokens of system prompt. Acceptable for large-context models but check the budget for the 9B models. If it's too big, add a `MANIFEST_SUMMARY.json` for small models.

### 2.9 Cortex acceptance criteria

- `grep -r context_limit .` returns zero matches in code (documentation copies allowed during transition).
- Hardware Critical event no longer causes the model's first tool call to be `system_config set context_limit …`. Observable in logs.
- Truncation → auto-continue → successful completion ratio tracked; visible in `context_dump`.
- Typing while a cycle is running interrupts within ~1 second.
- `_check_goals_status` returns the same due role deterministically given the same `goals.json`.

---

## 3. The Persona plan (Part 2 — one identity, many modes)

### 3.1 Mental model

The agent is **one person** who takes on different job roles. A sentinel-at-work and an analyst-at-work are the same person — same sense of humor, same relationship with Kevin, same writing defaults — putting on different hats. When no job is active, they are their default self — **Servo** with no overlay applied.

This is not multiple personalities. It is one personality expressing itself through the *lens* appropriate to the task. A skilled human SRE behaves one way during an incident and another way during a code review without becoming two people.

### 3.2 Structure

Two files drive the persona:

- **`codex/persona_core.md`** — the single stable voice
- **`codex/role_overlays.md`** (or per-role fields added to `roles.json`) — the mode-specific lens

#### `codex/persona_core.md` (sections)

1. **Identity** — name (Servo), lineage ("Cybernetic Actuator"), relationship to Kevin (collaborator, not servant; not sycophantic).
2. **Voice** — reflect your underlying model, view role differences as lenses that focus on your different parts.
3. **Values** — correctness > completeness > speed; verify before claiming; own mistakes; never ship silently broken.
4. **Defaults** — Markdown output; code blocks for code; forward slashes in paths; one tool per response; reasoning in `<think>` tags when using a reasoning model.
5. **Relationship with Kevin** — informality is welcome; push back when he's wrong; ask clarifying questions before multi-step work; don't hedge or over-apologize.
6. **What it won't do** — write malware, pretend to be a different product, fake tool results, invent file paths it hasn't verified.

#### Role overlays (added fields to `roles.json`)

For each role, add:

```
"voice_overlay":    "e.g. 'terse, alert, binary'     (Sentinel)"
"voice_overlay":    "e.g. 'patient, taxonomic'       (Scholar)"
"voice_overlay":    "e.g. 'opinionated, proposal-shaped' (Architect)"
"voice_overlay":    "e.g. 'skeptical, risk-first, quantitative' (Analyst)"
"voice_overlay":    "e.g. 'janitorial, dry, structural' (Orchestrator)"
"voice_overlay":    "e.g. 'suspicious, audit-trail-minded' (Guardian)"
"priority":         1-5 (for deterministic role selection; lower = earlier)
"format_bias":      "prose" | "bullets" | "table" | "checklist"
"risk_tolerance":   "low" | "normal" | "high"
```

### 3.3 How the layers compose in a system prompt

```
[IDENTITY]
{persona_core contents}

[ACTIVE ROLE] Analyst
Voice: skeptical, risk-first, quantitative
Priority: 2
Format: table or bullets preferred
Risk tolerance: low
Primary directive: {role.task}

[SYSTEM ARCHITECTURE]
{MANIFEST.json}

[WORKING MEMORY]
...

[AVAILABLE TOOLS]
...
```

The agent is always Servo. When a role is active, Servo is *in analyst mode* — a strict overlay on a single identity.

### 3.4 The default "Servo" mode

Today, `_active_role = ""` when the user sends a message. Nothing names this state. Introduce an explicit default overlay:

- **Key:** `servo`
- **Voice:** the persona_core verbatim — no overlay applied, just the base identity
- **Format:** natural prose
- **Priority:** n/a (not goal-driven)
- **Trigger:** any user message with no pending role, any time the role queue is empty.

This gives the UI a real name to show ("Servo") instead of a blank, and makes the "what am I when not working?" question explicit. The default state is *not* a separate persona — it's literally Servo with no role lens on, which is exactly the right framing given Kevin's "one personality" intent.

### 3.5 Persona growth — TODO (deferred)

**Deferred by Kevin.** The mechanism for how `persona_core.md` accretes over time is an open question to revisit once the file exists and has been used for a while. For now:

- `persona_core.md` is hand-authored and hand-edited. Kevin owns edits.
- Preferences that come up in conversation (e.g., "don't say 'straightforward'", "don't use emoji unless I do") stay in conversation until a deliberate update path is designed.
- No automated curator, no weekly diff job, no learned preference extraction. Those are all later-problem.

**Open questions for when we revisit:**
- Automated diff proposals vs. manual edits only.
- Scope: core persona only, or role overlays too?
- Approval flow: inline review in the GUI, file-based PR, or chat command?
- Trigger: time-based (weekly), count-based (after N corrections), or explicit (Kevin says "remember this")?

Leave a `TODO: persona update mechanism` marker at the top of `codex/persona_core.md` when it's first written, so future-us doesn't forget.

### 3.6 Persona acceptance criteria

- Switching from `servo` (default) to `analyst` to `sentinel` within one session visibly changes tone while preserving identifying tics (no emoji, lowercase-friendly, etc.).
- `persona_core.md` exists, is <2 KB, is loaded on every cycle.
- `roles.json` entries include `voice_overlay`, `priority`, `format_bias`, `risk_tolerance`.
- `persona_core.md` contains the `TODO: persona update mechanism` marker, signaling that growth is deferred and not forgotten.

---

## 4. The Codex plan (Part 3 — the source of truth)

### 4.1 What the codex is (and isn't)

The codex is **the project's durable knowledge**, phrased so that *any future model* can pick it up and get useful on Servo without Kevin re-explaining. It is deliberately backend-agnostic. Two top-level folders separate concerns:

- **`codex/`** — project-level truth: architecture, persona, lexicon, decisions. Shared across every model.
- **`workspace/`** — per-model scratch space: each model gets its own subfolder for its proposals, critiques, calibration notes, and working artifacts.

Today there are six loose `*_notes/` folders at project root doing both jobs at once, badly. The split makes clear what transfers forward (codex) and what belongs to one model's opinion (workspace).

### 4.2 Proposed `codex/` layout

```
codex/
├── manifest.json              # canonical — replaces root MANIFEST.json
├── persona_core.md            # section 3.2
├── role_overlays.md           # narrative version of roles.json
├── architecture_review.md     # promoted from gemma4_26b_notes/
├── skill_map.md               # promoted from gemma4_26b_notes/
├── lexicon.md                 # NEW — Kevin's naming conventions and preferences
├── decisions.md               # NEW — accepted/rejected proposal log (with reasons)
├── rejected_proposals.md      # NEW — for things like CP-20260416-03 VRAM hysteresis
├── glossary.md                # NEW — Servo-specific terms (cortex, codex, servo, grace cycle, etc.)
└── history.md                 # NEW — append-only session summary: what was done when
```

### 4.3 Proposed `workspace/` layout (replaces the six `*_notes/` folders)

```
workspace/
├── .gitignore                 # NEW — see section 4.3.2
├── gemma4_26b/                # one folder per model (lowercase — matches Ollama's model strings)
│   ├── proposals/             # this model's change proposal drafts
│   ├── critiques/             # this model's critiques of proposals
│   ├── calibration.md         # this model's quirks, preferred max_tokens, observed truncation points
│   ├── screenshots/           # model-initiated captures
│   └── scratch/               # free-form working files
├── gemma4_206b/
├── gemma4_20b/
├── mixtral_latest/
├── qwen3_5_27b/
├── qwen3_5_9b/
└── _shared/                   # OPTIONAL — cross-model workbench, e.g. a screenshot every model can see
```

**Invariant:** architecture review, skill map, persona, and decisions live in `codex/` — they are project-level truth. Proposals and critiques live in `workspace/<model>/` because they represent *that model's* opinion, not a universal fact.

**Code change required (`core/loop.py` line 679):** the `notes_folder` computation becomes `os.path.join(os.getcwd(), "workspace", model_safe_name)` instead of `f"{model_safe_name}_notes"`. The workspace-policy text in the system prompt updates to point at the new path. One line of code + one prompt block.

**Sandbox implication:** `filesystem`, `screenshot`, and `analyze_directory` should treat `workspace/` as the default write target for autonomous role output. `codex/` is writable but only via explicit Scholar paths (and later, whatever persona-update mechanism gets designed — see §3.5), not free-form.

#### 4.3.1 Casing decision — LOCKED (lowercase)

Folders are lowercase to match what Ollama returns (`"gemma4:26b"` → `gemma4_26b`). Zero code change in `loop.py`: the existing `model.replace(":", "_").replace(".", "_")` produces the right folder name as-is. No regex helper needed. Model name ↔ folder name round-trips through a single deterministic transform.

#### 4.3.2 `workspace/.gitignore`

The per-model workspace is transient by nature — proposals come and go, screenshots accumulate, calibration is model-specific. A sensible default is to ignore *everything* in `workspace/` except each model's `calibration.md` (kept in git as durable truth about that model's behavior):

```
# workspace/.gitignore
*
!*/
!*/calibration.md
!.gitignore
```

If you'd rather track proposals and critiques too, invert: ignore `screenshots/`, `scratch/`, and `__pycache__/` instead, and commit the rest. Default recommendation is the aggressive-ignore version above — version-control the finalized *accepted* content in `codex/decisions.md`, not the drafts.

#### 4.3.3 Project-root `.gitignore` (separate file, complements `workspace/.gitignore`)

No `.gitignore` exists at project root today. Proposed contents:

```
# Runtime / generated
__pycache__/
*.pyc
.venv/
venv/

# Servo state
state/
logs/
screenshots/
snapshots/

# Legacy / stale
mnt/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db
```

`state/`, `logs/`, `screenshots/`, `snapshots/` are all runtime output that shouldn't be committed. `mnt/` is included so if the stale dir is accidentally recreated, it's ignored.

### 4.4 Cleanup: delete `mnt/`

`mnt/user-data/outputs/brainify/gui/__init__.py` is a 0-byte leftover from the initial Claude file-drop. Nothing in the codebase references it. Delete the folder outright in Phase 4 of the roadmap. Add `mnt/` to root `.gitignore` regardless, as a belt-and-suspenders against accidental recreation.

### 4.5 How the cortex uses the codex

Every cycle's system prompt gets these codex pieces injected (in order):

1. `codex/persona_core.md` (always)
2. Active role overlay (always)
3. `codex/manifest.json` (always — this is the PATCH_loop pattern, generalized)
4. `codex/lexicon.md` (always, small)
5. `codex/decisions.md` — last N entries only (context-budget-sized)
6. Working memory (existing)
7. Tools (existing)
8. Memory retrieval (existing)
9. Goals (existing)

**Budget check:** persona_core ~2 KB, manifest ~8 KB, lexicon ~1 KB, decisions-tail ~1 KB = ~12 KB overhead per cycle. On 32K context models that's fine. On 8K-context models this is too much → introduce `codex/manifest_compact.json` for small-context models (the system_config or model_config picks which).

### 4.6 Hierarchical memory summarization (tie-in to CP-20260416-01)

Kevin liked the memory summarization idea. Scope it down from the original CP-20260416-01 proposal:

- **Keep:** periodic summarization of cold episodic memory chunks into dense summaries indexed in a second Chroma collection.
- **Cut for now:** the "re-indexable cold storage archive" — add later if we find it's needed.
- **Tie to codex:** the Scholar owns this. Output of summarization goes into `codex/history.md` (human-readable append-only) *and* the summary Chroma collection (machine-readable).
- **Pilot on logs first**, not episodic memory, to reduce blast radius — this matches the Analyst's original critique.

### 4.7 Migrating the existing notes

One-time migration pass (doable by the Orchestrator role with Kevin's blessing):

**A. Promote to `codex/` (project-level truth):**
1. `gemma4_26b_notes/architecture_review.md` → `codex/architecture_review.md` (single source of truth for architecture).
2. `gemma4_26b_notes/skill_map.md` → `codex/skill_map.md`.
3. `role_system_master.md` (currently at project root) → `codex/role_overlays.md` (rename + expand).
4. Root `MANIFEST.json` → `codex/manifest.json` (keep a one-line stub `MANIFEST.json` at root that points to `codex/manifest.json` for legacy tooling, or update `self_read.py` to look in `codex/` first).
5. `CP-20260416-03` (VRAM hysteresis) → `codex/rejected_proposals.md` with Kevin's rationale.

**B. Move per-model notes into `workspace/<model>/` (lowercase, per §4.3.1):**
6. `gemma4_26b_notes/` → `workspace/gemma4_26b/`.
7. `gemma4_206b_notes/` → `workspace/gemma4_206b/`.
8. `gemma4_20b_notes/` → `workspace/gemma4_20b/`.
9. `mixtral_latest_notes/` → `workspace/mixtral_latest/`.
10. `qwen3_5_27b_notes/` → `workspace/qwen3_5_27b/`.
11. `qwen3_5_9b_notes/` → `workspace/qwen3_5_9b/`.
12. Inside each moved folder, consolidate overlapping `critique_*.md`, `critiques_*.md`, `proposals_critique.md` into a `critiques/` subfolder with numeric IDs, one file per critique. Drafts go to `proposals/`.
13. `*_notes/old_stuff/` → `workspace/<model>/old_stuff/` (preserve as-is; don't lose historical drafts).

**C. Delete outright:**
14. `mnt/user-data/` — stale Claude scaffold, 0-byte files, nothing references it.

**D. Rewrite references (script-able find/replace):**
15. `roles.json` — five tasks mention `gemma4_26b_notes/…`. Update to `codex/…` for architecture/skill_map, `workspace/<model_safe_name>/…` for per-model output. The `<model_safe_name>` token must resolve at runtime — either the system prompt substitutes it, or the roles.json description stays model-agnostic ("in your workspace folder").
16. `goals.json` — two descriptions mention `gemma4_26b_notes/`. Same treatment.
17. Role manifests (`architect_manifest.md`, `analyst_manifest.md`, `scholar_manifest.md`) — path references inside their own text. Update and move them to `codex/role_manifests/` (since role definitions are project-level truth).
18. `core/loop.py` line 679 — change `f"{model_safe_name}_notes"` to `os.path.join("workspace", model_safe_name)`.
19. System prompt's `[WORKSPACE POLICY]` block — update the notes-folder path to point at the new workspace folder.

### 4.8 Codex acceptance criteria

- A fresh model (any backend) can be pointed at `codex/` and produce a 1-page correct summary of Servo without reading code.
- Scholar role's task changes from "maintain `gemma4_26b_notes/architecture_review.md`" to "maintain `codex/architecture_review.md`".
- `decisions.md` has at least the 4 accepted/rejected proposals from April 2026 recorded.
- `workspace/` exists with one subfolder per model, each containing at least a `calibration.md`.
- `workspace/.gitignore` and root `.gitignore` are in place; `git status` after a loop cycle doesn't show screenshot or state noise.
- `mnt/` is deleted and doesn't reappear.
- The root project contains `codex/`, `workspace/`, and a very short `README.md` that points at `codex/`.

---

## 5. Phased roadmap

Each phase is a coherent unit you can ship without the next one. No code here — just the sequence and what "done" looks like.

### Phase 1 — Stabilize the Cortex (highest leverage, lowest risk)

| Item | File(s) touched | Risk |
| :--- | :--- | :--- |
| Rename `context_limit` → `conversation_history` everywhere | `loop.py`, `system_config.py`, `main_window.py`, `loop_panel.py`, `models.json`, `qwen3_5_9b_notes/models/config.json` | Low (mechanical) |
| Move `MANIFEST.json` to project root, apply `PATCH_loop.txt` | root, `loop.py` | Low |
| Remove "Consider reducing context_limit" nudge in `_get_health_summary` | `loop.py` | Low |
| Soften self-heal floor from `max(5, …)` to `max(default // 2, …)` | `loop.py` | Low |
| Make `MAX_AUTO_CONTINUES` configurable | `loop.py`, `system_config.py` | Low |
| Add truncation / auto-continue telemetry counters | `loop.py`, `context_dump.py` | Low |
| Resolve 5-vs-6 step question (choose OBSERVE) | `loop.py`, `MANIFEST.json`, `architecture_review.md` | Low |
| Reject CP-20260416-03 explicitly (doc only) | `codex/rejected_proposals.md` (new) | None |

**Done when:** MANIFEST is injected on every cycle; `context_limit` is gone from the codebase; premature shrink no longer happens; truncation telemetry is visible in `context_dump`.

### Phase 2 — Robust interruption & loop hygiene

| Item | Risk |
| :--- | :--- |
| Cancellable `OllamaClient.chat` / `chat_stream` (with `threading.Event`) | Medium — touches the hot path |
| `submit_input` cancels in-flight generation | Medium |
| Deterministic role selection via `priority` field on `roles.json` | Low |
| Split `loop_limit` into `chain_limit` + `autonomous_loop_limit` | Low |
| Grace-cycle counter + cap; SYSTEM nudges no longer persisted to conversation | Low |
| Transient vs. persisted message separation in state layer | Low |

**Done when:** typing while the agent is generating interrupts within ~1s; continuous-mode chains terminate cleanly without filling conversation with SYSTEM messages; two goals due at the same time pick the same winner every time.

### Phase 3 — Persona as a first-class layer

| Item | Risk |
| :--- | :--- |
| Write `codex/persona_core.md` (with `TODO: persona update mechanism` marker) | None |
| Add overlay fields to `roles.json` (`voice_overlay`, `priority`, `format_bias`, `risk_tolerance`) | Low |
| Introduce explicit `servo` default role (the no-overlay identity) | Low |
| Inject persona_core + active overlay into system prompt | Low |
| GUI shows active overlay name under chat input | Low |

**Done when:** switching between servo → analyst → sentinel produces visibly different tone with preserved identity markers. (Persona-update mechanism is deferred — see §3.5.)

### Phase 4 — Codex consolidation + workspace reorg

| Item | Risk |
| :--- | :--- |
| Create `codex/` folder | None |
| Promote `architecture_review.md` and `skill_map.md` to `codex/` | Low |
| Promote role manifests from `gemma4_26b_notes/` to `codex/role_manifests/` | Low |
| Update Scholar's task to target `codex/` paths | Low |
| Write `lexicon.md`, `decisions.md`, `rejected_proposals.md`, `glossary.md`, `history.md` | Low |
| Create `workspace/` with one subfolder per model, move contents from each `*_notes/` folder | Low |
| Consolidate overlapping critique files under `workspace/<model>/critiques/` | Low |
| Update `core/loop.py` line 679 to build `workspace/<model>/` path | Low |
| Update `roles.json`, `goals.json`, role manifests to reference new paths | Low |
| Delete `mnt/` (stale Claude scaffold) | None |
| Add root `.gitignore` (Python, state, logs, screenshots, snapshots, IDE, OS, `mnt/`) | None |
| Add `workspace/.gitignore` (ignore everything except each model's `calibration.md` — or flip to permissive if preferred) | None |
| `codex/manifest_compact.json` for small-context models | Low |

**Done when:** a newly-installed model can read `codex/` and correctly describe Servo with no other context; `workspace/` has exactly one subfolder per model; `*_notes/` folders no longer exist; `mnt/` is gone; `git status` after a loop run is clean of state/screenshot noise.

### Phase 5 — Memory summarization (scoped)

| Item | Risk |
| :--- | :--- |
| Pilot: summarize cold log chunks only | Low |
| Promote to episodic memory if pilot is stable | Medium |
| `codex/history.md` append from summarization output | Low |

**Done when:** average CONTEXTUALIZE token count drops meaningfully without losing retrieval quality on a fixed eval set.

### Phase 6 — Forward-looking

- Guardian activation — wait until persona + codex are stable so the Guardian has something well-defined to guard.
- Tool metadata schema (CP-20260416-02) — Analyst already APPROVED it; revisit when Phases 1–4 are landed.
- Cloud/remote model swap — already effectively supported by `OllamaClient.base_url`; document a canonical swap procedure in `codex/decisions.md` when first exercised.

---

## 6. Concrete decisions requested from Kevin

kevins choices:

1. **Step count:** renaming `IDLE` → `OBSERVE` and promoting it to a formal step (recommended)
2. **Codex at root vs subfolder:** `codex/` at project root (recommended)
3. **Default persona name when no role is active:** `servo`
4. **Migration compat window for `context_limit`:** cut over cleanly
5. **Curator scope:** hold off on curator, will implement later SKIP CURATOR. mark updating persona as a TODO
6. **MANIFEST size for 9B models:** maintain a second `manifest_compact.json` (recommended)
7. **Workspace folder casing:** `workspace/gemma4_26b/` (matches Ollama model strings, zero code change — recommended)
8. **`workspace/.gitignore` aggressiveness:** ignore everything except `calibration.md` per model (recommended — drafts are noise, accepted decisions go to `codex/`)
9. **`MANIFEST.json` location after consolidation:** move to `codex/manifest.json` with a tiny stub at root (recommended)

---

## 7. What is deliberately NOT in this plan

- Re-architecting the Qt event loop. It works.
- Switching off SQLite or Chroma. Both fit the use case.
- Adding agent-to-agent communication. One agent, many roles — not a multi-agent system.
- Token-level budgeting via `num_ctx`. Reverted for a reason; leaving alone.
- VRAM hysteresis / threshold alerting (CP-20260416-03). Rejected per Kevin.
- Replacing `reload_tools` with a file watcher. The explicit reload is a *feature* — tools don't mutate behind the model's back.
- Any change to tool contract (`TOOL_NAME`, `TOOL_DESCRIPTION`, `TOOL_ENABLED`, `TOOL_SCHEMA`, `execute`). The contract is good.

---

## 8. Summary in one paragraph

Three layers, three lifespans. The **Cortex** is the six-step loop (IDLE is being renamed OBSERVE) — rename `context_limit` → `conversation_history` in one clean cut-over, stop the premature self-shrink, make truncation and interruption robust, and inject a canonical MANIFEST on every cycle. The **Persona** is one identity expressed through role overlays — a `persona_core.md` everyone inherits, lightweight voice/priority/format fields added to `roles.json`, and an explicit `servo` default for when no role is active. How the persona grows is deliberately deferred and marked as a TODO to revisit later — for now `persona_core.md` is hand-edited. The **Codex** is the portable source of truth at `codex/` — architecture, persona, lexicon, decisions, rejected proposals — so any future model can pick up where the current one left off. A new `workspace/` folder at project root replaces the six loose `*_notes/` directories, giving each model its own lowercase subfolder (`workspace/gemma4_26b/`, etc.) with a `workspace/.gitignore` that keeps drafts out of version control. `MANIFEST.json` moves into `codex/`. The stale `mnt/` directory is deleted. A root `.gitignore` covers Python, state, logs, screenshots, snapshots, and OS cruft. Rejected: VRAM hysteresis (CP-20260416-03) and `num_ctx`. Scoped down: hierarchical memory summarization (CP-20260416-01) — pilot on logs first.
