## 1. Learning Objective

Test whether an engineer can plan a stable passive transfer that threads `projectile_ball` through rounded outer rails and then through the tighter throat opening, without inventing hidden actuation, moving benchmark fixtures, or relying on unsupported geometry changes.

## 2. Environment Geometry

- `left_start_pad`: static landing pad centered at `[-245, 0, 8]` with size `[160, 140, 16]`.
- `funnel_left_outer`: static rounded left outer rail centered at `[-75, 82, 36]` with a rounded profile instead of a box wall.
- `funnel_right_outer`: static rounded right outer rail centered at `[-75, -82, 36]` with a rounded profile instead of a box wall.
- `funnel_left_mid`: static left guide wall centered at `[95, 62, 36]` with size `[138, 16, 72]`.
- `funnel_right_mid`: static right guide wall centered at `[95, -58, 36]` with size `[138, 16, 72]`.
- `funnel_left_inner`: static left throat guide centered at `[245, 34, 36]` with size `[126, 16, 72]`.
- `funnel_right_inner`: static right throat guide centered at `[245, -34, 36]` with size `[126, 16, 72]`.
- `goal_throat_frame`: static throat frame centered at `[348, 0, 42]` with outer size `[20, 94, 84]` and a centered opening roughly `[42, 62]` mm in the throat plane.
- `right_goal_pad`: static landing pad centered at `[422, 0, 8]` with size `[110, 120, 16]`.

The funnel narrows in steps from the broad capture mouth into the centered throat frame. The key challenge is preserving clearance through the narrowing corridor while keeping the payload centered enough to reach the throat opening despite the near-worst-case radius.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - sphere radius is randomized through `radius_mm` in the range `[19.4, 19.8]` mm.
- Nominal start position: `[-258, 0, 156]`
- Runtime jitter: `[6, 6, 3]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[372, -40, 20]`, max_mm `[462, 40, 85]`
- `forbid_zones`:
  - `funnel_left_outer`: approx AABB `[-134, 73, 0]` to `[-22, 91, 72]`
  - `funnel_right_outer`: approx AABB `[-134, -91, 0]` to `[-22, -73, 72]`
  - `funnel_left_mid`: approx AABB `[25, 54, 0]` to `[165, 70, 72]`
  - `funnel_right_mid`: approx AABB `[25, -70, 0]` to `[165, -54, 72]`
  - `funnel_left_inner`: approx AABB `[181, 26, 0]` to `[309, 42, 72]`
  - `funnel_right_inner`: approx AABB `[181, -42, 0]` to `[309, -26, 72]`
  - `goal_throat_frame`: approx AABB `[338, -47, 0]` to `[358, 47, 84]`
- `build_zone_mm`: min_mm `[-340, -180, 0]`, max_mm `[490, 180, 240]`

## 5. Simulation Bounds

- min_mm `[-380, -220, -20]`
- max_mm `[520, 220, 300]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 72 USD`, `max_weight <= 1500 g`
- All benchmark-owned geometry is static; there is no hidden powered gate, hinge, launcher, or moving wall.

## 7. Success Criteria

- Success if `projectile_ball` ends inside `goal_zone_mm` after passing through the throat opening.
- Fail if the payload starts outside the build zone, overlaps a benchmark fixture at spawn, or leaves `simulation_bounds_mm`.

## 8. Planner Artifacts

- `benchmark_definition.yaml` mirrors the declared zones, start pose, and cost caps.
- `benchmark_assembly_definition.yaml` records the benchmark-local manufactured parts and confirms the benchmark is fully static.
- `benchmark_plan_evidence_script.py` mirrors the approved geometry for preview and review.
