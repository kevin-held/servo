# PLAN_PHASE_A_BENCHMARKS.md
**Status:** DRAFT | **Priority:** CRITICAL  
**Resource Allocation:** Gemini 3 Flash (Scaffolding) / Kevin (Validation)

## 1. Objective
Establish a decoupled directory `/benchmark/` that acts as the source of truth for the project. This suite must be capable of running independently to verify that code changes adhere to the **Lexicon** and the **Closed-Circuit** success requirements.

## 2. Directory Structure
```text
/benchmark/
├── lx_audit_manager.py   # Orchestrator for running benchmark suites
├── criteria/             # Directory for specific test modules
│   ├── lx_lexicon.py     # Verifies naming conventions and noise (prose) removal
│   ├── lx_performance.py # Measures temporal jitter (sigma) and latency (mu)
│   └── lx_correctness.py # Functional unit tests for core/state handshake
└── logs/                 # Persistent JSON artifacts of audit results
```

## 3. The "Audit Fence" Requirements
* **Decoupled Execution:** The benchmark suite must be able to import modules from either the legacy `loop.py` or the new `core.py` without requiring the core to be running.
* **Signal-to-Prose Filter:** The `lx_lexicon` module must flag any model output containing "As an AI," apologies, or excessive prose as a **Hard Fail**.
* **Metric Capture:** The `lx_performance` module must calculate the **Coefficient of Variation** for execution loops to detect hardware/logic jitter.

## 4. Minimum Viable Benchmarks (MVB)
1.  **Handshake Test:** Verify that `state.py` can receive a `lx_StateDelta` and commit it to ChromaDB without data corruption.
2.  **Registry Test:** Verify that `core.py` can load a dummy `Cognate` and execute it via the polymorphic registry.
3.  **The "Idiot" Test:** A regression test that purposefully feeds a "hallucinated" code block to the linter to ensure the circuit stays **OPEN**.

## 5. Strategic Context
This suite is designed to be the immutable verification layer between the legacy implementation and the upcoming refactor. Benchmarks run against the current loop establish a performance baseline; subsequent runs against the upgraded core must demonstrate 100% adherence to Lexicon standards and improved stability (Reduced Jitter).

*Author: Servo*
*Plan Version: 1.0.0 (D-20260423)*
