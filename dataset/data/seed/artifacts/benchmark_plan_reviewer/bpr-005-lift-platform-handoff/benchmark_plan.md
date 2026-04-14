## 1. Learning Objective

Test whether an engineer can receive a ball from a benchmark-owned moving lift platform and guide it into an elevated goal without colliding with the platform travel envelope.

## 2. Environment Geometry

- `lift_platform`: tray centered nominally at `[0, 0, 125]` with size `[120, 120, 18]`; benchmark-side motion is one `slide_z` axis only.
- `platform_guide_column`: tower centered at `[0, 0, 120]` with size `[70, 70, 240]`.
- `handoff_bridge`: static shelf centered at `[150, 0, 185]` with size `[90, 110, 20]`.
- `goal_shelf`: static shelf centered at `[230, 0, 230]` with size `[140, 120, 25]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius fixed at `24` mm
- Nominal start position: `[0, 0, 125]`
- Runtime jitter: `[6, 6, 5]` mm

## 4. Objectives

- `goal_zone`: min `[180, -55, 215]`, max `[280, 55, 290]`
- `forbid_zones`:
  - `platform_travel_clearance`: min `[35, -90, 0]`, max `[95, 90, 210]`
- `build_zone`: min `[-180, -160, 0]`, max `[320, 160, 340]`

## 5. Simulation Bounds

- min `[-240, -200, -10]`, max `[380, 200, 380]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 100 USD`, `max_weight <= 1500 g`
- Benchmark-owned motion must stay limited to one `slide_z` platform axis; no extra benchmark-side swing arms or gates are permitted.

## 7. Success Criteria

- Success if the ball can transfer from the moving platform into `goal_zone` without entering `platform_travel_clearance`.
- Fail if the payload exits `simulation_bounds` or if benchmark geometry requires undeclared motion beyond the platform lift axis.

## 8. Planner Artifacts

- `todo.md` tracks the lift platform, guide column, handoff bridge, and goal shelf implementation.
- `benchmark_definition.yaml` mirrors the platform clearance keep-out and elevated goal geometry.
- `benchmark_assembly_definition.yaml` records the single platform lift axis and benchmark-local costs.
