## 1. Learning Objective

Test whether an engineer can plan a stable passive transfer that threads `transfer_cube` through a gated approach funnel and a narrow clearance opening without inventing hidden actuation, moving benchmark fixtures, or relying on unsupported geometry changes.

## 2. Environment Geometry

- `left_start_pad`: static landing pad centered at `[-225, 0, 8]` with size `[150, 130, 16]`.
- `left_approach_wall`: static guide rail centered at `[-110, -34, 42]` with size `[70, 6, 60]`.
- `gate_wall`: static wall centered at `[0, 0, 66]` with outer size `[20, 124, 132]` and a centered clearance opening roughly `[60, 100]` mm in the window plane.
- `right_approach_wall`: static guide rail centered at `[-110, 34, 42]` with size `[70, 6, 60]`.
- `right_goal_pad`: static landing pad centered at `[225, 0, 8]` with size `[150, 130, 16]`.

The opening through `gate_wall` is the clearance gate. The guide rails create a funnel-like lead-in so the handoff can focus on staged alignment, opening width, and wall thickness rather than on a completely open approach.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - cube edge length is randomized through `radius_mm` in the range `[17, 19]` mm, which corresponds to an edge length range of `34-38` mm.
- Nominal start position: `[-252, 0, 120]`
- Runtime jitter: `[5, 5, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[180, -45, 22]`, max_mm `[295, 45, 76]`
- `forbid_zones`: none beyond the benchmark-owned `gate_wall` and approach rails
- `build_zone_mm`: min_mm `[-320, -160, 0]`, max_mm `[330, 150, 190]`

## 5. Simulation Bounds

- min_mm `[-360, -200, -20]`
- max_mm `[360, 200, 220]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 55 USD`, `max_weight <= 2500 g`
- All benchmark-owned geometry is static; there is no hidden powered gate, hinge, launcher, or moving wall.

## 7. Success Criteria

- Success if `transfer_cube` ends inside `goal_zone_mm` after passing through the gate opening.
- Fail if the payload starts outside the build zone, overlaps the frame at spawn, or leaves `simulation_bounds_mm`.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the pads, the guide rails, the framed clearance opening, and the passive transfer path.
- `benchmark_definition.yaml` mirrors the declared zones, start pose, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` mirrors the approved geometry for preview and review.
