## 1. Learning Objective

Test whether an engineer can plan a stable passive transfer that threads `transfer_cube` through a canted clearance gate with an overhead shroud without inventing hidden actuation, moving benchmark fixtures, or relying on unsupported geometry changes.

## 2. Environment Geometry

- `left_start_pad`: static landing pad centered at `[-225, 0, 8]` with size `[150, 130, 16]`.
- `gate_wall`: static wall centered at `[0, 6, 66]` with outer size `[22, 128, 128]`, rotated 12 degrees around the vertical axis, and a centered clearance opening roughly `[58, 94]` mm in the gate plane.
- `upper_shroud`: static shroud centered at `[24, 28, 142]` with size `[92, 10, 18]`, acting as a decoy overhang above the opening.
- `right_goal_pad`: static landing pad centered at `[225, 0, 8]` with size `[150, 130, 16]`.

The opening through `gate_wall` is the clearance gate. The canted wall and overhead shroud create a less boxy approach so the handoff can focus on yaw alignment, opening width, and wall thickness rather than on a fully axis-aligned pass.

## 3. Input Objective

- Shape: `cube`
- Label: `transfer_cube`
- Static randomization:
  - cube edge length is randomized through `radius_mm` in the range `[17, 19]` mm, which corresponds to an edge length range of `34-38` mm.
- Nominal start position: `[-248, 10, 119]`
- Runtime jitter: `[6, 5, 4]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[190, -35, 22]`, max_mm `[300, 35, 76]`
- `forbid_zones`: none beyond the benchmark-owned `gate_wall` and `upper_shroud`
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

- `todo.md` captures the implementation checklist for the pads, the canted gate wall, the overhead shroud, and the passive transfer path.
- `benchmark_definition.yaml` mirrors the declared zones, start pose, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` mirrors the approved geometry for preview and review.
