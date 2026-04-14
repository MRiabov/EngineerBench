## 1. Learning Objective

- Train passive gravity-first rigid-body routing reasoning with a seeded central obstacle that forces the projectile to route around a forbid zone before reaching the goal.
- Keep the benchmark fully passive: no actuators, no motors, no FEM, no fluids. The only energy source is gravity acting on the payload.
- Test engineer robustness to runtime jitter on spawn position and input-object radius.

## 2. Static Geometry

- `environment_fixture`: a passive rigid-body environment shell that provides the seeded floor, walls, and the central blocker obstacle.
- The central blocker is a large rectangular forbid zone at `[120, -130, 0]` to `[260, 130, 150]` that spans most of the Y-axis and forces any solution to route around it.
- The environment fixture is static (`fixed: true`) and uses `material_id: aluminum_6061`.
- No benchmark-owned moving fixtures exist in this family.

## 3. Input Object

- Shape: `sphere`
- Label: `projectile_ball`
- Material: `abs`
- Static randomization: radius in `[28.0, 30.0]` mm
- Nominal start position: `[-180.0, 0.0, 110.0]`
- Runtime jitter:
  - Position: `[14.0, 10.0, 6.0]` mm (±X, ±Y, ±Z)
  - Properties: keep mass and friction constant for the family

## 4. Objectives

- Goal zone:
  - Type: AABB
  - Location: `min [420.0, -60.0, 15.0]`, `max [520.0, 60.0, 110.0]`
  - The projectile ball's center must enter this volume for success.
- Forbid zones:
  - `central_blocker`: `min [120.0, -130.0, 0.0]`, `max [260.0, 130.0, 150.0]`
  - Any contact with this volume fails the simulation.
- Build zone:
  - `min [-240.0, -180.0, 0.0]`
  - `max [560.0, 180.0, 240.0]`
  - All engineer-owned parts must stay within these bounds.

## 5. Design

- The benchmark stays passive: the sphere falls under gravity from an elevated spawn position and the engineer must create a routing path that guides it around the central blocker into the far goal zone.
- The central blocker is intentionally large enough to block direct paths, forcing the engineer to design an offset route (either around the positive-Y or negative-Y side).
- There are no benchmark-owned moving fixtures, actuators, FEM parts, or fluid features in this family.
- Any benchmark-side motion that would require a controller is out of scope and must be rejected rather than adapted.

## 6. Randomization

- Static: the benchmark variant `engineer_coder_forbid_route_v1` defines the geometry family. The environment fixture may be scaled slightly at generation time while preserving objective clearance.
- Runtime: use the declared position jitter `[14.0, 10.0, 6.0]` on the sphere spawn position to test robustness. The engineer solution must handle all positions within that envelope without re-tuning.
- The payload radius varies between `[28.0, 30.0]` mm across static variants, which affects clearance requirements.

## 7. Build123d Strategy

- Use simple CSG primitives for the benchmark environment: slabs for the floor and walls, a large block for the central blocker obstacle.
- Keep the geometry readable and aligned to world axes so the gravity path and blocker geometry are obvious to the reviewer.
- The payload is materialized from `benchmark_definition.yaml` using the declared shape (sphere), radius range, and start position.
- Objective overlays (goal zone, forbid zones, build zone) are reconstructed through `objectives_geometry()` for preview rendering.
- Materialize a compact drafting package for the passive fixture and inspect it with `preview_drawing()` before submission.

## 8. Cost & Weight Envelope

- `constraints.estimated_solution_cost_usd`: `42.0`
- `constraints.estimated_solution_weight_g`: `800.0`
- `constraints.max_unit_cost`: `64.0` (derived as 1.5x planner estimate, rounded)
- `constraints.max_weight_g`: `1250.0` (derived as 1.5x planner estimate, rounded)
- The estimate assumes a passive routing mechanism built from common rigid materials (HDPE guides, aluminum base plate) with a small parts count.
- The benchmark is designed to be solvable within these constraints using passive geometry only.

## 9. Part Metadata

- `environment_fixture` must be static (`fixed: true`) and carry `material_id: aluminum_6061`.
- The payload (`projectile_ball`) uses `material_id: abs`.
- No part in this family should introduce powered or deformable behavior.
- Top-level authored labels must be unique and must not be `environment` or start with `zone_`.

## 10. Solvability and Clearance

- The goal zone is positioned at `[420-520, -60 to 60, 15-110]`, which is downstream and to the far side of the central blocker.
- The spawn position at `[-180, 0, 110]` with runtime jitter `[14, 10, 6]` ensures the ball starts well clear of the blocker and has elevation to build momentum.
- The build zone extends from `[-240, -180, 0]` to `[560, 180, 240]`, providing ample space for the engineer to create a routing path around either side of the blocker.
- Under static variation plus runtime jitter, the payload must remain inside the build zone at spawn and must not intersect the forbid zone or goal zone at spawn.
- The benchmark is solvable via passive routing: a properly angled chute or rail system can guide the ball around the blocker using gravity alone.
