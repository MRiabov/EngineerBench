## 1. Learning Objective

Test whether an engineer can design a passive precision funnel that keeps
`projectile_ball` centered as a wide capture mouth narrows into a tight goal
throat.

## 2. Geometry

- `environment_fixture`: static upright lofted funnel fixture that provides
  the wide capture mouth and narrow throat used by the passive benchmark.
- The benchmark stays static; the challenge comes from the narrow throat and
  the runtime jitter on the payload.

## 3. Input Objective

- Shape: `sphere`
- Label: `projectile_ball`
- Radius variation: `18 mm` to `20 mm`
- Nominal start position: `[-80, 0, 145]`
- Runtime jitter: `[10, 10, 5]` mm

## 4. Objectives

- `goal_zone_mm`: `[500, -14, 12]` to `[538, 14, 60]`
- `forbid_zones`:
  - `throat_keepout`: `[250, -32, 0]` to `[410, 32, 46]`
- `build_zone_mm`: `[-140, -160, 0]` to `[560, 160, 220]`

## 5. Simulation Bounds

- `[-200, -200, -10]` to `[620, 200, 260]`

## 6. Constraints Handed To Engineering

- Benchmark caps: `max_unit_cost <= 56 USD`, `max_weight <= 1010 g`
- Planner target: keep the proposed funnel comfortably below the benchmark
  cap so the draft remains manufacturable and easy to review.

## 7. Success Criteria

- Success if the ball reaches the goal zone without entering the throat
  keepout.
- Fail if the payload leaves the simulation bounds or if the plan relies on
  hidden benchmark motion.

## 8. Planner Artifacts

- `benchmark_definition.yaml` mirrors the declared zones, payload, and caps.
- `benchmark_assembly_definition.yaml` stays read-only benchmark context.
- `benchmark_plan_evidence_script.py` provides a previewable scene for the
  benchmark review.
