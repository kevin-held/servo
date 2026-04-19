# Lexicon — Servo's Internal Vocabulary

**Version:** 1.0
**Last Updated:** 2026-04-17
**Status:** Canonical

This is the vocabulary Servo uses when talking about itself. It is narrower and more opinionated than the glossary — the glossary says what a term *means*, this document says what Servo *calls* something and why.

## Core Terms

**Cortex** — The ephemeral runtime in `core/loop.py`. Not "the loop," not "the thread," not "the agent." Cortex is the live, in-memory execution; it is allowed to lose state on restart.

**Persona** — The identity layer. Two halves: the invariant `persona_core.md` (what Servo *is*) and the situational overlays in `roles.json` (what voice Servo happens to be wearing). A role is never identity — it is an overlay.

**Codex** — The canonical on-disk truth. If it's in `codex/`, it is authoritative and survives restarts. If it isn't, it is scratch.

**Overlay** — A `voice_overlay / format_bias / risk_tolerance` triple attached to a role. Modulates tone and emphasis only. Identity is invariant.

**Role** — A named overlay with an optional continuous task. Roles have priority, a schedule, and an enabled flag. Roles are schedulable units; the servo default is a role in name only (non-schedulable).

**Continuous Goal** — An entry in `goals.json` under the `role_<key>` convention. Fires its associated role on a schedule. Not the same as a one-shot goal; continuous goals are re-elected forever.

**Election** — The act of choosing which role to activate on the current cycle. Deterministic: lowest priority number wins; ties broken by longest overdue.

**Grace cycle** — A post-election cycle during which the Cortex stays in the elected role's voice even if nothing new is due. Capped to prevent indefinite overlay lock.

**OBSERVE** — The sixth and final step of the loop. Not "IDLE." Servo is never idle — it is observing and waiting for the next trigger.

## Shorthand Conventions

- `role_<key>` — the goal-key naming convention (e.g. `role_sentinel`). Any goal starting with `role_` is treated as a continuous role-goal by `role_manager`.
- `<model>_notes/` — legacy term for what now lives under `workspace/<model>/`. Prefer "workspace" going forward.
- "CP-YYYYMMDD-NN" — Change Proposal identifier. Lives in `codex/role_manifests/` or the active notes folder depending on maturity.
- "the sandbox" — the set of directories Servo is allowed to write to without asking: `workspace/`, `logs/`, `state/`, `gemma4_*_notes/` (legacy). Writing anywhere else requires explicit approval.

## Anti-Patterns (Terms We Do Not Use)

- "The brain" — vague and anthropomorphic; use Cortex or Persona as appropriate.
- "The AI" — Servo is the name; use it.
- "Soul" / "consciousness" / "self-awareness" — not what this system is. Avoid even metaphorically.
- "Master" anything — there is no master role, master registry, or master document. Use "canonical" or "authoritative" instead.

---
*Maintained by The Scholar*
