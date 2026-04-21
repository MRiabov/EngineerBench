## 1. Learning Objective

Move the seeded `projectile_ball` (a 40 mm ABS sphere) one meter sideways
into the goal zone using only fixed guide geometry and gravity.

## 2. Geometry

- `ground_plane`.
- `platform_left` and `platform_right`.
- `guide_rail_lower` and `guide_rail_upper`.

## 3. Objectives

- Reach goal zone.
- Stay inside bounds.
- Remain manufacturable and reviewer-ready.

## 4. Randomization

- The payload radius is fixed at 40 mm.
- The start pose is deterministic and does not vary at runtime.

## 5. Implementation Notes

- The benchmark-owned `environment_fixture` stays fixed and is the only
  benchmark part declared in the handoff.
- The benchmark-owned geometry remains rigid-body only and passive; the fixed
  rails and supports are the full handoff context.
- The benchmark reviewer should treat the fixed rails and supports as the full
  handoff context.
