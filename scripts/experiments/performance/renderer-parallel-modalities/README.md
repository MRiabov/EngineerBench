# Renderer Parallel Modalities Experiment

This experiment measures preview modality rendering on the current headless
renderer backend. Parallel RGB/depth/segmentation fan-out is only supported in
smoke-test mode; non-smoke runs stay sequential and fail closed if parallel mode
is requested.

It exercises the same `render_preview_scene_bundle(...)` code path that the
renderer worker uses internally, but it runs on a synthetic scene so the result
is not dominated by worker HTTP admission, retry loops, or seed bundle staging.

The benchmark compares sequential rendering, and in smoke-test mode can also
exercise the parallel branch.

The default scene uses 24 views, all three modalities, axes and edges enabled,
and a payload-path overlay, which matches the expensive part of the current
preview workload.

## Run

From repo root:

```bash
uv run python scripts/experiments/performance/renderer-parallel-modalities/benchmark_parallel_modalities.py
```

Quick smoke test with a single view:

```bash
uv run python scripts/experiments/performance/renderer-parallel-modalities/benchmark_parallel_modalities.py \
  --smoke-test-mode true \
  --repetitions 1 \
  --warmup-runs 0
```

Write to a custom output file:

```bash
uv run python scripts/experiments/performance/renderer-parallel-modalities/benchmark_parallel_modalities.py \
  --output scripts/experiments/performance/renderer-parallel-modalities/results-custom.json
```

## Output

The script writes a timestamped JSON result in this folder by default.

Important fields:

- `summary.parallel.mean_sec`
- `summary.sequential.mean_sec`
- `summary.parallel_minus_sequential_sec`
- `summary.parallel_to_sequential_ratio`
- `rows`

How to read the result:

- `parallel_minus_sequential_sec > 0` means parallel modality rendering was
  slower on average.
- `parallel_to_sequential_ratio < 1` means parallel modality rendering was
  faster on average.
- `rows[*].warmup=true` are intentionally excluded from the summary.
