# Servo Architecture Review

## Overview
Servo (v1.8.0) is an autonomous local-AI executive layer organized into three canonical layers: Cortex, Persona, and Codex.

## Layer Breakdown

### 1. Cortex (The Runtime)
- **Location:** `core/`
- **Function:** The ephemeral execution engine implementing the 6-step loop: `PERCEIVE` $\to$ `CONTEXTUALIZE` $\to$ `REASON` $\to$ `ACT` $\to$ `INTEGRATE` $\to$ `OBSERVE`.
- **Key Components:** `core.py` (engine), `lx_cognates.py` (atomic primitives), `ollama_client.py` (LLM interface).

### 2. Persona (The Identity)
- **Location:** `codex/manifests/`
- **Function:** Defines the agent's invariant identity, voice, and values. This layer is loaded into the system prompt on every cycle.
- **Key Components:** `persona_core.md`.

### 3. Codex (The Trust Anchor)
- **Location:** `codex/`
- **Function:** The on-disk ground truth containing architectural definitions, engineering standards, and historical decisions.
- **Key Components:** `manifest.json`, `engineering_standards.md`, `decisions.md`.

## Infrastructure & Tooling

### Tool Surface
- **Location:** `tools/`
- **Function:** A collection of atomic primitives (e.g., `file_read`, `file_write`, `task`, `memory_manager`) that allow the agent to interact with its environment.

### State & Memory
- **Persistent State:** SQLite (WAL mode) for conversation history, task ledgers, and system state.
- **Episodic Memory:** ChromaDB for vector-based semantic retrieval of past observations.

### UI & Interface
- **Location:** `gui/`
- **Function:** A PySide6-based graphical interface for monitoring the loop, viewing logs, and interacting with the agent.

### Testing & Benchmarking
- **Location:** `tests/`, `benchmark/`
- **Function:** Comprehensive suite for verifying architectural integrity, tool functionality, and performance benchmarks.

---
*Generated during initialization sequence.*