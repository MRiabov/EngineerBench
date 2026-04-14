# solution_script.py Acceptance Criteria

## Role of the File

This is the implemented solution geometry and execution source of truth.
It is worth being a dedicated artifact because the final run, validation, and simulation gates all need the same grounded solution source rather than a loose description of the assembly.

## Hard Requirements

- The script mirrors `assembly_definition.yaml` inventory and motion contract.
- The script exposes the final assembly as expected by the runtime.
- The script is consistent with validation and simulation outputs.
- The script uses exact source-grounded identifiers only.
- The script does not author or duplicate the benchmark payload; that context is injected by the runtime environment.

## Quality Criteria

- The solution implementation is readable enough that the reviewer can compare it against the assembly contract.
- The final assembly is stable and does not rely on invented fallback labels or transient shell state.
- The script stays aligned with the validated totals and with the current revision of the workspace.

## Reviewer Look-Fors: File Antipatterns to Look For

- The implementation drifts from `assembly_definition.yaml`.
- The runtime exposure does not match the final assembly that validation and simulation exercised.
- Invented identifiers, stale geometry, or hidden fallback paths appear.
- The solution only appears valid because of transient state rather than the persisted source.
- Benchmark payload geometry is embedded in the solution source instead of being supplied by the environment.

## Cross-References

- `specs/architecture/agents/handover-contracts.md`
- `specs/architecture/agents/artifacts-and-filesystem.md`
- `specs/architecture/agents/tools.md`
