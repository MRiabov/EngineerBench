# benchmark_execution_review_yaml Acceptance Criteria

## Role of the File

This file family is the benchmark execution review decision/comments pair.
It is worth being a dedicated artifact because it captures the post-implementation verdict and the reviewer evidence that determined whether the benchmark implementation matches the approved plan.

## Hard Requirements

- The decision YAML is stage-canonical and revision-specific.
- The comments YAML is factual, evidence-based, and grounded in the latest benchmark implementation.
- Checklist keys match the expected benchmark execution-review schema.
- The review package includes the benchmark execution review manifest.
- Decision and comments files refer to the same latest implementation package.

## Quality Criteria

- The comments identify concrete implementation mismatches or confirmations, not generic praise or criticism.
- The checklist gives later replanning a clear path to repair specific failures.
- The verdict aligns with the benchmark geometry, motion, validation evidence, and the config-driven benchmark-payload observation window from `config/agents_config.yaml` (`benchmark_payload_observation.window_s`, default `1.5s`).

## Reviewer Look-Fors: File Antipatterns to Look For

- The decision and comments disagree or reference different revisions.
- The package relies on stale benchmark evidence or an old manifest.
- The checklist invents keys or omits required stage-canonical fields.
- The comments do not explain the actual implementation evidence that drove the decision.
- The comments treat late benchmark-payload drift after the configured observation window as a benchmark-simulation failure.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
