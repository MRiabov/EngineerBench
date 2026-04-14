# engineering_execution_review_yaml Acceptance Criteria

## Role of the File

This file family is the engineering execution review decision/comments pair.
It is worth being a dedicated artifact because the final execution gate must record the exact evidence-backed verdict against the latest implementation.

## Hard Requirements

- The decision YAML is stage-canonical and revision-specific.
- The comments YAML is factual, evidence-based, and grounded in the latest implementation.
- Checklist keys match the expected engineering execution-review schema.
- The review package includes the engineering execution review manifest.
- Decision and comments files refer to the same latest implementation package.

## Quality Criteria

- The comments identify concrete deviations, robustness risks, or confirmations, not generic feedback.
- The checklist helps a later repair loop understand which exact items still fail.
- The verdict aligns with validation, simulation, and any required render evidence.

## Reviewer Look-Fors: File Antipatterns to Look For

- The decision and comments disagree or reference different revisions.
- The package relies on stale manifest data or stale simulation evidence.
- The checklist invents keys or omits required stage-canonical fields.
- The comments do not explain the actual implementation evidence that drove the decision.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
