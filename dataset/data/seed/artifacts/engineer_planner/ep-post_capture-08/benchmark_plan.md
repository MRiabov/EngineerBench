## 1. Learning Objective

Test whether an engineer can deliver `projectile_ball` into a post-centered capture region while respecting a fixed tray lip and purely static benchmark geometry.

## 2. Environment Geometry

- `left_start_pad`: static launch pad centered at [-225.0, 0, 10] with size [140, 120, 20].
- `goal_capture_tray`: static landing tray centered at [455.0, 0, 10] with size [180.0, 180.0, 20].
- `capture_post`: static vertical post centered at [455.0, 0, 57.5] with size [20.0, 20.0, 75.0].
- `goal_lip`: static downstream retention lip centered at [539.0, 0, 27.0] with size [12.0, 180.0, 14.0]; this is read-only benchmark geometry.

The route is intentionally simple. The challenge is the final capture precision around the post and the lip-aware retention envelope, not hidden benchmark-side actuation.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius_mm in `[18, 20]` mm
- Nominal start position: [-235.0, 0, 70]
- Runtime jitter: [10.0, 10.0, 5.0] mm

## 4. Objectives

- `goal_zone_mm`: min_mm [415.0, -45, 20], max_mm [495.0, 45, 110]
- `build_zone_mm`: min_mm [-320, -180, 0], max_mm [620, 180, 240]

## 5. Simulation Bounds

- min_mm [-360, -220, -20], max_mm [660, 220, 300]

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 80 USD`, `max_weight <= 1400 g`
- The benchmark is fully static; the post-capture behavior must come from the engineered solution and the declared geometry only.

## 7. Success Criteria

- Success if the ball comes to rest in `goal_zone_mm` around `capture_post` without leaving `simulation_bounds_mm`.
- Fail if the plan depends on undeclared moving benchmark parts or if the payload cannot physically fit into the post-centered capture region.

## 8. Planner Artifacts

- `todo.md` tracks the post-capture lane, anchors, and goal-side retention details.
- `benchmark_definition.yaml` mirrors the static post-capture geometry and caps.
- `benchmark_assembly_definition.yaml` records the static benchmark-local parts and confirms the benchmark is fully static.
