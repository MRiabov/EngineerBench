# Bug Report

- **Active role:** `engineer_coder`
- **Task ID:** `ec-002`
- **Session / run:** `run_20260415_223301`

## Failure

The minimal eval run failed during `env_up` before the task could execute.

### Command

`uv run dataset/evals/run_evals.py --agent engineer_coder --task-id ec-002 --limit 1 --concurrency 1 --verbose --log-level INFO --runner-backend controller --call-paid-api`

### Expected

The eval environment should boot, the controller should become healthy, and the single `ec-002` task should run to completion.

### Actual

`env_up.sh failed with exit code 1`.

The worker-renderer container startup failed with:

`service "worker-renderer" refers to undefined volume logs/evals/runs/run_20260415_223301: invalid compose project`

### Relevant logs

- `logs/evals/runs/run_20260415_223301/run_evals.log`
- `logs/evals/runs/run_20260415_223301/worker_renderer.log`
- `logs/evals/runs/run_20260415_223301/worker_light.log`

## Notes

- `scripts/validate_eval_seed.py --agent engineer_coder --task-id ec-002` passed before the eval run.
- The render bundle for `dataset/data/seed/artifacts/engineer_coder/ec-002-low-friction-cube/renders/engineer_plan_renders/low_friction_route_render_e45_a45.png` shows the red route overlay as continuous and healthy.
