# assembly_definition.yaml Acceptance Criteria

## Role of the File

`assembly_definition.yaml` is the engineer-owned contract for solution-side parts, constraints, pricing, totals, and final assembly.
It is worth being a dedicated agent artifact because it is the main binding between the planned solution, the concrete geometry, the cost model, and the final review gate.

## Hard Requirements

- The file schema-validates before execution continues.
- `manufactured_parts` include method, material, and method-specific costing fields.
- `final_assembly` includes the subassemblies, reuse, and joints that the solution actually exposes.
- Planner-owned caps from `benchmark_definition.yaml` are copied through exactly and remain internally consistent.
- Planner-target unit cost and weight fields are derived from validated totals, not invented later.
- Motion anchors in `motion_forecast` name explicit `rot_deg` poses, and an omitted rotation is a validation failure rather than an implied identity pose.
- The file stays internally consistent with `engineering_plan.md`, `todo.md`, and `benchmark_definition.yaml`.

## Quality Criteria

- The assembly is manufacturable and stable within the approved caps.
- Exact derived totals are materialized at seed time and do not depend on later inference.
- The solution scope is clearly separated from benchmark-owned read-only context.
- Motion metadata is explicit enough for simulation, swept-clearance validation, and reviewer comparison.

## Reviewer Look-Fors: File Antipatterns to Look For

- Placeholder values, stale revision data, or schema drift appear.
- Component rows are backed by invented prices, manufacturers, or source IDs.
- Benchmark-owned geometry is treated as editable engineer scope.
- Final-assembly totals do not reconcile with the grounded costing and motion contract.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/CAD-and-other-infra.md`
