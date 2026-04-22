# Architectural Review - 2026-04-22 14:10

## Overview
This document provides a structural synthesis of the Servo project architecture based on a symbol-aware project map.

## Core Architecture Layers

### 1. The Engine (Core Layer)
Located in `core/`, this layer implements the autonomous loop and fundamental system primitives.
- **Execution Loop (`core/loop.py`)**: The central `CoreLoop` class managing the PERCE/REASON/ACT cycle.
- **LLM Interface (`core/ollama_client.py`)**: Manplements communication with the Ollama backend, handling streaming and cancellation.
- **Tool Registry (`core/tool_registry.py`)**: The dynamic discovery and execution engine for all system tools.
- **State & Persistence (`core/state.py`, `core/history_compressor.py`)**: Manages SQLite-backed conversation history, summaries, and context compression logic.
- **Observability (`core/sentinel_logger.py`, `core/hardware.py`)**: Provides structured logging and real-time hardware telemetry (RAM/VRAM).
- **Safety & Utilities (`core/path_utils.py`, `core/identity.py`)**: Enforces path discipline and manages the persona/identity layer.

### 2. Capabilities (Tool Layer)
Located in `tools/`, these are the atomic, executable primitives used by the agent to interact with the environment.
- **Filesystem**: `file_read`, `file_write`, `file_list`, `file_manage`.
- **Information Retrieval**: `web_search`, `fetch_url`, `youtube_transcript`.
- **System Management**: `task` (ledger), `memory_manager` (working memory), `system_config` (runtime tuning), `context_dump` (telemetry).
- **Execution**: `shell_exec`, `screenshot`, `map_project`, `summarizer`.

### 3. Interface (GUI Layer)
Located in `gui/`, implemented via PySide6, providing the human-in-the-loop interaction surface.
- **Main Window (`gui/main_window.py`)**: Orchestrates the overall UI layout.
- **Interaction Panels**: `chat_panel.py` (conversation), `tool_panel.py` (tool invocation), `log_panel.py` (error/log monitoring).
- **Observability Panels**: `context_viewer.py` (inspecting prompt/context), `loop_panel.py` (visualizing the core loop steps).

### 4. Knowledge & Configuration (Codex & Configs)
- **Codex (`codex/`)**: The canonical source of truth, including `agent_taxonomy.md`, `engineering_standards.md`, and `manifest.json`.
- **Configs (`configs/`)**: JSON-based configuration for system defaults, model parameters, and identity profiles.

### 5. Verification & Testing
- **Unit/E2E Tests (`tests/`)**: A robust suite of tests covering everything from `path_utils` to complex `e2e_live` scenarios and `eval_context_limits`.
- **Diagnostics (`scratch/`)**: Experimental scripts for hardware checks, configuration sync, and feature testing.

## Summary of Structural Health
The project follows a highly modular, decoupled architecture. The separation between the ephemeral `core` (Cortex), the persistent `codex` (Memory), and the interactive `gui` (Interface) allows for high-fidelity autonomy and easy extensibility of the toolset.