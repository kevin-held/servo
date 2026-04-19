# Rejected proposals

This is a durable record of change proposals that were considered and rejected.
It exists so that autonomous roles (Architect, Analyst) don't re-surface ideas
that have already been evaluated and declined.

**Format:** each entry includes the proposal ID, title, original source, the
rejection rationale, and the date rejected. Entries are never deleted — only
superseded or amended.

---

## CP-20260416-03 — Automated VRAM Threshold Alerting / Hysteresis

**Source:** `gemma4_26b_notes/change_proposals.md`
**Status:** REJECTED
**Rejected:** 2026-04-17
**Decided by:** Kevin

**Proposal summary:**
Add a VRAM hysteresis layer on top of the existing hardware monitor so that
Critical status uses two thresholds (enter at 95%, exit at 85%) to prevent
oscillation between Critical and Stable when VRAM hovers near the limit.
Bundle this with a lightweight alerting hook that fires when the threshold is
crossed.

**Rejection rationale:**
The existing `core/hardware.py` already requires **both** RAM >= 95%
**and** VRAM >= 95% to reach Critical — a conservative AND-gate that does not
oscillate in practice. Hysteresis adds state (last-seen status, dwell timers)
without solving a real problem we have observed. We prefer the simpler gate
with the throttle-then-restore pattern already implemented in `core/loop.py`:

- On Critical: clear KV cache, reduce `conversation_history` by 2 down to a
  model-appropriate floor (`default_conversation_history // 2`).
- On 5 consecutive stable cycles: restore `conversation_history` to the model
  default.

That loop already provides the stability benefit hysteresis was meant to
deliver, without the extra machinery.

If future observation shows actual oscillation under load, revisit. Until then
this is closed.

**Related:**
- `UPGRADE_PLAN.md` § 2.3 "Fix premature context shrink" — where the
  soft-shrink and model-side nudge problems are addressed instead.
- `core/hardware.py` — the AND-gate is in `get_resource_status`.

---

## CP-001 / CP-20260416-02 / tool_manifest — Tool-registry metadata rework (trilogy)

**Source:** `workspace/gemma4_26b/change_proposal_001.md`,
`workspace/gemma4_26b/change_proposal_20260416_02.md`,
`workspace/gemma4_26b/change_proposal_tool_manifest.md`
**Status:** REJECTED (all three variants)
**Rejected:** 2026-04-18
**Decided by:** Kevin

**Proposal summaries:**
Three overlapping drafts by the Architect role, each attacking the tool
registry from a different angle:
- **CP-001 "Context-Aware Tool Discovery"** — add an `allowed_tools` array per
  role in `roles.json`; registry filters by active role so tool descriptions
  for irrelevant roles don't burn context.
- **CP-20260416-02 "Unified Tool Metadata Schema"** — a `@tool_metadata`
  decorator adding `version`, `author`, `dependencies`, `complexity_score`,
  `usage_examples` to every tool; registry extracts and caches in `state.db`.
- **change_proposal_tool_manifest "Centralized Tool Manifest"** — move tool
  metadata out of the `.py` file and into a separate `tools/manifest.json`
  as the single source of truth.

**Rejection rationale:**
Duplicative re-discovery of the same surface ("tool metadata could be richer")
from three angles, none of which solves a problem we actually have.

- The tool-count is small (~12) and description bloat in the context window is
  not yet painful. Per-role filtering (CP-001) is the only variant with
  latent value and it is premature at this scale — revisit at 30+ tools.
- The decorator schema (CP-20260416-02) solves a dependency/version problem
  that doesn't exist: no tool depends on another, no tool has a second author,
  and the current `TOOL_SCHEMA` dict is already extensible. Adding
  `complexity_score` fields invites guessing.
- The JSON manifest (tool_manifest) is actively worse than the status quo —
  it creates the exact synchronization bug it acknowledges in § 3: add a
  `.py`, forget to update the JSON, tool silently disappears. Co-locating
  metadata with the function is correct and should stay.

The real problem the Architect is pattern-matching on — "tool context is
getting big" — is a token-budget problem solvable by shortening descriptions,
not by introducing registry indirection.

