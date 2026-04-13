# solution_plan_evidence_script.py Acceptance Criteria

## Role of the File

This script is the inspectable source for the planned solution geometry.
It is worth being a dedicated artifact because the engineering planner needs a previewable, reviewable version of the proposed assembly, not just prose about the plan.

## Hard Requirements

- The script matches the proposed assembly contract.
- The script is consistent with `assembly_definition.yaml`.
- The script stays solution-side and does not rewrite benchmark-owned context.
- The script does not use exploded-layout presentation; if presentation needs that treatment, it belongs in `solution_plan_technical_drawing_script.py`.
- The script is legible enough for downstream review and visual inspection.

## Quality Criteria

- The script expresses the proposed assembly clearly enough that the next role can see the intended solution shape.
- The evidence scene is compact and readable rather than a hidden implementation detail dump.
- The same identifiers and structure appear in the plan text and the solution-side YAML.

## Reviewer Look-Fors

- The script drifts from `assembly_definition.yaml`.
- Benchmark-owned context is edited or reinterpreted as solution scope.
- The script is too opaque to review or hides unsupported geometry.
- The script uses exploded-layout presentation instead of keeping that presentation in another planning artifact.
- The evidence scene no longer matches the current revision of the engineering plan package.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/roles.md`
