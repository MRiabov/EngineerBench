# benchmark_assembly_definition.yaml Acceptance Criteria

## Role of the File

`benchmark_assembly_definition.yaml` is the read-only benchmark-owned fixture and motion contract copied into engineer and reviewer workspaces.
It is worth being a dedicated artifact because it captures the benchmark-side motion facts that downstream roles must honor without reinterpreting them as engineer-owned scope.

## Hard Requirements

- The file schema-validates as a full `AssemblyDefinition` artifact.
- Every referenced benchmark-owned object exists in `benchmark_definition.yaml`.
- Fixture structure, labels, and quantities match `benchmark_plan.md` and the benchmark planner scripts exactly.
- Moving fixtures declare explicit motion facts, including the supported motion type, bounds, and controller-visible limits.
- One-axis motion is used per moving fixture unless the benchmark contract explicitly says otherwise.
- Any anchor-style motion metadata names `rot_deg` explicitly instead of relying on an implied default pose.
- The file stays read-only for downstream roles and does not import engineer-owned parts or solution-side assemblies.

## Quality Criteria

- Motion topology is explicit enough that reviewer inspection can reconstruct the intended benchmark behavior.
- Stable labels and part references survive into downstream intake without rename drift.
- The motion contract is legible enough for engineer planning and reviewer comparison.

## Reviewer Look-Fors: File Antipatterns to Look For

- Hidden motion, contradictory motion, or unsupported motion declarations appear.
- The benchmark-owned fixture does not match the plan, evidence, or the object inventory.
- Motion facts are missing for a moving fixture that downstream roles must observe.
- The file leaks engineer-owned parts, solution assemblies, or invented fixtures into benchmark scope.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/simulation.md`
