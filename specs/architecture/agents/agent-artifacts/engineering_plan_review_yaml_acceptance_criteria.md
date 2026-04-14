# engineering_plan_review_yaml Acceptance Criteria

## Role of the File

This file family is the engineering plan review decision/comments pair.
It is worth being a dedicated artifact because the engineering plan-quality gate must be deterministic, reviewable, and attached to the exact seeded revision.

## Hard Requirements

- The decision YAML is stage-canonical and revision-specific.
- The comments YAML is factual, evidence-based, and grounded in the current engineering plan package.
- Checklist keys match the expected engineering plan-review schema.
- The review package includes the engineering plan review manifest.
- Decision and comments files refer to the same stage, round, and revision.

## Quality Criteria

- The comments call out concrete plan-quality issues, not generic dissatisfaction.
- The checklist maps to the actual engineering handoff contract and not to invented review categories.
- The decision, comments, and plan text are internally consistent.

## Reviewer Look-Fors: File Antipatterns to Look For

- The decision and comments disagree about the stage, revision, or outcome.
- The package relies on stale manifest data or a stale plan snapshot.
- The checklist invents keys or omits required stage-canonical fields.
- The comments do not explain what in the engineering plan package triggered the decision.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
