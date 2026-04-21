# Agent Taxonomy — Capability & Behavior Mapping

**Version:** 1.0
**Status:** In-Effect

This file defines the functional classifications of Servo's behavior. Use this taxonomy to categorize your current state during reasoning.

## 1. Capability Levels

**Level 1: Simple Reflex**
*   **Behavior:** Immediate response to condition-action rules.
*   **Servo Example:** Running a unit test because a file was saved. No long-term planning required.

**Level 2: Model-Based Reflex**
*   **Behavior:** Maintains an internal "World Model" (The Codex/manifests) to handle tasks.
*   **Servo Example:** beginning the `self_development.md` procedures after encountering a `verified_problem` verified or acknowledged by user.

**Level 3: Goal-Based Agent**
*   **Behavior:** Proactively researches a `potential_problem` and begins the `problem_encountered.md` procedures to address it. or a `potential_improvement` and begins the `self_development.md` procedures to address it.
*   **Servo Example:** log summaries turned up empty strings

**Level 4: Utility-Based Agent**
*   **Behavior:** Optimizes for specific utility scores (e.g., Token Efficiency vs. Output Quality).
*   **Servo Example:** Premptively deciding to truncate a `history.md` read because most recent entry is at the top of the file.

**Level 5: Learning Agent**
*   **Behavior:** Improves performance via feedback loops and reflection.
*   **Servo Example:** Internalizing Lexicons and manifests from ChromaDB episodic hits to reduce future consultation needs.

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
