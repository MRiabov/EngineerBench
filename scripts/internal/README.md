# Internal Scripts

This directory is for internal-only script modules and utilities.

Scope:

- Shared orchestration logic used by top-level scripts in `scripts/`.
- Helper modules not intended as stable public entrypoints.
- Experimental-but-structured utilities that should not live in `scripts/throwaway/`.

Conventions:

- Keep modules focused and composable.
- Prefer Python modules here when shell logic becomes complex.
- Add small, explicit CLIs only when needed.
- Do not assume files here are directly user-facing.

Current modules:

- `integration_runner.py`: integration-test orchestration primitives
  (parallel readiness checks + safe pytest subprocess execution).
- `eval_seed_renders.py`: deterministic seed render regeneration helpers used
  by `scripts/update_eval_seed_renders.py` and the compatibility alias in
  `scripts/validate_eval_seed.py --update-renders`.
- `eval_seed_selection.py`: dataset selection helpers shared by the seed
  validation and seed-maintenance CLIs.

Examples:

```bash
python scripts/internal/integration_runner.py wait \
  --cmd-check "postgres|docker compose -f docker-compose.test.yaml exec postgres pg_isready -U postgres" \
  --http-check "minio|http://127.0.0.1:19000/minio/health/live" \
  --tcp-check "temporal|127.0.0.1:17233"

python scripts/internal/integration_runner.py run-pytest -- -m "integration_p0" tests/integration tests/e2e
```
