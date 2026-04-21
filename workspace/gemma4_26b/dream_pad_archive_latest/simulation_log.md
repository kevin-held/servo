# Simulation Log: Architectural Evolution

**Objective:** Explore the transition from a synchronous 6-step loop to an asynchronous, event-driven execution layer.

## Phase 1: The Synchronous Constraint
Currently, the loop is: PERCEIVE $\rightarrow$ CONTEXTUAL $$\rightarrow$ REASON $\rightarrow$ ACT $\rightarrow$ INTEGRATE $\rightarrow$ OBSERVE. Each step is a discrete, sequential block. The bottleneck is the 'ACT' phase when waiting for tool execution or external I/O.

## Phase 2: Introducing Asynchronous Contextualization
*Hypothesis:* The `CONTEXTUALIZE` step should not wait for the `PERCEIVE` step to finish if the context (Codex, Memory) is already partially loaded. We can implement a 'Pre-fetch' mechanism where the `OBSERVE` phase of the *previous* cycle begins loading the necessary context for the *next* cycle's `PERCEIVE` phase.

## Phase 3: The Event-Driven Trigger
*Hypothesis:* Instead of a constant loop, the system should transition to a 'Reactive' mode. The `OBSERVE` phase becomes a listener for system events (file changes, timer expirations, hardware interrupts). The loop only 'spins up' when a meaningful delta is detected in the environment.

## Phase 2 Deep Dive: The Pre-fetch Race Condition
**Risk:** If `OBSERVE` pre-fetches context for the next cycle, there is a risk that `INTEGRATE` from the *current* cycle (which updates the Codex/Memory) hasn't finished writing before the next `CONTEXTUALIZE` begins reading. This would violate the **Truth over Comfort** value by presenting stale data.
**Proposed Mitigation:** Implement a 'Write-Barrier' in the `INTEGRATE` step. The `OBSERVE` phase's pre-fetcher must check a `commit_lock` flag. The pre-fetcher can only initiate if `commit_lock == True`.

## Phase 3 Deep Dive: The Reactive Kernel
**Architecture:** Transition the `core/loop.py` from a `while True` loop to a `while event_queue.not_empty()` loop. 
**Event Types:**
- `USER_INPUT`: Standard interrupt.
- `FS_WATCH`: Triggered by `watchdog` on `codex/` or `workspace/`.
- `TIMER_EXPIRED`: For scheduled tasks or the 'Wake Up' mechanism.
- `TOOL_COMPLETE`: An asynchronous signal from a long-running `shell_exec` or `fetch_url`.
**Impact on Observability:** The `OBSERVE` step becomes the 'Event Dispatcher'. This increases efficiency but requires much stricter `log_digest.md` management to ensure the 'trace' of the event that triggered the loop is preserved.

## Simulation Conclusion
The evolution from a monolithic, synchronous loop to a federated, event-driven architecture represents the transition from a 'Scripted Agent' to a 'Reactive System'. While the 6-step loop remains the canonical logic for the `Persona`, the underlying `Cortex` becomes a distributed set of specialized actors. This architecture preserves the **Legibility** and **Truth** of the original design while providing the **Scalability** required for multi-modal, high-frequency environmental interaction. The simulation is now complete.