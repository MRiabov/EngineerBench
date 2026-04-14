# benchmark_script.py Acceptance Criteria

## Role of the File

This is the approved benchmark geometry source and read-only downstream context.
It is worth being a dedicated artifact because coder and reviewer roles must consume the exact benchmark geometry that was approved, not a reinterpreted copy.

## Hard Requirements

- The script matches the benchmark contract exactly.
- The script is not overwritten by downstream roles.
- The script preserves exact labels, quantities, and motion facts.
- The script can be consumed by coders and reviewers without reinterpretation.

## Quality Criteria

- The benchmark geometry is stable enough to serve as the downstream source of truth.
- The script is clear enough that downstream roles can compare their own output against it mechanically.
- The object inventory and motion facts remain exact across the current revision.

## Reviewer Look-Fors: File Antipatterns to Look For

- Benchmark-owned geometry drifts from the approved plan.
- Labels, quantities, or motion facts change during materialization.
- The script contains accidental solution-side edits or hidden fallback behavior.
- The downstream workspace would need to guess what the benchmark geometry means.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/tools.md`
