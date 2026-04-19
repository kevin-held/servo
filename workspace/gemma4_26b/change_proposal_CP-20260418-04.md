# Change Proposal: CP-20260418-04
**Date:** 2026-04-18
**Author:** role_architect
**Status:** Proposed

## 1. Overview
The current `architecture_review_v5.md` is out of sync with the canonical `decisions.md` and `history.md` files. It is missing critical architectural decisions made during the Phase 5 pilot (Log Summarization) and the v0.6.0 release (Path Discipline).

## 2. Proposed Changes

### 2.1 Update `workspace/gemma4_26b/architecture_review_v5.md`

#### 2.1.1 Expand Decisions Section
Append the following decision entries to the "Decisions" section:

### D-20260417-06 — Scope Phase 5 memory-summarization to cold logs only
**Date:** 2026-04-17
**Status:** Accepted
**Context:** The original Phase 5 spec proposed broad memory summarization. That surface is too large to land in one change.
**Decision:** Scope the Phase 5 pilot to cold logs only. Destination is `codex/log_digest.md`. Driver is `tools/log_summarizer.py`.
**Consequences:** Pilot is small and validatable in isolation.

### D-20260417-07 — Log summarizer must segregate incidents from routine
**Date:** 2026-04-17
**Status:** Accepted
**Context:** The first two digests omitted real ERROR-level events because they were drowned in INFO chatter.
**Decision:** Split the entry stream into `INCIDENTS` and `ROintine` sections. Lead with incidents and quote context values verbatim.
**Consequences:** Error details survive into the prompt.

### D-20260417-08 — Log summarizer must send log data as a user turn, not as a system prompt
**Date:** 2026-04-17
**Status:** Accepted
**Context:** The digest arrived empty when run against gemma:26b because the request lacked a user turn.
**Decision:** Split the prompt into `system_rules` and `user_content`. Call the client with a `user` role message.
**Consequences:** The tool works against gemma:26b as intended.

### D-20260417-09 — All tool path arguments are project-root-relative
**Date:** 2026-04-17
**Status:** Accepted
**Context:** Sentinel was hitting FileNotFoundError on hallucinated absolute paths.
**Decision:** Implement Single-Anchor Discipline. All paths must be project-root-relative. Reject absolute paths and `..` escapes.
**Consequences:** Mangled-user-segment paths can no longer land in the filesystem layer.

#### 2.1.2 Update Recent Changes (Delta)
Update the "Recent Changes" section to include the `v0.6.0` release (Path Discipline).

## 3. Rationale
Maintaining synchronization between the architecture review and the canonical truth is critical for the integrity of the system's documentation.

## 4. Risk Assessment
- **Risk:** Low. This is a documentation-only update.
- **Impact:** High. Restores the accuracy of the system's primary architectural artifact.