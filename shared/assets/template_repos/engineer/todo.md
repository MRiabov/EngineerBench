# TODO List

## Phase 1: Ground the Starter

- [ ] Confirm `benchmark_definition.yaml` and `benchmark_assembly_definition.yaml`
  are read-only inputs for the current workspace.
- [ ] Keep `starter_stub_block` and `starter_stub_assembly` stable until a real
  task-specific revision is written.

## Phase 2: Keep The Planner Artifacts Aligned

- [ ] Keep `engineering_plan.md` aligned with `assembly_definition.yaml`
  and `solution_plan_evidence_script.py`.
- [ ] Keep the evidence scene compact and non-exploded so the starter remains
  easy to inspect.

## Phase 3: Cross-Check Coherence

- [ ] Verify the part label, assembly label, and evidence script all use the
  same starter identifiers.
- [ ] Verify the declared cost and weight totals match the YAML and the plan.
- [ ] Verify the scene contains one visible block and nothing that looks like a
  solved mechanism.

## Phase 4: Handoff Ready

- [ ] Leave benchmark-owned files unchanged.
- [ ] Keep the workspace starter-like rather than solved.
- [ ] Replace the stub with task-specific engineering labels only when the real
  plan is ready.
