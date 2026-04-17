# Fresh vs Warm `simulate_subprocess(...)`

This experiment measures the optimization target directly:

1. Current behavior: fresh spawned simulation child per request.
2. Candidate behavior: one reused spawned simulation child running two requests sequentially.

The benchmark drives the real `simulate_subprocess(...)` code path inside worker-heavy process executors. It uses two distinct successful bundles and runs both bundle orders:

- `A_then_B`
- `B_then_A`

Important controls:

- Distinct `session_id` per bundle execution, even in warm mode, so backend cache hits do not collapse into same-session reuse.
- Fresh `HOME` / `XDG_CACHE_HOME` / Taichi cache roots per repetition child run, so on-disk cache contamination is reduced.
- `ProcessPoolExecutor(..., initializer=init_genesis_worker)` is used in both modes to match the current runtime contract.

Example run:

```bash
GENESIS_FORCE_CPU=1 .venv/bin/python scripts/experiments/simulate-subprocess-reuse/benchmark_fresh_vs_warm_simulate_subprocess.py --force-cpu --repetitions 1
```
