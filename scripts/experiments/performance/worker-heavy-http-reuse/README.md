# Worker-Heavy HTTP Reuse Benchmark

This experiment measures the difference between:

1. restarting `worker-heavy` before each `/benchmark/simulate` request,
2. reusing one `worker-heavy` process across repeated `/benchmark/simulate` requests.

It is designed to approximate the local integration-debugging pain point more closely than the direct `simulate_subprocess(...)` benchmark, because the worker process and its persistent simulation child are both part of the measured path.

## What it answers

- Whether the local slowdown between repeated integration invocations is primarily "new worker process every time".
- Whether the already-implemented persistent child inside one worker process produces a large HTTP-level second-request gain.

## Run

From repo root:

```bash
GENESIS_FORCE_CPU=1 .venv/bin/python \
  scripts/throwaway/experiments/worker-heavy-http-reuse/benchmark_worker_heavy_http_reuse.py \
  --force-cpu \
  --scenario int101_like \
  --repetitions 2
```

## Output

The script writes a timestamped JSON file into this folder by default.
