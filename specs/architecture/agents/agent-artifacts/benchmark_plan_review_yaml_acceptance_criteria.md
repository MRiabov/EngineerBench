# benchmark_plan_review_yaml Acceptance Criteria

## Role of the File

This file family is the benchmark plan review decision/comments pair.
It is worth being a dedicated artifact because it persists the plan-quality gate in a deterministic form that later routing and seed repair can inspect.

## Hard Requirements

- The decision YAML is stage-canonical and revision-specific.
- The comments YAML is factual, evidence-based, and grounded in the current benchmark plan package.
- Checklist keys match the expected benchmark plan-review schema.
- The review package includes the benchmark plan review manifest.
- Decision and comments files refer to the same stage, round, and revision.

## Quality Criteria

- The comments explain the exact problem and the concrete fix, not just the verdict.
- The checklist items map to the actual benchmark handoff contract rather than generic review language.
- The decision and comments tell the same story about the current package.

## Reviewer Look-Fors: File Antipatterns to Look For

- The decision and comments disagree about the stage, revision, or outcome.
- The review uses stale manifest data or a stale package snapshot.
- The checklist introduces invented keys or omits required stage-canonical keys.
- The review comments are vague enough that a replanning agent would still have to guess.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
