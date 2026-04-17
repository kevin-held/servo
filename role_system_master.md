# 🏛️ Role System Master Registry

This document serves as the single source of truth for the Agent's multi-layered role architecture. It maps the high-level personas to the active system configurations.

## 🗺️ System Layer Map

| Layer | Role Title | Role Key | Domain | Status | Continuous Goal |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Observability** | The Sentinel | `sentinel` | System Health | **Active** | `role_sentinel` |
| **2. Synthesis** | The Scholar | `scholar` | Architecture Knowledge | **Active** | `role_scholar` |
| **5. Orchestration** | The Orchestrator | `orchestrator` | Workspace Integrity | **Active** | `role_orchestrator` |
| **3. Engineering** | The Architect | `architect` | Strategic Planning | **Active** | `role_architect` |
| **4. Intelligence** | The Analyst | `analyst` | Data/Visual Analytics | **Active** | `role_analyst` |
| 6. Security | The Guardian | `guardian` | Security Auditing | *Pending* | - |

## 📁 Manifest Registry

| Role | Manifest Path | Primary Directive Source |
| :--- | :--- | :--- |
| **The Sentinel** | [sentinel_manifest.md](file:///c:/Users/kevin/OneDrive/Desktop/ai/gemma4_26b_notes/sentinel_manifest.md) | System Logs |
| **The Scholar** | [scholar_manifest.md](file:///c:/Users/kevin/OneDrive/Desktop/ai/gemma4_26b_notes/scholar_manifest.md) | `analyze_directory` (mtime analysis) |
| **The Architect** | [architect_manifest.md](file:///c:/Users/kevin/OneDrive/Desktop/ai/gemma4_26b_notes/architect_manifest.md) | `architecture_review.md` & Strategy Planning |
| **The Analyst** | [analyst_manifest.md](file:///c:/Users/kevin/OneDrive/Desktop/ai/gemma4_26b_notes/analyst_manifest.md) | `change_proposals.md` & Full File Ingestion |
| **The Orchestrator** | [orchestrator_manifest.md](file:///c:/Users/kevin/OneDrive/Desktop/ai/gemma4_26b_notes/orchestrator_manifest.md) | Workspace Root |

## ⚙️ Configuration Notes

- **Goal Keys**: All autonomous background tasks must follow the `role_<key>` prefix to be recognized by the `role_manager` tool.
- **Schedules**: 
  - Sentinel: 5m (High Priority Observability)
  - Scholar: 120m
  - Orchestrator: 60m
- **Sandboxing**: All autonomous role outputs are strictly confined to the `notes` folders (e.g., `gemma4_26b_notes`).

---
*Last Updated: 2026-04-16 | Maintained by The Orchestrator*
