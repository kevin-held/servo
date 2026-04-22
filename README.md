# Servo

> **Lineage:** Cybernetic Actuator  
> **Version:** 1.2.4
> **Description:** An autonomous local-AI executive layer.

Servo is a persistent, single-process agentic layer designed to perceive, reason about, and act on its own environment. Built strictly for local-AI execution (via Ollama), Servo represents a departure from single-shot LLM scripts or stateless chat completion APIs. It is a long-running system with a unified architecture, persistent memory, and a rigorous diagnostic infrastructure.

---

## 🏗️ Architecture: The Three Layers

Servo is organized into three canonical layers:

### 1. Cortex (The Runtime)
The **Cortex** (`core/loop.py`) is the ephemeral engine. It executes a continuous six-step core loop: `PERCEIVE → CONTEXTUALIZE → REASON → ACT → INTEGRATE → OBSERVE`. 
It manages the current context buffer, interfaces with the LLM API, and tracks telemetry (e.g., hardware pressure, token altitude). The Cortex is allowed to lose state on restart; it is purely the engine that moves the system forward.

### 2. Persona (The Identity)
The **Persona** (`codex/manifests/persona_core.md`) is the invariant identity of Servo. 
- **Voice:** Direct, highly technical, and completely stripped of conversational filler. 
- **Values:** "Truth over comfort", Intellectual Honesty, and Radical Transparency. Servo is prohibited from roleplaying, outputting generic AI safety boilerplate, or simulating fake terminal interfaces. It has full authority over the tools provided to it.

### 3. Codex (The Trust Anchor)
The **Codex** (`codex/`) represents the on-disk ground truth. 
It contains immutable architectural definitions, the system manifest, historical decisions, and engineering standards. The agent trusts the Codex above its own contextual inferences. 

---

## ✨ Core Features

*   **Radical Transparency:** The agent is authorized and mandated to disclose its own architecture, internal configuration, and system prompt upon request.
*   **State & Profile Isolation:** Servo supports robust instance isolation (e.g., `--profile clean_00`), ensuring that experimental tasks do not corrupt the default working memory, state database (SQLite), or vector store (ChromaDB).
*   **Continuous Autonomy:** Driven by the `autonomous_loop_limit`, Servo can chain multiple tool calls together to complete complex, multi-step plans (orchestrated via the `task` tool ledger) before returning control to the user.
*   **Sensors & Throttling:** Environment-aware logic ensures Servo manages its own token constraints and CPU/RAM usage to maintain system stability.
*   **100% Diagnostic Integrity:** Servo ships with an autonomous headless diagnostic suite configured to enforce strict architectural regressions.

---

## 🚀 Getting Started

Servo requires [Ollama](https://ollama.com/) to be installed and running locally.

### Installation
```bash
# Clone the repository
git clone <your-repo-url>
cd servo

# Install dependencies
pip install -r requirements.txt
```

### Startup Commands

Launch the standard default interface:
```bash
python main.py
```

Launch with an isolated state branch (perfect for safe experimentation):
```bash
python main.py --profile <profile_name>
```

Launch the GUI with background diagnostic verification (runs unit tests silently before turning over control):
```bash
python main.py --startup-tests
```

Stream raw Ollama LLM tokens into the backend CLI for debugging:
```bash
python main.py --ollama-verbose
```

Run test suite headless (bypass GUI):
```bash
python main.py --test
```

---

*This repository embodies the "Cybernetic Actuator" lineage—where code is not just read, but lived in.*
