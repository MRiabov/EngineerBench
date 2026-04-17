## 1. Learning Objective

- Show that a passive benchmark can stay schema-valid while using a simple
  rigid-body gravity path.

## 2. Static Geometry

- `environment_fixture`: a passive rigid-body scene shell with a base plate,
  side walls, and a single center blocker.

## 3. Input Object

- Shape: `sphere`
- Label: `projectile_ball`
- Static randomization: radius_mm in `[4, 6]` mm
- Nominal start position: `[0, 0, 48]`
- Runtime jitter:
  - Position: `[2, 2, 1]` mm

## 4. Objectives

- Goal zone: `min_mm [22, 8, 2]`, `max_mm [34, 20, 12]`
- Forbid zone: `central_baffle`, `min_mm [-8, -8, 0]`, `max_mm [8, 8, 16]`
- Build zone: `min_mm [-36, -28, 0]`, `max_mm [36, 28, 60]`

## 5. Design

- The sphere falls under gravity and is redirected by static geometry into the
  goal zone.
- There are no benchmark-owned moving fixtures or powered features.

## 6. Randomization

- Allow small symmetric scale jitter on the passive environment shell while
  preserving objective clearance.
- Use the declared runtime jitter on the sphere spawn position to test
  robustness.

## 7. Build123d Strategy

- Use simple CSG primitives: slabs for the floor and walls, a block for the
  center obstacle, and a box-like goal pocket.

## 8. Cost & Weight Envelope

- `totals.estimated_unit_cost_usd`: `24.0`
- `totals.estimated_weight_g`: `650.0`
- `totals.estimate_confidence`: `high`

## 9. Part Metadata

- `environment_fixture` must be static (`fixed: true`) and carry a known
  `material_id`.
- The payload uses `material_id: abs`.
