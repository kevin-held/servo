# Glossary

**Version:** 1.0
**Last Updated:** 2026-04-17
**Status:** Canonical

Quick definitions of every concept in the Servo codebase. Alphabetical. For Servo-specific phrasing and conventions, see `lexicon.md`. For the story of why things are the way they are, see `history.md`. For decision rationale, see `decisions.md`.

## A

**Active role** — The role currently shaping Servo's voice. Held in `_active_role` on the Cortex; `""` is treated as `servo`.

**Auto-continue** — When the LLM hits a token budget mid-response, the Cortex automatically continues generation up to `MAX_AUTO_CONTINUES` times.

## C

**ChromaDB** — Vector database used for episodic memory and semantic search over past experiences. Lives under `state/`.

**Codex** — The on-disk canonical truth (`codex/` directory). Authoritative; survives restarts.

**Continuous goal** — A scheduled, recurring goal in `goals.json`. Distinct from a one-shot goal.

**Cortex** — The ephemeral runtime in `core/loop.py`. The QThread-based execution engine.

**Cycle** — One pass through the 6-step loop (PERCEIVE → CONTEXTUALIZE → REASON → ACT → INTEGRATE → OBSERVE).

## E

**Election** — The deterministic process of choosing which role to activate this cycle. Lowest priority wins; ties broken by longest overdue.

## G

**Goals.json** — The continuous-goal schedule. Each entry has `type`, `description`, `schedule_minutes`, `last_run`.

**Grace cycle** — A cycle in which the Cortex stays in the elected role's voice even with nothing new due. Capped.

## I

**Identity** — The invariant baseline persona defined by `codex/persona_core.md`. Distinct from any role overlay.

**INTEGRATE** — Step 5 of the loop. Reconciles action results into memory and state.

## L

**Loop** — The 6-step cognitive cycle that the Cortex runs continuously.

## M

**Manifest** — `codex/manifest.json`. The canonical machine-readable description of the system layout, version, and layer mapping.

**Memory manager** — A tool that stabilizes context for the Analyst by summarizing critical logic before evaluation.

## O

**OBSERVE** — Step 6 of the loop. Quiet stance between cycles. Replaces the legacy term IDLE.

**Ollama client** — `core/ollama_client.py`. Thin resilient wrapper around the Ollama HTTP API. Supports cancellable streaming.

**Overlay** — A `voice_overlay / format_bias / risk_tolerance` triple attached to a role. Modulates tone only.

## P

**PERCEIVE** — Step 1 of the loop. Scans the environment for new data.

**Persona** — The identity layer: invariant identity (`persona_core.md`) plus situational overlays (`roles.json`).

**Persona core** — `codex/persona_core.md`. The invariant identity document, injected verbatim into every system prompt.

**Priority (role)** — Integer; lower = elected first. `servo` has priority 99 (never auto-elected).

## R

**REASON** — Step 3 of the loop. LLM call that decides the next action.

**Role** — A named overlay with an optional continuous task. Roles have priority, schedule, enabled flag.

**Role manager** — `tools/role_manager.py`. The tool that enables/disables roles and syncs goal state.

## S

**Sandbox** — The set of directories Servo is allowed to write without asking.

**Schedulable** — A role is schedulable iff it is not in the deny-list, has a non-empty task, and has positive `schedule_minutes`.

**SQLite (state.db)** — Structured persistent state, WAL mode. Holds conversation history and key-value system state.

**System prompt** — The full prompt-head sent to the LLM each turn. Composed of identity block + overlay block + system environment.

## T

**Tool registry** — `core/tool_registry.py`. Auto-discovers Python files in `tools/` and exposes their `execute()` functions to the agent.

## V

**Voice overlay** — The one-line tone descriptor on each role. Appended to the system prompt as `Voice:`.

## W

**WAL** — Write-Ahead Logging. The SQLite mode used for `state.db`.

**Workspace** — `workspace/<model>/`. The agent-writable scratch tree, scoped per model. Replaces the legacy `<model>_notes/` folders.

---
*Maintained by The Scholar*
