# engineering_plan.md Acceptance Criteria

## Role of the File

`engineering_plan.md` is the engineering planner narrative that makes the handoff readable to humans and downstream engineering roles.
It binds the solution approach, exact inventory names, assumptions, calculations, operating envelope, and intended sequence of work in a stable, reviewable form.

## Hard Requirements

- Headings match the engineering planner and engineering plan reviewer contract.
- The plan states the engineering solution clearly.
- Exact identifiers, labels, and file names used elsewhere in the engineering handoff appear where the contract expects them.
- The plan stays consistent with `benchmark_definition.yaml`, `assembly_definition.yaml`, the planner scripts, and review artifacts.
- The plan does not invent benchmark-owned geometry, caps, or unsupported motion.

## Quality Criteria

- The plan is specific enough that engineer coder can start without re-deciding the mechanism shape.
- The narrative is stage-ordered and engineering-owned.
- The plan uses exact engineering names instead of generic placeholders.

## Reviewer Look-Fors: File Antipatterns to Look For

- Generic prose appears where the contract expects exact names or counts.
- Required headings or exact identifier mentions are missing.
- Detailed Calculations subsection headings are complete but out of order, or the CALC row order does not match the subsection order; the validator should report the specific ordering mismatch rather than a generic missing-heading failure.
- The plan conflicts with the YAML files, scripts, or review artifacts.
- Stale benchmark scope or unsupported engineering work appears in the handoff.

## Cross-References

- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
