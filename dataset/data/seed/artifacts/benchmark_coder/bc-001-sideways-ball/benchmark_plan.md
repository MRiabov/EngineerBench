## 1. Learning Objective

Test lateral transfer over 1 meter distance. The benchmark moves a 40 mm radius steel sphere (`projectile_ball`, `material_id: steel_carbon`) from the left start position at X=-0.5 m to the right goal zone centered near X=+0.5 m without leaving simulation bounds. The transfer uses a passive gravity-driven ramp; no active drive mechanism or powered DOFs are present.

## 2. Geometry

- `ground_plane`: fixed base plane at Z=0 made from HDPE, spanning the full build-zone footprint (1.16 m x 0.20 m).
- `floor_plate`: fixed aluminum plate (`aluminum_6061`) centered near X=0, providing a rigid base for the mechanism (200 mm x 60 mm x 10 mm).
- `support_tower`: vertical aluminum tower (`aluminum_6061`) centered near X=0, 160 mm tall, supporting the raised goal shelf.
- `raised_goal_shelf`: aluminum goal shelf (`aluminum_6061`) positioned on the support tower near X=+0.5 m at Z=0.17 m.
- `lift_carriage`: HDPE carriage plate that slides passively along the Z axis (`dofs: [slide_z]`, no active control), providing lateral guidance for the sphere.
- Two guide rails along the X axis around Y=+/-0.06 m to contain the sphere.
- Build zone limited to X=[-0.58, 0.58], Y=[-0.1, 0.1], Z=[0, 0.18].

## 3. Objectives

- Goal zone AABB: min=[0.44, -0.05, 0.15], max=[0.56, 0.05, 0.20]. The Z range [0.15, 0.20] intersects the `raised_goal_shelf` top surface at Z=0.17 m, ensuring the sphere can land on the shelf.
- Failure if the sphere exits simulation bounds.
- Gravity-only passive transfer via a ramp/track geometry; no active drive mechanism. The `lift_carriage` has a single passive DOF (`slide_z`) with no `control` block — it acts as a friction-guided sliding surface, not a powered actuator.

## 4. Randomization

- Static variation on platform height between 0.07 m and 0.09 m (affects ramp mounting base).
- Static variation on rail Y offset between -0.01 m and +0.01 m (affects guide clearance).
- Runtime jitter on the sphere start position: [0.01, 0.005, 0.005] m.

## 5. Implementation Notes

### 5.1 Detailed Calculations

**Transfer distance:** `delta_x = 0.5 - (-0.5) = 1.0 m`

**Energy balance** for steel sphere (`steel_carbon`, density ~7850 kg/m³, radius 0.04 m, mass ≈ 2.105 kg):

- Ramp entry at Z=0.18 m (build zone ceiling), lowest point at Z=0.04 m, goal shelf at Z=0.17 m.
- `E_start = m * g * (0.18 - 0.04) = 2.105 * 9.81 * 0.14 = 2.87 J`
- `E_goal = m * g * (0.17 - 0.04) = 2.105 * 9.81 * 0.13 = 2.68 J`
- `E_margin = 2.87 - 2.68 = 0.19 J` (7% before friction)
- Rolling friction loss (μ_r ≈ 0.002, d=1.0 m): `W_friction = 0.002 * 20.65 * 1.0 = 0.041 J`
- Net energy at goal: 0.15 J > 0 — transfer succeeds.

**Timing:** velocity at bottom ≈ 1.66 m/s, transfer time ≈ 0.91 s.

**Clearance:** guide rail spacing Y=±0.06 m, sphere diameter 0.08 m → 20 mm per side.

**Tolerance:** worst-case jitter (Z: -0.005 m) still leaves positive margin because ramp entry height is fixed by geometry.

### 5.2 Payload Trajectory

The payload follows a gravity-driven ramp path: start at X=-0.5 m, Z=0.18 m → bottom at X=0 m, Z=0.04 m → goal at X=+0.5 m, Z=0.17 m. The `lift_carriage` provides passive Z-axis guidance (`dofs: [slide_z]`, no `control` block).

### 5.3 General Requirements

- Use Build123d primitives.
- Ensure every part has `PartMetadata` or `CompoundMetadata`.
- Preserve `benchmark_plan_evidence_script.py` and `benchmark_plan_technical_drawing_script.py` as read-only planner context.
- Keep `benchmark_script.py` import-safe with no `__main__` block and no in-module review submission call.
- Run validate/simulate/review submission only from external shell self-check commands.
- The engineer must design ramp geometry that starts at Z=0.18 m (build zone ceiling) at X=-0.5 m, drops to Z=0.04 m near X=0, and rises to Z=0.17 m at the goal shelf near X=+0.5 m.
