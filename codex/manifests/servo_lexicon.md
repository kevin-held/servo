# Servo Lexicon — Implementation & Nuance

**Version:** 2.0
**Status:** Authoritative (Overrides General Lexicon)

This document defines the physical implementation of agentic concepts within the Servo codebase. **Typically, definitions found here override generalized definitions in `lexicon.md`.**

## 1. Core Runtime (The Cortex)

**Cortex**
*   The live, in-memory execution engine found in `core/loop.py`. It executes the canonical 6-step loop continuously.

**Step 1: PERCEIVE (The Sensory Gate)**
*   **Nuance:** Captures raw text, image attachments, and timestamps. It also intercepts "hijacked" payloads like auto-chains (chained tool calls) and user-pasted tool JSON, bypassing reasoning when a direct action is already queued.

**Step 2: CONTEXTUALIZE (Memory Retrieval)**
*   **Nuance:** Pulls the active environment. It retrieves conversation history (and recent summaries), performs a semantic similarity search in Episodic Memory (ChromaDB), and loads the current Task Ledger and Tool Registry.

**Step 3: REASON (The Cognitive Engine)**
*   **Nuance:** Synthesizes the system prompt and context into a model query. Includes "Hardware Self-Healing" logic—if VRAM or RAM is critical, the Cortex automatically throttles the `conversation_history` count to protect system stability.

**Step 4: ACT (Physical Execution)**
*   **Nuance:** Translates the model's JSON tool calls into physical code execution. It routes data through the registry, captures external results, and logs both successful completions and error tracebacks.

**Step 5: INTEGRATE (State Persistence)**
*   **Nuance:** The "Learning" phase. It commits turns to the SQLite database and updates Episodic Memory. Crucially, it triggers the `history_compressor` kernel to roll up old turns into dense summaries when the context threshold is met.

**Step 6: OBSERVE (Passive Watch)**
*   **Nuance:** The "rest" state between active cycles. The Cortex monitors for new user input, pending tasks, or external interrupts. It is the steady-state gate that ensures the loop is never truly idle, only waiting.

## 2. Tools & Intelligence

**Atomic Primitives**
*   **Implementation:** `file_read`, `file_write`, `file_list`, `file_manage`.
*   **Nuance:** Deployed in v1.3.0 to replace monolithic "God-Tools." Each primitive is a sharp, single-purpose tool that reduces schema "Tax" and improves model precision by forcing explicit selection.

**Symbolic Mapping**
*   **Implementation:** `map_project`.
*   **Nuance:** Replaces directory crawling with regex-based symbol extraction. Provides a "Technical Capability Map" (classes, methods, functions) rather than a raw content dump.

**Summarizer Kernel**
*   **Implementation:** `tools/summarizer.py`.
*   **Nuance:** Factored out of `log_summarizer` to provide a system-wide condensation engine. Shared by the `history_compressor` and the `ACT` phase to manage context pressure.

## 2. Memory Implementation

**Episodic Memory**
*   **Implementation:** Persisted via `chromadb` in `state/chroma`.
*   **Refinement:** Automatically queried during **CONTEXTUALIZE** using the user's current input vector. Hits are injected as `[EPISODIC MEMORY]` blocks.

**Semantic Memory**
*   **Implementation:** All `.md` and `.json` files within the `codex/` directory (primarily `codex/manifests/`).
*   **Refinement:** Indexed and summarized by the `knowledge_manager` and `summarizer` kernel.

**Working Memory**
*   **Implementation:** The active `context` dictionary in `CoreLoop` and the `working_memory` key/value store in `state.db`.
*   **Nuance:** Reset during a `/reset` command or significantly compressed during the **INTEGRATE** phase.

**The Demarcation (Session Gap)**
*   The `--- SYSTEM RESTART ---` banner injected into the SQLite `conversation` table. It signals to the Cortex that the biological passage of time has occurred between sessions.

## 3. Operational Safety

**The Sandbox**
*   The strict set of directories Servo is allowed to write to without asking:
    *   `workspace/` (Scratchpad for all model files)
    *   `logs/` (System logs)
    *   `state/` (Database and Chroma files)
    *   `codex/` (The root manifest files)
    *   `codex/manifests/` (Authoritative documentation and lifecycle standards)
*   **Nuance:** If you want to modify source code in `core/`, `tools/`, or `gui/` remember to start with the Change Proposal (CP) process as outlined in [Self-Development Lifecycle](self_development.md). 

**Transient Payloads**
*   Any system message marked with `_transient=True`. These are processed by the reasoning engine but are **never saved** to the persistent SQLite history. Used for diagnostics and nudges. consider working memory for tracking useful transient payloads.

**Block Argument**
*   **An optional parameter (e.g., `block=1`) used with compatible tools (like `file_read`, `fetch_url`, or `youtube_transcript`) to retrieve subsequent chunks of data after a 15,000 character truncation.

**Surgical Reading**
*   **Implementation:** `file_read` with `start_line` / `end_line`.
*   **Nuance:** The preferred method for investigating large source files. Avoids "block-blindness" by allowing the agent to target specific logic blocks by line number. Deployed in v1.3.1 to enhance precision.

## 4. Engineering Philosophy

**High Fitness (Naming)**
*   **Philosophy:** A variable or function name is "high fitness" if it is the shortest possible string that eliminates the need for an explanatory comment. High fitness is the default state for atomic primitives.

**Low Fitness (Naming)**
*   **Philosophy:** A name has "low fitness" if it requires a comment to explain what it does. This constitutes a technical debt regression.

## 5. Shorthand & Identifiers

*   **CP-YYYYMMDD-NN**: A Change Proposal identifier. (See [process_cp.md](process_cp.md))
*   **IP-YYYYMMDD-NN**: An Implementation Plan identifier. (See [process_ip.md](process_ip.md))
*   **VR-YYYYMMDD-NN**: A Verification Report identifier. (See [process_verification.md](process_verification.md))
*   **D-YYYYMMDD-NN**: An Architectural Decision identifier.
*   **`workspace/<model>/`**: The scratchpad for all model files. Always prefer "workspace."
*   **`workspace/<model>/dream_pad/`**: The scratchpad for dream sequences 
    **`workspace/<model>/old_stuff/`**: files which may be important but are not currently in use. old code, manifests, etc. do not run scripts in this directory.
    **`codex/manifests/old_stuff/`**: old codex files. avoid just saying "old stuff" without specifying workspace or codex, important files do not belong here.

## 6. Self-Development Lifecycle (SDL)

The rigid process for all structural system changes. (See [self_development.md](self_development.md))

*   **Change Proposal (CP)**: High-level solution draft. [Gated for user approval]
*   **Implementation Plan (IP)**: Detailed technical design. [Gated for user approval]
*   **Execution**: The application of the plan via `task` tool and `task.md`.
*   **Verification (VR)**: Formal pass/fail testing.
*   **Integration**: Permanent record-keeping in `history.md`.

---
*Maintained by The Architect*
