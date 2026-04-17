## 1. Learning Objective

- Show that a passive rigid-body benchmark can route a sphere into a goal
  zone using only static geometry.
- Keep the scenario simple enough to validate quickly, but specific enough that
  the geometry, input object, and objective zones are unambiguous.

## 2. Geometry

- `environment_fixture`: a compact box-like passive scene shell around the
  origin with a floor, side walls, and a center redirecting surface.
- The static geometry should leave a clear gravity path that is still
  obstructed enough to require deliberate routing.
- No benchmark-owned moving fixtures are needed.

## 3. Objectives

- Input object:
  - Shape: `sphere`
  - Label: `projectile_ball`
  - Static randomization: radius_mm in `[1, 2]` mm
  - Nominal start position: `[0, 0, 0]`
  - Runtime jitter: `[0.5, 0.5, 0.5]`
- Goal zone: `min_mm [6, -2, 0]`, `max_mm [10, 2, 4]`
- Forbid zone: `min_mm [3, -3, 0]`, `max_mm [4, 3, 4]`
- Build zone: `min_mm [-10, -10, -10]`, `max_mm [10, 10, 10]`
- Simulation bounds: `min_mm [-30, -30, -30]`, `max_mm [30, 30, 30]`
- Success requires the sphere to reach the goal zone without crossing the
  forbid zone.

## 4. Randomization

- Static randomization is limited to the moved sphere radius_mm.
- Runtime jitter is limited to the sphere spawn position.
- The passive fixture remains fixed so the benchmark stays reproducible.

## 5. Implementation Notes

- Keep the drafted benchmark grounded in a single passive environment fixture.
- The benchmark_definition file will carry the copied customer caps and the
  exact payload contract.
- No moving benchmark-owned fixtures are needed.
