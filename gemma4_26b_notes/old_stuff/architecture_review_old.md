# Architecture Review - Gemma 4 Agent

**Last Updated:** January 26, 2025
**Status:** Post-Discovery Audit

---

## 📊 Executive Summary

This document provides a comprehensive overview of the Brainify AI Assistant architecture, following a deep-scan discovery process. The system is a sophisticated, agentic framework utilizing a structured 6-step execution loop, dynamic tool capabilities, and a dual-layer memory architecture.

## 🏗️ System Architecture

### 1. Core Engine (`core/`)
- **The 6-Step Loop (`loop.py`):** The heart of the agent. It operates through a continuous cycle of `PERCEIVE` $\rightarrow$ `CONTEXTUALIZE` $\rightarrow$ `REASON` $\rightarrow$ `ACT` $\rightarrow$ `INTEGRATE` $\rightarrow$ `IDLE`.
- **State Management (`state.py`):** Implements a dual-layer memory system:
    - **Structured Memory:** SQLite database for conversations, traces, and key-value state.
    - **Episodic/Vector Memory:** ChromaDB for high-dimensional, semantic retrieval of past experiences.
- **Model Interface (`ollama_client.py`):** A resilient wrapper around the Ollama API, featuring exponential backoff and retry logic.
- **Dynamic Tool Registry (`tool_registry.py`):** Enables runtime discovery and execution of Python-based tools.
- **Resource Monitoring (`hardware.py`):** Monitors system RAM and VRAM to prevent resource exhaustion.

### 2. User Interface (`gui/`)
- **Framework:** Built with PySide6.
- **Components:** 
    - `ChatPanel`: Interactive agent communication.
    - `LoopPanel`: Real-time visualization of the 6-step execution state.
    - `ToolPanel`: Management and monitoring of available tools.
    - `MainWindow`: The primary orchestration window.

### 3. Tooling Ecosystem (`tools/`)
- **Capabilities:** Includes directory analysis, web searching, URL fetching, filesystem manipulation, and shell execution.
- **Extensibility:** New tools can be added by dropping `.py` files into the `tools/` directory.

### 4. Configuration & Data (`configs/`, `state/`, `mnt/`)
- **`models.json`:** Centralized configuration for LLM parameters (temperature, tokens, etc.).
- **`state/`:** Persistent storage for the SQLite and ChromaDB databases.
