## 1. Learning Objective

Test passive gravity-driven redirection: a ball dropped from height must strike an angled deflector ramp and roll into a side goal without touching a forbid zone directly below the spawn.

## 2. Geometry

- `base_plate`: fixed floor plate centered at `[0, 0, 5]` mm, size `300×200×10` mm.
- `deflector_ramp`: fixed angled ramp centered near `[40, 0, 60]` mm, top surface tilted 30° from horizontal, size `120×160×15` mm.
- `side_goal_wall`: vertical wall forming the goal bin at `[140, -40, 20]` mm to `[200, 40, 80]` mm.
- `catch_bin`: goal collection bin at `[140, -35, 5]` mm to `[200, 35, 25]` mm.
- `projectile_ball` (payload, ABS plastic):
  - Shape: `sphere`
  - Radius range (static randomization): `[18, 22]` mm
  - Spawn position: `[0, 0, 120]`
  - Runtime jitter: `±[8, 6, 4]` mm

## 3. Objectives

### Goal zone

- AABB min: `[140, -35, 5]`
- AABB max: `[200, 35, 25]`
- Success when the projectile ball center enters this volume.

### Forbid zone: `direct_drop_trap`

- AABB min: `[-20, -25, 0]`
- AABB max: `[20, 25, 50]`
- Any contact with this zone by any simulation object = failure.

### Build zone

- AABB min: `[-180, -120, 0]`
- AABB max: `[240, 120, 160]`
- The engineer may only build within these bounds.

### Simulation bounds

- AABB min: `[-220, -160, -10]`
- AABB max: `[280, 160, 200]`
- Any object exiting this volume = failure.

## 4. Randomization

- Static: projectile ball radius varies in `[18, 22]` mm per benchmark variant.
- Runtime: projectile ball spawn position jitters by `±[8, 6, 4]` mm per simulation run.
- The solution must handle all positions within the jitter range robustly.

## 5. Implementation Notes

- Use build123d primitives for all geometry.
- Preserve `benchmark_plan_evidence_script.py` and `benchmark_plan_technical_drawing_script.py` as read-only planner context.
- Keep `benchmark_script.py` import-safe: no `__main__` block, no in-module review submission call.
- Run validate/simulate/review submission only from external shell self-check commands.
