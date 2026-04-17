# compile_kernels experiment

This experiment measures cold-start timings for heavy-worker code paths equivalent to:

- `/benchmark/validate`
- `/benchmark/simulate`

It toggles `GENESIS_COMPILE_KERNELS` between `true` and `false` and runs each sample in fresh subprocesses.

## Run

From repo root:

```bash
uv run python scripts/experiments/no-compile-experiment/benchmark_compile_kernels.py --scenario all --mode both --repetitions 1 --smoke-test-mode false --isolate-cache --force-cpu
```

Shorter smoke run:

```bash
uv run python scripts/experiments/no-compile-experiment/benchmark_compile_kernels.py --scenario int101_like --mode both --repetitions 2 --smoke-test-mode true --isolate-cache --timeout-sec 120 --force-cpu
```

The script prints grouped summaries and writes a JSON artifact into this folder by default.

Notes:

- `--force-cpu` is enabled by default.
- `--isolate-cache` is enabled by default to avoid cache pollution between runs.
- Scenario fixtures are integration-test-like benchmark setups (`int101_like`, `int133_like`).
