## 1. Learning Objective

Test whether an engineer can plan a stable passive transfer that threads `transfer_cube` through a layered clearance tunnel with front and rear gate walls without inventing hidden actuation, moving benchmark fixtures, or relying on unsupported geometry changes.

## 2. Environment Geometry

- `left_start_pad`: static landing pad centered at `[-225, 0, 8]` with size `[150, 130, 16]`.
- `front_gate_wall`: static wall centered at `[0, 0, 64]` with outer size `[20, 118, 124]` and a centered clearance opening roughly `[62, 96]` mm in the front window plane.
- `rear_gate_wall`: static wall centered at `[78, 4, 70]` with outer size `[20, 118, 124]` and a slightly tighter clearance opening roughly `[58, 92]` mm in the rear window plane.
- `right_goal_pad`: static landing pad centered at `[225, 0, 8]` with size `[150, 130, 16]`.

The openings through `front_gate_wall` and `rear_gate_wall` are the clearance tunnel. The twin walls create a layered alignment problem so the handoff can focus on depth staging, opening width, and wall thickness rather than on a single-pass window.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - cube edge length is randomized through `radius_mm` in the range `[17, 19]` mm, which corresponds to an edge length range of `34-38` mm.
- Nominal start position: `[-250, -6, 38]`
- Runtime jitter: `[6, 6, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[185, -40, 22]`, max_mm `[295, 40, 76]`
- `forbid_zones`: none beyond the benchmark-owned `front_gate_wall` and `rear_gate_wall`
- `build_zone_mm`: min_mm `[-320, -160, 0]`, max_mm `[330, 155, 190]`

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

- `todo.md` captures the implementation checklist for the pads, the front and rear gate walls, and the passive transfer path.
- `benchmark_definition.yaml` mirrors the declared zones, start pose, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` mirrors the approved geometry for preview and review.
