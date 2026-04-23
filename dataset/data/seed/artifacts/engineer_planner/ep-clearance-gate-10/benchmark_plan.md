## 1. Learning Objective

Test whether an engineer can plan a stable passive transfer that threads `transfer_cube` through a stepped clearance tunnel without inventing hidden actuation, moving benchmark fixtures, or relying on unsupported geometry changes.

## 2. Environment Geometry

- `left_start_pad`: static landing pad centered at `[-225, 0, 8]` with size `[150, 130, 16]`.
- `front_gate_wall`: static lower wall centered at `[0, -6, 58]` with outer size `[20, 88, 96]`, rotated 8 degrees around the vertical axis, and a centered clearance opening roughly `[48, 70]` mm in the wall plane.
- `step_plinth`: static low plinth centered at `[38, -60, 18]` with size `[104, 14, 12]`, acting as a shallow ledge under the tunnel.
- `rear_gate_wall`: static deeper wall centered at `[74, 8, 72]` with outer size `[20, 94, 104]`, rotated -6 degrees around the vertical axis, and a centered clearance opening roughly `[52, 78]` mm in the wall plane.
- `right_goal_pad`: static landing pad centered at `[225, 0, 8]` with size `[150, 130, 16]`.

The paired wall openings form the stepped clearance tunnel. The lower plinth and offset rear wall add depth so the handoff has to manage lateral offset, vertical clearance, and a shallow ledge instead of a single flat slot.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - cube edge length is randomized through `radius_mm` in the range `[16, 18]` mm, which corresponds to an edge length range of `32-36` mm.
- Nominal start position: `[-250, -8, 40]`
- Runtime jitter: `[6, 5, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[188, -36, 22]`, max_mm `[302, 36, 78]`
- `forbid_zones`: none beyond the benchmark-owned `front_gate_wall`, `step_plinth`, and `rear_gate_wall`
- `build_zone_mm`: min_mm `[-320, -160, 0]`, max_mm `[330, 155, 190]`

## 5. Simulation Bounds

- min_mm `[-360, -200, -20]`
- max_mm `[360, 200, 220]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 55 USD`, `max_weight <= 2500 g`
- All benchmark-owned geometry is static; there is no hidden powered gate, hinge, launcher, or moving wall.

## 7. Success Criteria

- Success if `transfer_cube` ends inside `goal_zone_mm` after passing through the stepped tunnel opening.
- Fail if the payload starts outside the build zone, overlaps the frame at spawn, or leaves `simulation_bounds_mm`.

## 8. Planner Artifacts

- `todo.md` captures the implementation checklist for the pads, the stepped gate walls, the low plinth, and the passive transfer path.
- `benchmark_definition.yaml` mirrors the declared zones, start pose, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` mirrors the approved geometry for preview and review.