**Note on ID collision:**
The Architect used `CP-20260416-02` for BOTH the Unified Metadata Schema
and the Guardian proposal on the same day. Future proposal generation should
check this file and prior proposals before claiming an ID.

---

## CP-20260417-01 — Resource-Aware Task Scheduling (RATS)

**Source:** `workspace/gemma4_26b/change_proposal_CP-20260417-01.md`
**Status:** REJECTED
**Rejected:** 2026-04-18
**Decided by:** Kevin

**Proposal summary:**
A "gatekeeper" layer between PERCEIVE and REASON that queries
`core/hardware.py` pressure before every high-complexity role call and
applies dynamic complexity scaling: Green Zone (< 80%) → full params,
Yellow Zone (80–95%) → reduced `max_tokens` and temperature, Red Zone
(> 95%) → snooze/throttle. All scaling decisions logged to `sentinel.jsonl`.

**Rejection rationale:**
Over-engineered for a problem that doesn't exist in practice. `core/hardware.py`
already uses a conservative AND-gate (both RAM ≥ 95% AND VRAM ≥ 95%) to reach
Critical, and `core/loop.py` already throttles `conversation_history` in that
state — see the already-rejected CP-20260416-03 entry above for the full
mechanism. Adding three zones, pre-execution checks per cycle, and dynamic
temperature/max_tokens scaling adds latency and state on top of a system that
isn't actually observed to OOM.

If a real OOM or pressure event is later observed in production, the minimal
correct response is a single WARNING log line in Sentinel when
`get_resource_status` returns Critical — not a scheduler layer. Closed.

---

## Guardian activation trilogy — CP-20260416-02 / CP-20260418-01 / CP-IMPLEMENT-GUARDIAN

**Source:** `workspace/gemma4_26b/change_proposals.md` (CP-20260416-02 Guardian
variant), `workspace/gemma4_26b/change_proposal_CP-20260418-01.md`,
`workspace/gemma4_26b/change_proposal_guardian_implementation.md`
**Status:** REJECTED / DEFERRED (all three variants)
**Rejected:** 2026-04-18
**Decided by:** Kevin

**Proposal summaries:**
Three iterations by the Architect role proposing activation of the `guardian`
role (`enabled: false` in `roles.json`):
- **CP-20260416-02 (Guardian variant)** — formalize the role, create
  `role_guardian_manifest.md`, add continuous goal, build a new
  `file_integrity_checker` tool using SHA-256 hashes of `core/` and `tools/`
  to detect unauthorized changes, with a "Maintenance Mode" flag to suppress
  alerts during legitimate updates.
- **CP-20260418-01 "Activation of the Security Layer"** — revised version
  adding "Triangulation Logic": every critical file change must be verified
  across (1) filesystem presence, (2) authorization in `decisions.md`,
  (3) mtime/hash integrity.
- **CP-IMPLEMENT-GUARDIAN** — narrowest version, just "create the manifest
  and schedule the role at 1080 min intervals."

**Rejection rationale:**
The threat model doesn't justify the role. Kevin is the only entity editing
files in `core/`, `tools/`, and `codex/`. A hash-based integrity checker
either (a) alerts on every legitimate commit — noise, or (b) requires
Maintenance Mode and decisions.md triangulation for every change —
bureaucracy without a real adversary.

The two paths the Guardian was meant to guard are already covered:
- **Model writes outside the sandbox** — prevented at the tool boundary by
  `core/path_utils.py` (v0.6.0, D-20260417-09). No need for detection after
  the fact when prevention is deterministic.
- **Unauthorized external tampering** — the threat model for a single-user
  local dev environment doesn't warrant periodic SHA-256 scans.

If a real need emerges later — e.g., the model starts writing files outside
the sandbox via a pathway the resolver doesn't cover — the minimal response
is a single WARNING in Sentinel when an unexpected write is observed, not an
activated role with its own manifest, goal, and tool. Fold into Sentinel
if/when needed.

Guardian role entry stays in `roles.json` with `enabled: false` as an opt-in
hook for future work. All three proposals closed.

---

## Meta-observation: Architect role rediscovers prior proposals

**Observed:** 2026-04-18
**By:** Kevin (during workspace review)

