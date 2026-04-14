## 1. Learning Objective

- Train gravity-first rigid-body reasoning with a passive benchmark that moves
  a sphere into a goal zone using only gravity and static geometry.
- Keep the family simple, reproducible, and fully rigid-body: no actuators,
  FEM, or fluids.

## 2. Static Geometry

- `environment_fixture`: a passive rigid-body scene shell made from a base
  plate, side walls, and a central blocker that forces the sphere to route
  around the obstacle.
- The static geometry may be scaled slightly at generation time, but it must
  remain entirely passive and rigid-body.

## 3. Input Object

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization: radius in `[4, 6]` mm
- Nominal start position: `[0, 0, 48]`
- Runtime jitter:
  - Position: `[2, 2, 1]` mm
  - Properties: keep mass and friction constant for the family

## 4. Objectives

- Goal zone:
  - Type: AABB
  - Location: `min [22, 8, 2]`, `max [34, 20, 12]`
- Forbid zones:
  - `central_baffle`: `min [-8, -8, 0]`, `max [8, 8, 16]`
- Build zone:
  - `min [-36, -28, 0]`
  - `max [36, 28, 60]`

## 5. Design

- The benchmark stays passive: the sphere falls under gravity and the static
  geometry redirects it into the goal zone.
- There are no benchmark-owned moving fixtures, actuators, FEM parts, or fluid
  features in this family.
- Any benchmark-side motion that would require a controller is out of scope and
  must be rejected rather than adapted.

## 6. Randomization

- Static: allow small symmetric scale jitter on the passive environment shell
  while preserving objective clearance.
- Runtime: use the declared position jitter on the sphere spawn position to
  test robustness.

## 7. Build123d Strategy

- Use simple CSG primitives: slabs for the floor and walls, a block for the
  center obstacle, and a simple box or pocket for the goal area.
- Keep the geometry readable and aligned to world axes so the gravity path is
  obvious to the reviewer.

## 8. Cost & Weight Envelope

- `totals.estimated_unit_cost_usd`: `24.0`
- `totals.estimated_weight_g`: `650.0`
- `totals.estimate_confidence`: `high`
- The estimate assumes a small passive environment fixture built from common
  rigid materials and a lightweight sphere input object.

## 9. Part Metadata

- `environment_fixture` must be static (`fixed: true`) and carry a known
  `material_id`.
- The payload uses `material_id: abs`.
- No part in this family should introduce powered or deformable behavior.
