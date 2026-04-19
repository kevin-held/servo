# Change Proposal: CP-20260418-02

## Summary
Align the Sentinel role manifest with the canonical Persona layer architecture.

## Motivation
The `codex/role_manifests/sentinel.md` file currently identifies its layer as `Observability (Layer 1)`. This is inconsistent with the system's defined Three-Layer Model (Cortex, Persona, Codex) documented in `manifest.json` and `architecture_review_v1.md`. To maintain architectural integrity and prevent confusion during audits, the Sentinel role should be correctly classified under the `Persona` layer.

## Detailed Edits

### `codex/role_manifests/sentinel.md`
- **Change:** `Layer: Observability (Layer 1)` $\rightarrow$ `Layer: Persona (Observability Overlay)`

## Risk Assessment
- **Risk:** Extremely Low. This is a metadata/labeling change that does not affect the functional logic of the Sentinel's `log_query` or `log_summarizer` duties.
- **Impact:** Improves documentation consistency and prevents false positives during Orchestrator audits.

## Verification Plan
1. Read `codex/role_manifests/sentinel.md` using `filesystem:read`.
2. Confirm the `Layer` field reflects `Persona (Observability Overlay)`.
3. Verify that the change does not break any existing `role_sentinel` continuous task logic.