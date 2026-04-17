# Integration Cache Path Stability Benchmark

This experiment measures whether repeated fresh-child simulation requests benefit more from:

1. a stable integration workspace path,
2. a stable `INT-###` session identifier,
3. or both together.

It is intended to answer the open question from the integration-cache discussion:

- if repeated integration runs are still rebuilding Genesis work even though on-disk caches exist,
- is the blocker the random `session_id`,
- the random workspace / bundle extraction path,
- or both?

## What it measures

The benchmark drives the real `simulate_subprocess(...)` path in fresh Python child processes, but keeps the cache root stable within each scenario/mode so repeated runs can reuse disk-backed cache state if the runtime keys actually match.

The benchmark compares four modes:

1. `random_workspace_random_session`
   - current-like baseline
   - new workspace path on every repetition
   - new `INT-###-uuid8` session id on every repetition
2. `stable_workspace_random_session`
   - candidate proving whether path stability alone helps
   - same workspace path every repetition
   - random `INT-###-uuid8` session id
3. `random_workspace_stable_session`
   - candidate proving whether stable session id alone helps
   - new workspace path every repetition
   - same `INT-###` session id every repetition
4. `stable_workspace_stable_session`
   - strongest candidate
   - same workspace path every repetition
   - same `INT-###` session id every repetition

The script clears the workspace contents before each repetition even in stable-workspace mode. This preserves identical absolute paths without letting prior output files trivially shortcut later runs.

## Scenarios

The default scenarios mirror the existing simple Genesis smoke workloads already used in earlier throwaway benchmarks:

1. `int101_like`
2. `int133_like`

They are intentionally small enough to run repeatedly while still exercising the real simulation subprocess path.

## Run

From repo root:

```bash
GENESIS_FORCE_CPU=1 .venv/bin/python \
  scripts/throwaway/experiments/integration-cache-path-stability/benchmark_integration_cache_path_stability.py \
  --force-cpu \
  --backend GENESIS \
  --repetitions 3
```

Example narrower run:

```bash
GENESIS_FORCE_CPU=1 .venv/bin/python \
  scripts/throwaway/experiments/integration-cache-path-stability/benchmark_integration_cache_path_stability.py \
  --force-cpu \
  --scenario int101_like \
  --mode stable_workspace_random_session \
  --repetitions 4
```

## Output

The script writes a timestamped JSON file into this folder by default:

- `results-cache-path-stability-<timestamp>.json`

The JSON includes:

1. one row per repetition,
2. per-scenario/per-mode summaries,
3. speedups relative to `random_workspace_random_session`.

## Interpretation

- If `stable_workspace_random_session` is much faster than baseline on repeated runs, stable paths matter and session-id randomness is not the main blocker.
- If `random_workspace_stable_session` is much faster than baseline, stable `INT-###` session ids matter independently.
- If only `stable_workspace_stable_session` improves materially, both dimensions are likely part of the cache key.
- If none of the stable modes improve, the repeated rebuild cost is likely dominated by another unstable input or by cache layers unrelated to session/workspace identity.
