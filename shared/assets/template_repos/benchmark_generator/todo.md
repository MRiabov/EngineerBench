# TODO List - Benchmark Generator

## Planning

- [ ] Confirm the benchmark stays in the simple rigid-body, gravity-only
  family.
- [ ] Define the bridge-gap static geometry and the sphere input object in
  `benchmark_plan.md`.
- [ ] Write the goal zone, forbid zone, and build zone so the bridge span is
  unambiguous.
- [ ] Record the cost and weight envelope for the passive fixture family.

## Handoff Artifacts

- [ ] Write `benchmark_definition.yaml` with rigid-body-only scope and explicit
  bounds.
- [ ] Write `benchmark_assembly_definition.yaml` with a schema-valid passive
  fixture handoff.
- [ ] Keep any benchmark-side motion out of scope unless it remains passive
  and reviewable.

## Validation

- [ ] Verify geometry, objective clearance, and runtime jitter robustness.
- [ ] Reject any actuators or soft-material branches before submission.
- [ ] Call `submit_benchmark_plan()` only after the handoff files are internally
  consistent.
