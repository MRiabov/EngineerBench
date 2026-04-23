## 1. Learning Objective

Test whether an engineer can plan a stable passive transfer that threads `projectile_ball` through a widening capture mouth, then through a tight goal throat, without inventing hidden actuation, moving benchmark fixtures, or relying on unsupported geometry changes.

## 2. Environment Geometry

- `left_start_pad`: static landing pad centered at `[-245, 0, 8]` with size `[160, 140, 16]`.
- `funnel_left_outer`: static left guide wall centered at `[-75, 76, 36]` with size `[110, 16, 72]`.
- `funnel_right_outer`: static right guide wall centered at `[-75, -76, 36]` with size `[110, 16, 72]`.
- `funnel_left_mid`: static left guide wall centered at `[75, 58, 36]` with size `[130, 16, 72]`.
- `funnel_right_mid`: static right guide wall centered at `[75, -58, 36]` with size `[130, 16, 72]`.
- `funnel_left_inner`: static left throat guide centered at `[224, 36, 36]` with size `[118, 16, 72]`.
- `funnel_right_inner`: static right throat guide centered at `[224, -36, 36]` with size `[118, 16, 72]`.
- `goal_throat_frame`: static throat frame centered at `[295, 0, 42]` with outer size `[20, 104, 84]` and a centered opening roughly `[52, 64]` mm in the throat plane.
- `right_goal_pad`: static landing pad centered at `[370, 0, 8]` with size `[120, 120, 16]`.

The funnel narrows in steps from the broad capture mouth into the throat frame. The key challenge is preserving clearance through the narrowing corridor while keeping the payload centered enough to reach the throat opening.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - sphere radius is randomized through `radius_mm` in the range `[18, 20]` mm.
- Nominal start position: `[-255, 0, 36]`
- Runtime jitter: `[6, 6, 3]` mm

## 4. Objectives

- `goal_zone_mm`: min_mm `[315, -40, 20]`, max_mm `[390, 40, 85]`
- `forbid_zones`:
- `funnel_left_outer`: approx AABB `[-130, 68, 0]` to `[-20, 84, 72]`
- `funnel_right_outer`: approx AABB `[-130, -84, 0]` to `[-20, -68, 72]`
- `funnel_left_mid`: approx AABB `[10, 50, 0]` to `[140, 66, 72]`
- `funnel_right_mid`: approx AABB `[10, -66, 0]` to `[140, -50, 72]`
- `funnel_left_inner`: approx AABB `[165, 28, 0]` to `[283, 44, 72]`
- `funnel_right_inner`: approx AABB `[165, -44, 0]` to `[283, -28, 72]`
  - `goal_throat_frame`: approx AABB `[285, -52, 0]` to `[305, 52, 84]`
- `build_zone_mm`: min_mm `[-340, -180, 0]`, max_mm `[430, 180, 240]`

## 5. Simulation Bounds

- min_mm `[-380, -220, -20]`
- max_mm `[460, 220, 300]`

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
