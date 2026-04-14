# validation_results.json Acceptance Criteria

## Role of the File

This file captures the latest-revision deterministic validation evidence.
It is worth being a dedicated artifact because later gates need an exact, parseable record of the deterministic pass or fail state before any LLM judgment happens.

## Hard Requirements

- The file reflects the current revision only.
- The file is schema-valid and parseable.
- The file matches the seeded workspace state.
- The file is sufficient to explain deterministic pass/fail outcomes before LLM evaluation.

## Quality Criteria

- The failure or success reason is specific enough to reproduce the gating outcome.
- The file is stable enough that later reviewers can compare it against the workspace without guesswork.
- The result does not smuggle in stale or approximate state.

## Reviewer Look-Fors: File Antipatterns to Look For

- The result comes from another revision or another seeded task.
- The file is parseable but too vague to explain why validation passed or failed.
- Deterministic fields were left implicit instead of being materialized.
- The validation record contradicts the visible workspace state.

## Cross-References

- `specs/architecture/application-acceptance-criteria.md`
- `specs/architecture/evals-architecture.md`
- `specs/architecture/agents/handover-contracts.md`
