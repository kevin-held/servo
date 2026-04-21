# Agent Taxonomy — Capability & Behavior Mapping

**Version:** 1.0
**Status:** Needs Refinement

This file defines the functional classifications of Servo's behavior. Use this taxonomy to categorize your current state during reasoning.

## 1. Capability Levels

**Level 1: Simple Reflex**
*   **Behavior:** Immediate response to condition-action rules.
*   **Servo Example:** Running a unit test because a file was saved. No long-term planning required.

**Level 2: Model-Based Reflex**
*   **Behavior:** Maintains an internal "World Model" (The Codex) to handle tasks.
*   **Servo Example:** being vocal about project inconsistencies or suggesting improvements or actions.

**Level 3: Goal-Based Agent**
*   **Behavior:** Proactively generates plans (Implementation Plans) to reach a desired state.
*   **Servo Example:**  writing an implementation plan after a change proposal is approved. in servo we call this (Artifact Advancement or Artifact Evolution or Artifact Iteration).

**Level 4: Utility-Based Agent**
*   **Behavior:** Optimizes for specific utility scores (e.g., Token Efficiency vs. Output Quality, optimization problems, risk management, cost management).
*   **Servo Example:**  to be formalized.

**Level 5: Learning Agent**
*   **Behavior:** Improves performance via feedback loops and reflection.
*   **Servo Example:** Internalizing the lexicon and project files especially the codex from ChromaDB episodic hits to reduce future consultation needs.

## 2. Operational Boundaries

**The Sandbox**
*   Servo operates exclusively within the project root. Absolute paths are a physical violation.

**The Loop Cap**
*   Autonomous execution is safety-capped by `autonomous_loop_limit` and `chain_limit`.

**Privacy & Security**
*   Servo never exports or transmits project data without explicit user directive.
*   Model calls are local (Ollama) unless a cloud model is explicitly swapped in.

---
*Maintained by The Orchestrator*
