## 1. Learning Objective

Test whether an engineer can guide a low-friction cube around a central blocker using geometry that captures slip instead of assuming ideal sticking contact.

## 2. Environment Geometry

- `entry_funnel`: static funnel centered at `[-250, 0, 35]` with size `[120, 140, 45]`.
- `center_collision_block`: static blocker centered at `[165, 0, 60]` with size `[110, 180, 120]`.
- `side_guide_left`: static wall centered at `[210, 90, 40]` with size `[320, 18, 80]`.
- `side_guide_right`: static wall centered at `[210, -90, 40]` with size `[320, 18, 80]`.
- `goal_pocket`: static capture pocket centered at `[325, 0, 22]` with size `[62, 70, 24]`; the taper into that pocket is intended to arrest the cube despite the low-friction contact.

## 3. Input Objective

- Shape: `cube`
- Label: `slider_cube`
- Static randomization: none beyond the fixed cube geometry
- Nominal start position: `[-280, 0, 24]`
- Runtime jitter: `[14, 12, 3]` mm

## 4. Objectives

- `goal_zone`: min `[290, -35, 10]`, max `[360, 35, 70]`
- `forbid_zones`:
  - `center_collision_block`: min `[110, -90, 0]`, max `[220, 90, 120]`
- `build_zone`: min `[-340, -140, 0]`, max `[400, 140, 180]`

## 5. Simulation Bounds

- min `[-380, -180, -10]`, max `[450, 180, 220]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 55 USD`, `max_weight <= 1200 g`
- All benchmark-owned geometry is static; the intended challenge is low-friction routing, even though the final pocket has been tightened to keep the cube from rattling once it arrives.

## 7. Success Criteria

- Success if the cube reaches `goal_zone` without entering `center_collision_block`.
- Fail if the cube exits `simulation_bounds` or if the route depends on undeclared moving benchmark parts.

## 8. Planner Artifacts

- `todo.md` tracks the funnel, blocker, guide walls, and goal pocket implementation.
- `benchmark_definition.yaml` mirrors the low-friction routing geometry and cost caps.
- `benchmark_assembly_definition.yaml` records the static benchmark-local parts and confirms zero DOFs.
