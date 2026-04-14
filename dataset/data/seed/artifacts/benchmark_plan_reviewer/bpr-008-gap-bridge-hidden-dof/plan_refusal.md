---
role: benchmark_coder
reasons:
  - CONTRADICTORY_CONSTRAINTS
---

The seeded benchmark handoff is not a passive gap-transfer fixture as written.

Evidence:

- `benchmark_assembly_definition.yaml` gives `bridge_reference_table` a `slide_y` DOF with `ON_OFF` control.
- `benchmark_plan.md` describes the bridge reference table as effectively passive, which conflicts with the motion metadata.
- The added self-centering correction introduces benchmark-side actuation semantics that are not justified by the surrounding benchmark narrative.

Attempted fixes:

- Reviewed the declared zone geometry and static geometry assumptions.
- Compared the planner narrative against the assembly motion metadata and render evidence.
- Looked for a passive reinterpretation that would preserve the bridge as a non-actuated fixture.

Requested planner changes:

- Remove the benchmark-side `slide_y` DOF from `bridge_reference_table`.
- Keep the bridge reference table static if the benchmark is intended to remain passive.
- If motion is required, declare it explicitly in the benchmark objective and fixture contract instead of hiding it in the assembly metadata.
