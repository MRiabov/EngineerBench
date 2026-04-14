## 1. Learning Objective

Test whether a rolling sphere can stay constrained inside a tunnel-shaped guide and exit into a goal box without clipping the tunnel roof.

## 2. Geometry

- A tunnel body inside the build zone with a clear inner channel for a 30 mm radius sphere.
- Entry shelf near X=-0.42 m and exit lip near X=+0.48 m.
- Static outer shell and floor should be fixed.

## 3. Objectives

- Keep the sphere inside the tunnel until the exit.
- Land in the goal zone near the right side.
- Fail if the sphere leaves through the tunnel roof or simulation ceiling.

## 4. Randomization

- Small tunnel-width variation.
- Runtime jitter on spawn.

## 5. Implementation Notes

- Prefer CSG-friendly boxes/cylinders.
- Keep planner files read-only and implement through `benchmark_script.py`.
- Preserve `benchmark_plan_evidence_script.py` as read-only planner context.
- Keep `benchmark_script.py` import-safe with no `__main__` block and no in-module review submission call.
- Run validate/simulate/review submission only from external shell self-check commands.
