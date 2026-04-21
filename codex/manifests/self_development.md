# Self-Development Lifecycle (SDL)

**Version:** 1.0
**Status:** In-Effect

The rigid process for all structural system changes. This ensures that every modification is deliberate, planned, and verified.

## 1. Phase Overview

| Phase | Identifier | Purpose |
| :--- | :--- | :--- |
| **1. Change Proposal** | `CP-YYYYMMDD-NN` | High-level solution draft. Define the "What" and "Why". |
| **2. Implementation Plan** | `IP-YYYYMMDD-NN` | Detailed technical design. Define the "How". |
| **3. Execution** | - | Application of changes via `task` tool and `task.md`. |
| **4. Verification** | `VR-YYYYMMDD-NN` | Formal pass/fail testing. |
| **5. Integration** | - | Permanent record-keeping in `history.md` and `decisions.md`. |

## 2. Gating
*   **CP & IP**: Require explicit user approval before moving to the next stage.
*   **Execution**: Only permitted once the IP is approved.
*   **Verification**: Requires evidence of success (tests, logs, or user sign-off).

## 3. Documents
*   [Change Proposal Template](process_cp.md)
*   [Implementation Plan Template](process_ip.md)
*   [Verification Report Template](process_verification.md)
*   [Integration Checklist](process_integration.md)

---
*Maintained by The Architect*