The Architect role wrote three tool-registry proposals and three Guardian
proposals on separate days without referencing the earlier ones. Root cause:
the Architect's prompt doesn't surface prior workspace proposals or this
`rejected_proposals.md` before generating new proposals. Fix is a prompt or
role-manifest change: before drafting a new proposal, the Architect should
read `codex/rejected_proposals.md` and its own recent workspace drafts to
check for duplicates. Tracked but not scheduled — will revisit when the next
Architect cycle runs and we can see whether this file alone breaks the loop.

---

## CP-20260418-02, -03, -04, -05 — Proposals against archived architecture reviews

**Source:** `workspace/gemma4_26b/change_proposal_CP-20260418-02.md`,
`...03.md`, `...04.md`, `...05.md` (each with a matching Analyst critique
in the same folder — the Analyst APPROVED them without noticing the
archival issue)
**Status:** REJECTED (all four)
**Rejected:** 2026-04-18
**Decided by:** Kevin

**Proposal summaries:**
Four Architect-cycle proposals, each drafted against a superseded baseline:
- **CP-20260418-02** — Relabel the Sentinel manifest's `Layer:` field from
  `Observability (Layer 1)` to `Persona (Observability Overlay)`. The
  manifest was ALREADY on the correct label when the proposal was drafted;
  the Architect was reading from memory of an earlier version.
- **CP-20260418-03** — "Update `architecture_review_v5.md` to mark
  CP-20260418-02 as no longer pending." v5 was archived under `old_stuff/`
  and the active baseline was v8 by the time this was drafted. v5 is dead
  state, not live documentation.
- **CP-20260418-04** — Append ADRs D-20260417-06 through -09 to
  `architecture_review_v5.md`. Same archival problem; those ADRs already
  exist in `codex/decisions.md` (canonical), and the baseline being edited
  was superseded.
- **CP-20260418-05** — Fix a typo ("Cintrex" → "Cortex") in
  `architecture_review_v6.md`. v6 was also already archived under
  `old_stuff/`.

**Rejection rationale:**
Four proposals, one failure mode: the Architect was drafting against
archived artifacts because its auto_tool payload didn't carry the current
review's text. The Architect was invoking `scholar_runner` with default
args, which returned only `review_path` — forcing the model to either
re-read the file (extra cycle, sometimes skipped) or work from memory of a
prior review. When memory was stale, the target pointer was stale too.
Add an archival guard to roles and manifests, and inline the current
review text into the Architect's nudge so the model cannot work from a
stale snapshot. Tracked as D-20260418-07.

The Analyst critiques on all four APPROVED these proposals because its
own auto_tool (then `filesystem:list` on the workspace folder) didn't
carry any signal about whether a target path was archived. Addressed in
the same decision via a new `analyst_runner` tool that pre-classifies
each target as `is_archived=true/false` with an `archived_reason`.

---

## CP-20260418-06 — Fix the (non-broken) log_summarizer tool

**Source:** `workspace/gemma4_26b/change_proposal_CP-20260418-06.md`
**Status:** REJECTED
**Rejected:** 2026-04-18
**Decided by:** Kevin

**Proposal summary:**
"Perform a structured refactor of the `log_summarizer` tool: fix the
underlying error, verify checkpoint logic, implement dry-run validation,
standardize output alignment with INCIDENTS/ROUTINE." The proposal's
Problem Statement opened with "Currently, the `log_summarizer` tool is in
a broken state."

**Rejection rationale:**
The tool is not broken. `tools/log_summarizer.py` at v0.5.2 (see
`decisions.md` D-20260417-08) is working: the checkpoint advanced on Apr
17 18:48; the INCIDENTS/ROUTINE split is live (D-20260417-07); the
user-turn message shape landed in v0.5.2. The premise was false.

Root cause of the false premise: `codex/role_manifests/sentinel.md`
carried a stale "Known issue: `log_summarizer` is currently broken"
block, left over from an earlier debugging session. The Architect read
the manifest, pattern-matched on the warning, and drafted a proposal
against a problem that no longer existed. The manifest warning was
removed in the same cycle (see `history.md` v0.6.5 and `decisions.md`
D-20260418-08).

Lesson: stale "Known issue" blocks in role manifests are load-bearing
lies — they teach the model to rediscover non-problems. When a tool is
fixed, the warning must be struck at the same time.
