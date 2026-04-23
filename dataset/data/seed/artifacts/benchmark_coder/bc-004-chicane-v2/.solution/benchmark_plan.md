## 1. Learning Objective

Test whether a rolling sphere can survive a chicane-shaped tunnel with two bends and exit into a side-shifted goal box without clipping the roof or the inner elbow.

## 2. Geometry

- `environment_fixture`: single fixed chicane-shell fixture that stays inside the build zone and contains the rolling sphere until it reaches the goal box.
- A tunnel body inside the build zone with a clear inner channel for a 30 mm radius_mm sphere.
- Entry shelf near X=-0.44 m, a mid-chicane offset around X=-0.06 m, Y=+0.02 m, and an exit lip near X=+0.50 m, Y=+0.04 m.
- Static outer shell and floor should be fixed.

## 3. Objectives

- Keep the sphere inside the tunnel until the exit.
- Land in the goal zone near the right side.
- Fail if the sphere leaves through the tunnel roof, the inner elbow, or the simulation ceiling.

## 4. Randomization

- Small tunnel-width variation.
- Runtime jitter on spawn.

## 5. Implementation Notes

- Prefer CSG-friendly boxes and rotated tunnel segments.
- Keep planner files read-only and implement through `benchmark_script.py`.
- Preserve `benchmark_plan_evidence_script.py` as read-only planner context.
- Keep `benchmark_script.py` import-safe with no `__main__` block and no in-module review submission call.
- Run validate/simulate/review submission only from external shell self-check commands.
