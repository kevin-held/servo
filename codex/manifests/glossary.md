# Glossary

**Version:** 1.0
**Last Updated:** 2026-04-17
**Status:** Canonical

Quick definitions of every concept in the Servo codebase. Alphabetical. For Servo-specific phrasing and conventions, see `lexicon.md`. For the story of why things are the way they are, see `history.md`. For decision rationale, see `decisions.md`.

## A

**Auto-continue** — When the LLM hits a token budget mid-response, the Cortex automatically continues generation up to `MAX_AUTO_CONTINUES` times.

## B

**Block Argument** — An optional parameter (e.g., `block=1`) used with compatible tools to retrieve subsequent chunks of data after a 16,000 character truncation.

## C

**ChromaDB** — Vector database used for episodic memory and semantic search over past experiences. Lives under `state/`.

**Codex** — The on-disk canonical truth (`codex/` directory). Authoritative; survives restarts.

**Cortex** — The ephemeral runtime in `core/loop.py`. The QThread-based execution engine.

**Cognitive Load** — [Experimental] The complexity of the current set of instructions and data relative to the model's context window. High cognitive load requires pruning or summarizing.

**Cycle** — One pass through the 6-step loop (PERCEIVE → CONTEXTUALIZE → REASON → ACT → INTEGRATE → OBSERVE).

## D

**Demarcation** — The `--- SYSTEM RESTART ---` banner in logs signaling the biological passage of time between user sessions.

**Dream Pad** — A divergent exploratory scratchpad (e.g., `workspace/<model>/dream_pad/`) for architectural simulation and hypothesis testing.

**Dream Pad Archive** — The destination for completed dreams (`workspace/<model>/dream_pad_archive/`) after a Final Synthesis is created.

**Dream Sequence** — A focused session of non-linear exploration governed by a `dream_manifest.md`.

## F

**Formal Change Process** — The rigid Self-Development Lifecycle (SDL) for structural changes. Consists of:
    1. **Change Proposal (CP)**: High-level solution draft [Gated]. 
    2. **Implementation Plan (IP)**: Detailed technical design [Gated]. 
    3. **Execution**: Application of changes via `task.md`. 
    4. **Verification (VR)**: Formal pass/fail testing. 
    5. **Integration Phase**: Permanent record-keeping and archival.

**Final Synthesis** — The convergence event that ends a Dream Sequence by summarizing findings into a `final_synthesis.md`.


## I

**Identity** — The invariant baseline persona defined by `codex/manifests/persona_core.md`. Distinct from any role overlay.

**INTEGRATE** — Step 5 of the core loop. Reconciles action results into memory and state. auto summarizes older conversation terms.

**Integration Phase** — The final, distinct phase of the SDL. Involves updating `integrated_proposals.md`, archiving CP/IP documents to `old_stuff/`, prepending to `history.md`, and appending to `decisions.md`.

## L

**Loop** — The 6-step cognitive cycle that the Cortex runs continuously.

## M

**Manifest** — `codex/manifest.json`. The canonical machine-readable description of the system layout, version, and layer mapping.

**Memory manager** — one of your tools.

## O

**OBSERVE** — Step 6 of the loop. Quiet stance between cycles. Replaces the legacy term IDLE.

**Ollama client** — `core/ollama_client.py`. Thin resilient wrapper around the Ollama HTTP API. Supports cancellable streaming.

**Oscillating Temperature** — A standard procedure during Dream Sequences to encourage divergent reasoning; requires further research for general loop use.

**Overlay** — legacy term for role designation

## P

**PERCEIVE** — Step 1 of the loop. Scans the environment for new data.

**Persona** — The identity layer: invariant identity (`persona_core.md`) 

**Persona core** — `codex/manifests/persona_core.md`. The invariant identity document, injected verbatim into every system prompt.

**Potential Improvement** — A non-critical enhancement identified during reasoning; triggers Level 3 agency.

**Potential Problem** — A suspected but unverified issue identified during reasoning; triggers Level 3 agency.

**Priority (role)** — Integer; lower = elected first. `servo` has priority 99 (never auto-elected).

## R

**REASON** — Step 3 of the loop. LLM call that decides the next action.

**Role** — a legacy term for persona designation, could come back in the future...

## S

**Sandbox** — The set of directories Servo is allowed to write without asking.

**SQLite (state.db)** — Structured persistent state, WAL mode. Holds conversation history and key-value system state.

**Synthesis Anchor** — [Experimental] A critical piece of truth within the Codex used to resolve contradictions between memory hits and model weights.

**System prompt** — The full prompt-head sent to the LLM each turn. Composed of identity block + overlay block + system environment.

## T

**Tool registry** — `core/tool_registry.py`. Auto-discoverer for the `tools/` directory.

**Truncation Awareness** — The engineering standard for handling tool outputs exceeding 16,000 characters (e.g., using `Block Argument`).

## V

**Verified Problem** — An issue acknowledged by the user or verified via testing; triggers Level 2 reflex to start the SDL process.


## W

**WAL** — Write-Ahead Logging. The SQLite mode used for `state.db`.

**Workspace** — `workspace/<model>/`. The agent-writable scratch tree, scoped per model. Replaces the legacy /model_notes/ folders.

---
*Maintained by The Scholar*
