## 1. Learning Objective

Test whether an engineer can widen capture upstream and then funnel a ball into a narrow goal throat without relying on oversized or ambiguous benchmark geometry.

## 2. Environment Geometry

- `capture_bowl`: static flare centered at `[120, 0, 120]` with size `[260, 180, 80]`.
- `throat_left`: static wall centered at `[420, 17, 35]` with size `[180, 12, 70]`.
- `throat_right`: static wall centered at `[420, -17, 35]` with size `[180, 12, 70]`; the narrowed throat leaves only `34` mm between the inner faces before the goal sleeve.
- `goal_sleeve`: static end pocket centered at `[515, 0, 35]` with size `[36, 36, 70]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius in `[18, 20]` mm
- Nominal start position: `[-80, 0, 145]`
- Runtime jitter: `[10, 10, 5]` mm

## 4. Objectives

- `goal_zone`: min `[500, -12, 10]`, max `[530, 12, 60]`
- `build_zone`: min `[-140, -160, 0]`, max `[560, 160, 220]`

## 5. Simulation Bounds

- min `[-200, -200, -10]`, max `[620, 200, 260]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 75 USD`, `max_weight <= 1300 g`
- The benchmark stays fully static; precision comes from funnel geometry and jitter tolerance, even though the final throat has been squeezed below the previous opening.

## 7. Success Criteria

- Success if the ball reaches the narrow `goal_zone` after being captured by the upstream funnel geometry.
- Fail if the ball exits `simulation_bounds` or if the plan relies on undeclared moving benchmark parts to squeeze into the sleeve.

## 8. Planner Artifacts

- `todo.md` tracks the bowl, narrowing throat walls, and goal sleeve implementation.
- `benchmark_definition.yaml` mirrors the narrow goal geometry and caps.
- `benchmark_assembly_definition.yaml` records the static benchmark-local parts and confirms zero DOFs.
