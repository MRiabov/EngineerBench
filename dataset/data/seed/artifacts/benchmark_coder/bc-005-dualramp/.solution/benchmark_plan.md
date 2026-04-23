## 1. Learning Objective

Test whether a falling sphere can strike a primary ramp, transfer to a secondary ramp, and roll into a side goal bin while never entering the direct drop trap below the spawn.

## 2. Geometry

- `base_plate`: fixed floor plate centered at `[0, 0, 5]` mm, size `340×240×10` mm.
- `primary_ramp`: fixed angled ramp centered near `[30, -18, 60]` mm, built from `Rotation(0, 26, -12) * box` so the top surface tilts and yaw-shifts the incoming ball, size `120×150×15` mm.
- `secondary_ramp`: fixed angled ramp centered near `[118, 34, 38]` mm, built from `Rotation(0, -18, 18) * box` to catch the redirected ball, size `110×130×12` mm.
- `splitter_wall`: thin vertical wall centered near `[68, 0, 34]` mm that forces the ball toward the second ramp, size `12×120×70` mm.
- `goal_wall`: vertical wall forming the goal bin at `[190, 60, 22]` mm to `[250, 110, 82]` mm.
- `catch_bin`: goal collection bin at `[190, 55, 5]` mm to `[250, 105, 28]` mm.
- `projectile_ball` (payload, ABS plastic):
  - Shape: `sphere`
  - Radius range (static randomization): `[18, 22]` mm
  - Spawn position: `[0, 0, 126]`
  - Runtime jitter: `±[8, 6, 4]` mm

## 3. Objectives

### Goal zone

- AABB min_mm: `[190, 55, 5]`
- AABB max_mm: `[250, 105, 28]`
- Success when the projectile ball center enters this volume.

### Forbid zone: `direct_drop_trap`

- AABB min_mm: `[-24, -28, 0]`
- AABB max_mm: `[24, 28, 52]`
- Any contact with this zone by any simulation object = failure.

### Build zone

- AABB min_mm: `[-190, -130, 0]`
- AABB max_mm: `[260, 130, 170]`
- The engineer may only build within these bounds.

### Simulation bounds

- AABB min_mm: `[-230, -170, -10]`
- AABB max_mm: `[300, 170, 210]`
- Any object exiting this volume = failure.

## 4. Randomization

- Static: projectile ball radius_mm varies in `[18, 22]` mm per benchmark variant.
- Runtime: projectile ball spawn position jitters by `±[8, 6, 4]` mm per simulation run.
- The solution must handle all positions within the jitter range robustly.

## 5. Implementation Notes

- Use build123d primitives for all geometry.
- Preserve `benchmark_plan_evidence_script.py` as read-only planner context.
- Keep `benchmark_script.py` import-safe: no `__main__` block, no in-module review submission call.
- Run validate/simulate/review submission only from external shell self-check commands.
