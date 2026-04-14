# Benchmark Planner Handoff Contract

Use this reference when drafting or reviewing the benchmark planner handoff.

## File Set

Required planner-owned files:

- `benchmark_plan.md`
- `todo.md`
- `benchmark_definition.yaml`
- `benchmark_assembly_definition.yaml`
- `benchmark_plan_evidence_script.py`

`benchmark_script.py` is downstream benchmark-coder context and should not be expected before plan approval.

The planner handoff is YAML-backed. Populate the YAML files so downstream roles can treat them as the machine-readable source of truth, and keep the planner evidence script aligned with those YAML fields.

For file-level acceptance criteria, also read `specs/architecture/agents/agent-artifacts/README.md` and the matching contracts for `benchmark_plan.md`, `todo.md`, `benchmark_definition.yaml`, `benchmark_assembly_definition.yaml`, and `benchmark_plan_evidence_script.py`.

## Source Hierarchy

Prefer the strictest current contract in this order:

1. `specs/desired_architecture.md`
2. `specs/architecture/agents/*.md`
3. `config/prompts.yaml`
4. this skill

If these sources disagree, stop and resolve the contradiction before submitting the handoff.

## File Ownership

### `benchmark_plan.md`

Describe the benchmark objective, geometry, randomization, benchmark-owned fixtures, and why the challenge is solvable.

### `todo.md`

List the concrete planner-to-coder work items in execution order.

### `benchmark_definition.yaml`

Own the benchmark/task geometry, objective zones, payload, randomization, benchmark-owned fixture metadata, and benchmark estimate fields.

### `benchmark_assembly_definition.yaml`

Own the benchmark-owned fixture structure and motion contract. Keep it schema-valid and benchmark-owned.

### `benchmark_plan_evidence_script.py`

Provide a legible build123d scene that makes the benchmark geometry easy to inspect.

## Consistency Checks

Before submission, verify all of the following:

- `benchmark_plan.md`, `todo.md`, the YAML files, and the evidence script use the same object names and labels.
- Every planner-declared inventory label and selected COTS `part_id` appears in `benchmark_plan.md` at least once as an exact identifier mention.
- The evidence script preserves the same labels, repeated quantities, and COTS identities as the YAML inventory.
- Every length, offset, clearance, and travel limit is formula-backed from declared source geometry, COTS specs, or manufacturing constants. If a value is missing, the handoff is incomplete.
- The planner evidence script is the inspectable source of the planned solution geometry; do not leave geometry implied only in prose.
- Geometry or physics that cannot be derived rigorously should be treated as a hard failure. In practice, weak derivations have repeatedly led to downstream failure, so the handoff should be fixed before submission.
- Any moving fixture position is defined by its joint frame or axis, not by an arbitrary world coordinate.
- Every top-level authored label is unique and not `environment` or `zone_*`.
- `payload.material_id` is a known material from `manufacturing_config.yaml`.
- `payload.start_position` is a top-level field under `payload`.
- The payload stays inside `build_zone` after applying static randomization and runtime jitter.
- Goal and forbid zones do not intersect the payload at spawn.
- Any benchmark-owned moving fixture declares its motion explicitly, with motion topology / DOF profile, motion kind, and clear bounds or controller facts. Include an axis or path reference when applicable.
- The assembly file stays schema-valid and does not rely on template placeholders.
- The evidence script matches the same geometry and does not drift from the YAML.

## Submission Gate

Call `submit_benchmark_plan()` only after the handoff is internally consistent, placeholder-free, and ready for downstream benchmark coding.
