# TODO

- [x] Planner handoff seeded
- [ ] Implement environment geometry in `benchmark_script.py`
  - [ ] `base_plate`: 300×200×10 mm floor plate at [0, 0, 5]
  - [ ] `deflector_ramp`: 120×160×15 mm angled ramp at 30°, centered at [40, 0, 60]
  - [ ] `side_goal_wall`: vertical wall at goal zone near [170, 0, 50]
  - [ ] `catch_bin`: goal bin floor at [170, 0, 5], 60×70×5 mm
- [ ] Construct the payload from `benchmark_definition.yaml` contract
- [ ] Preserve `benchmark_plan_evidence_script.py` and `benchmark_plan_technical_drawing_script.py` as read-only context
- [ ] Keep `benchmark_script.py` import-safe with a pure `build()` module contract
- [ ] Use external shell self-checks for validate/simulate/review submission, not in-module calls
