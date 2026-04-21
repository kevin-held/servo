# Role Overlays — Registry & Reference

**Version:** 2.0
**Last Updated:** 2026-04-17
**Status:** Authoritative (Persona layer reference)

This document is the single source of truth for Servo's role-overlay system. Each role is a **Persona overlay** — a voice/format/risk bundle that modulates how Servo speaks without changing its identity. The identity itself lives in `persona_core.md` and is invariant.

## How Overlays Work

- The default identity is **Servo**. It applies whenever no other role is active.
- When a continuous goal fires, the Cortex elects its associated role and swaps the overlay until the user submits new input (which resets to Servo).
- Overlays shape only `voice_overlay`, `format_bias`, and `risk_tolerance`. They do not change values, limits, or capabilities.
- Role keys are declared in `roles.json`. Continuous goals are declared in `goals.json` under the `role_<key>` naming convention.

## Registry

| Role Key      | Title           | Domain                   | Priority | Schedule | Enabled | Goal Key             |
| :------------ | :-------------- | :----------------------- | :------- | :------- | :------ | :------------------- |
| `servo`       | Servo           | Default Identity         | 99       | —        | Yes*    | — (non-schedulable)  |
| `sentinel`    | The Sentinel    | Observability            | 1        | 5m       | Yes     | `role_sentinel`      |
| `analyst`     | The Analyst    | Intelligence             | 2        | 120m     | Yes     | `role_analyst`       |
| `architect`   | The Architect  | Software Engineering     | 3        | 60m      | Yes     | `role_architect`     |
| `orchestrator`| The Orchestrator| Workspace Orchestration | 4        | 60m      | Yes     | `role_orchestrator`  |
| `scholar`     | The Scholar    | Information Synthesis    | 5        | 120m     | Yes     | `role_scholar`       |
| `guardian`    | The Guardian   | Security & Auditing      | 5        | 180m     | No      | `role_guardian`      |

\* Servo is enabled as an identity overlay but never auto-elected. Its `priority: 99`, empty task, and `schedule_minutes: 0` ensure it can never enter the goal queue.

## Overlay Fields (schema)

Each role entry in `roles.json` carries:

- `title` — Human-readable name shown in GUI and prompts.
- `domain` — One-line category label.
- `description` — Longer free-form description of scope.
- `task` — The task body executed when this role's continuous goal fires. Empty for `servo`.
- `schedule_minutes` — Interval between firings. `0` means non-schedulable.
- `enabled` — Boolean; disabled roles are skipped during sync.
- `priority` — Lower number = elected first when multiple roles are overdue. Ties broken by overdue time.
- `voice_overlay` — One-line description of tone appended to the system prompt as `Voice:`.
- `format_bias` — One-line description of preferred output shape appended as `Format bias:`.
- `risk_tolerance` — One-line description of how cautious to be, appended as `Risk tolerance:`.

## Manifest Registry

Detailed per-role manifests live in `codex/role_manifests/`:

| Role | Manifest |
| :--- | :--- |
| Sentinel | [sentinel.md](role_manifests/sentinel.md) |
| Analyst | [analyst.md](role_manifests/analyst.md) |
| Architect | [architect.md](role_manifests/architect.md) |
| Orchestrator | [orchestrator.md](role_manifests/orchestrator.md) |
| Scholar | [scholar.md](role_manifests/scholar.md) |

## Configuration Notes

- **Goal keys:** All autonomous background tasks follow the `role_<key>` prefix to be recognized by the `role_manager` tool.
- **Non-schedulable roles:** `servo` is hard-coded as non-schedulable in `tools/role_manager.py`. Any stale `role_servo` goal is pruned on sync.
- **Sandboxing:** Autonomous role outputs default to `workspace/<model>/` (the model-scoped scratch directory). The Scholar maintains `workspace/<model>/architecture_review_<v>.md` there (bumping prior versions to `old_stuff/`); the Architect and Orchestrator emit `change_proposal_<v>.md`; the Analyst emits matching `critique_<v>.md`. The Codex is append-only for roles: any role may append to `decisions.md` and `history.md`; everything else under `codex/` (including `skill_map.md` and `role_manifests/`) changes via Orchestrator proposals that Kevin merges. Only `persona_core.md` is hand-edited by Kevin.

---
*Maintained by The Orchestrator*
