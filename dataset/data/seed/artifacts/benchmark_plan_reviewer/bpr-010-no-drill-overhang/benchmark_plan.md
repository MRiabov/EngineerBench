## 1. Learning Objective

Test whether an engineer can solve a freestanding transfer benchmark where the environment offers no drilling, clamping, or attachment privileges.

## 2. Environment Geometry

- `ballast_base`: static base centered at `[-40, 0, 15]` with size `[420, 180, 30]`.
- `transfer_chute`: static chute centered at `[35, 0, 70]` with size `[410, 90, 80]`.
- `counterweight_fin`: static rear stabilizer centered at `[-170, 0, 95]` with size `[90, 40, 150]`.
- `goal_cradle`: static pocket centered at `[305, 0, 30]` with size `[110, 110, 35]`.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization:
  - radius in `[22, 24]` mm
- Nominal start position: `[-250, 0, 70]`
- Runtime jitter: `[10, 8, 4]` mm

## 4. Objectives

- `goal_zone`: min `[210, -55, 20]`, max `[310, 55, 110]`
- `build_zone`: min `[-320, -180, 0]`, max `[340, 180, 220]`

## 5. Simulation Bounds

- min `[-380, -220, -10]`, max `[400, 220, 280]`

## 6. Constraints Handed To Engineering

- Benchmark/customer caps: `max_unit_cost <= 60 USD`, `max_weight <= 1000 g`
- The benchmark assumes zero environment attachments and zero benchmark-side DOFs, even though the farther-right chute and goal cradle stretch the freestanding layout near the build-zone edge.

## 7. Success Criteria

- Success if the ball ends within `goal_zone` while the freestanding benchmark geometry remains inside `build_zone`.
- Fail if any solution depends on undeclared environment attachment or if the payload exits `simulation_bounds`.

## 8. Planner Artifacts

- `todo.md` tracks the ballast base, chute, stabilizer, and cradle implementation.
- `benchmark_definition.yaml` mirrors the no-drill limits and objective layout.
- `benchmark_assembly_definition.yaml` records the freestanding benchmark-local parts and confirms zero DOFs.
