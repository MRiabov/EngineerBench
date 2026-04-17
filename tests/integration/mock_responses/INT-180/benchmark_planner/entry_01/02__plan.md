## 1. Learning Objective

- Show that a benchmark can stay solvable and compact while still using the
  benchmark handoff contract.

## 2. Static Geometry

- `environment_fixture`: a passive rigid-body shell with a direct corridor to
  the goal zone.

## 3. Input Object

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization: radius_mm in `[4, 6]` mm
- Nominal start position: `[0, 0, 48]`
- Runtime jitter:
  - Position: `[2, 2, 1]` mm

## 4. Objectives

- Goal zone: `min_mm [22, 8, 2]`, `max_mm [34, 20, 12]`
- Forbid zones: none
- Build zone: `min_mm [-36, -28, 0]`, `max_mm [36, 28, 60]`

## 5. Design

- The sphere should fall through the open corridor without requiring any
  powered fixtures.

## 6. Randomization

- Use small symmetric scale jitter on the passive shell while keeping the
  corridor open.
- Use the declared runtime jitter on the sphere spawn position.

## 7. Build123d Strategy

- Use simple CSG primitives: slabs for the floor and walls, and a simple goal
  pocket.

## 8. Cost & Weight Envelope

- `totals.estimated_unit_cost_usd`: `24.0`
- `totals.estimated_weight_g`: `650.0`
- `totals.estimate_confidence`: `high`

## 9. Part Metadata

- `environment_fixture` must be static (`fixed: true`) and carry a known
  `material_id`.
- The payload uses `material_id: abs`.
