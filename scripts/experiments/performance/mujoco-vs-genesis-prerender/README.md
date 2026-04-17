# MuJoCo vs Genesis 24-View Prerender Experiment

This experiment benchmarks the static 24-view render path used by heavy-worker
validation:

- endpoint-equivalent path: `validate_subprocess(...)` (`--mode validate`)
- direct render path: `prerender_24_views(...)` (`--mode prerender`)

Each run executes in a fresh subprocess. Cache isolation is enabled by default
to reduce cross-run cache effects.

## Run

From repo root:

```bash
uv run python scripts/experiments/mujoco-vs-genesis-prerender/benchmark_validate_prerender_backends.py --scenario all --mode both --backend all --repetitions 1 --smoke-test-mode false --isolate-cache --force-cpu --mujoco-gl egl
```

Quick smoke sanity check:

```bash
uv run python scripts/experiments/mujoco-vs-genesis-prerender/benchmark_validate_prerender_backends.py --scenario int133_like --mode both --backend all --repetitions 1 --smoke-test-mode true --timeout-sec 180
```

## Output

The script writes a timestamped JSON result in this folder by default:

- `summary`: per `(scenario, mode, backend)` aggregates
- `speedups`: MuJoCo speedup vs Genesis when both means are available
- `rows`: per-run raw records (including timeout/error details)

Notes:

- `runs_usable` means successful runs with at least one saved render image.
- In strict headless environments, a backend can "succeed" but produce zero
  renders; such runs are tracked but excluded from `mean_sec_usable`.
