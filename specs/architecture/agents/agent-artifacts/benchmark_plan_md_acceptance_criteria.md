# benchmark_plan.md Acceptance Criteria

## Role of the File

`benchmark_plan.md` is the benchmark planner narrative that makes the handoff readable to humans and downstream benchmark roles.
It binds the benchmark objective, inventory names, geometry, randomization, and intended sequence of work in a stable, reviewable form.

## Hard Requirements

- Headings match the benchmark planner and benchmark plan reviewer contract.
- The plan states the benchmark objective clearly.
- Exact identifiers, labels, and file names used elsewhere in the benchmark handoff appear where the contract expects them.
- The plan stays consistent with `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, the planner scripts, and review artifacts.
- The plan does not invent engineering scope, solution parts, cost, or unsupported motion.

## Quality Criteria

- The plan is specific enough that benchmark coder can start without re-deciding the benchmark shape.
- The narrative is stage-ordered and benchmark-owned.
- The plan uses exact benchmark names instead of generic placeholders.

## Reviewer Look-Fors: File Antipatterns to Look For

- Generic prose appears where the contract expects exact names or counts.
- Required headings or exact identifier mentions are missing.
- The plan conflicts with the YAML files, scripts, or review artifacts.
- Stale engineering scope or unsupported benchmark work appears in the handoff.

## Cross-References

- `specs/architecture/agents/roles.md`
- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
