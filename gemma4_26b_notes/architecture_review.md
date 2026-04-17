# 🏗️ Project Architecture Review: Servo - Cybernetic Actuator

**Status:** Comprehensive Overhaul
**Last Updated:** 2026-04-16
**Version:** 2.1 (Post-Role Formalization & Proposal Integration)

## 🌟 System Overview
Servo is an autonomous agentic ecosystem built around a continuous, six-step cognitive loop. Unlike traditional request-response models, Servo operates as a persistent process that perceives, reasons, and acts upon its environment, driven by a multi-role architecture organized into functional layers.

---

## ⚙️ The Core Engine: The 6-Step Loop
The heart of the system is `core/loop.py`, a `QThread`-based execution engine that cycles through the following cognitive stages:

1.  **PERCEIVE**: Scans the environment (logs, filesystem, hardware status) for new data.
2.  **CONTEXTUALIZE**: Retrieves relevant historical data from SQLite and episodic memory from ChromaDB.
3.  **REASON**: Interfaces with the LLM (`ollama_client.py`) to determine the next logical step or action.
4.  **ACT**: Executes tools from the `tools/` registry to interact with the real world.
5.  **INTEGRATE**: Analyzes the results of actions and updates the internal state and memory.
6.  **IDLE**: Enters a low-power state or waits for the next scheduled trigger/event.

---

## 🧠 Intelligence & Memory Layers

### 1. Intelligence Layer (Layer 4)
*   **LLM Interface (`core/ollama_client.py`)**: A thin, resilient wrapper around the Ollama API, supporting retry logic and structured prompting.
*   **Dynamic Tool Registry (`core/tool_registry.py`)**: A plugin-based architecture where every Python file in the `tools/` directory is automatically discovered, loaded, and made available to the agent.
*   **The Analyst (Active)**: Performs deep-dive research, technical auditing of proposals, and risk assessment of complex datasets.

### 2. State & Memory Layer (Layer 2)
*   **Structured State (SQLite)**: Uses `state.db` with WAL (Write-Ahead Logging) mode to manage persistent conversation history, traces, and key-value system states.
*   **Episodic/Vector Memory (ChromaDB)**: A vector database implementation that allows the agent to perform semantic searches over past experiences.
*   **[PROPOSAL] Hierarchical Memory Summarization (CP-20260416-01)**: A proposed second tier of 'Summary' metadata to handle long-term semantic retrieval and prevent context overflow.

### 3. Engineering Layer (Layer 3)
*   **The Architect (Active)**: Strategic planner responsible for identifying technical debt and generating `Change Proposals`.

### 4. Observability Layer (Layer 1)
*   **The Sentinel (Active)**: Monitors `sentinel.jsonl` for `ERROR` and `CRITICAL` events; manages system health and hardware metrics.
*   **[PROPOSAL] Automated VRAM Threshold Alerting**: Integration of automated threshold checks to prevent OOM (Out of Memory) errors during high-load periods.

### 5. Orchestration Layer (Layer 5)
*   **The Orchestrator (Active)**: Ensures workspace integrity, updates `skill_map.md`, and manages role synchronization and manifests.

### 6. Security Layer (Layer 6)
*   **The Guardian (Pending)**: Performs security auditing and permission verification.

---

## 🖥️ Interface Layer (PySide6 GUI)
The `gui/` directory contains a sophisticated dashboard for human-in-the-loop interaction:
*   **Chat Panel**: Role-aware chat interface with support for text and image (Base64) streaming.
*   **Log Panel**: Real-time, color-coded stream of system logs with interactive level filtering.
*   **Loop Panel**: Visual representation of the current 6-step loop progress and step-specific status.
*   **Tool Panel**: An interactive explorer for discovering, testing, and even generating new tools at runtime.

---

## 📂 Workspace Structure
```text
ai/
├── configs/             # System and LLM configurations
├── core/                # The Engine (Loop, State, LLM, Registry, Logger)
├── gui/                 # PySide6 Dashboard (Chat, Log, Loop, Tool panels)
├── tools/               # The Agent's capabilities (Dynamic Python plugins)
├── logs/                # Structured system logs (JSONL)
├── state/               # Persistent storage (SQLite & ChromaDB)
├── gemma4_26b_notes/    # Knowledge base, manifests, and architecture docs
└── ...                  # Screenshots, Snapshots, and Tests
```

---
*Maintained by [The Scholar]*