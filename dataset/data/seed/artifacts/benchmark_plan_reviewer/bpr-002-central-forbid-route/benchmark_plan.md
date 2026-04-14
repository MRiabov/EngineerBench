## 1. Learning Objective

Test whether an engineer can route a ball around a central blocker rather than attempting a direct line transfer through an obstructed corridor.

## 2. Environment Geometry

- `left_launch_pad`: box centered at `[-180, 0, 55]` with size `[140, 120, 110]`.
- `central_blocker`: box centered at `[190, 0, 75]` with size `[140, 260, 150]`.
- `upper_route_wall`: guide wall centered at `[260, 110, 60]` with size `[360, 20, 120]`.
- `lower_route_wall`: guide wall centered at `[260, -110, 60]` with size `[360, 20, 120]`.
- `goal_catch_tray`: pocket centered at `[470, 0, 30]` with size `[130, 110, 30]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius in `[28, 30]` mm
- Nominal start position: `[-180, 0, 110]`
- Runtime jitter: `[14, 10, 6]` mm

## 4. Objectives

- `goal_zone`: min `[420, -60, 15]`, max `[520, 60, 110]`
- `forbid_zones`:
  - `central_blocker`: min `[120, -130, 0]`, max `[260, 130, 150]`
- `build_zone`: min `[-240, -180, 0]`, max `[560, 180, 240]`

## 5. Simulation Bounds

- min `[-300, -220, -10]`, max `[620, 220, 280]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 80 USD`, `max_weight <= 1600 g`
- All benchmark-owned parts are static; the challenge should come from the around-obstacle route and jitter tolerance, not benchmark-side actuation.

## 7. Success Criteria

- Success if the ball reaches `goal_zone` without entering the `central_blocker` forbid volume.
- Fail if the ball exits `simulation_bounds` or if planner artifacts imply a shortcut through the blocker.

## 8. Planner Artifacts

- `todo.md` tracks implementation of the launch pad, blocker, route walls, and goal tray.
- `benchmark_definition.yaml` mirrors the route geometry and objective zones.
- `benchmark_assembly_definition.yaml` records benchmark-local cost estimates and confirms zero benchmark-side DOFs.
