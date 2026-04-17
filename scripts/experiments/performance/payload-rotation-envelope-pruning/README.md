# Payload Rotation Envelope Pruning Benchmark

This experiment measures the optimization you were asking for:

1. a naive uniform orientation grid, and
2. an adaptive search that uses a conservative broad phase plus recursive subdivision.

The point is to make the planning cost visible in numbers:

- how many exact `build123d` booleans the naive search needs,
- how many exact booleans the adaptive search needs,
- how much wall time each mode takes,
- and the speedup of adaptive over naive.

The geometry setup is intentionally job-scoped:

- `part_to_trimesh()` runs once per scenario during setup,
- the search loop reuses the derived mesh radius and does not reinitialize
  trimesh,
- and mesh export/import stays out of the inner loop so the hot path remains
  CPU-bound.

## Hypothesis

The hypothesis is that a bounded adaptive search will reduce exact intersection work compared with a naive grid over the same rotation window.

In practice that means:

- `naive_grid` checks every sampled orientation in the window.
- `adaptive_pruning` rejects many cells with broad-phase bounds and only runs exact intersections on leaf cells that survive the pruning.

## Scenarios

The script ships with three demo scenarios:

1. `demo_immediate_hit`

   - the nominal pose collides immediately
   - shows the edge case where the naive grid can be cheaper than the adaptive overhead

2. `demo_recursive_prune`

   - the payload is translated to a case where the naive grid checks every cell
   - shows the adaptive search using recursive subdivision and broad-phase pruning

3. `demo_far_miss`

   - the payload is translated far away from the fixture
   - shows the broad phase rejecting the whole rotation cell quickly

You can also pass `--payload-step` and `--fixture-step` to benchmark your own geometry against the same search strategy.

## Run

From repo root:

```bash
./.venv/bin/python \
  scripts/experiments/performance/payload-rotation-envelope-pruning/benchmark_payload_rotation_envelope_pruning.py \
  --scenario all \
  --repetitions 1
```

If you want to inspect a single scenario:

```bash
./.venv/bin/python \
  scripts/experiments/performance/payload-rotation-envelope-pruning/benchmark_payload_rotation_envelope_pruning.py \
  --scenario demo_recursive_prune \
  --repetitions 1
```

## Output

The script writes a timestamped JSON file into this folder by default.

The JSON contains:

- `metadata`
  - the hypothesis
  - the naive baseline definition
  - the adaptive candidate definition
  - the geometry cache contract
- `rows`
  - raw per-run measurements for each mode and repetition
- `scenarios`
  - per-scenario summaries
  - adaptive search traces
- `summary`
  - per-scenario mode aggregates
  - speedups versus naive

## Reading The Results

Look at these fields first:

- `summary.by_scenario.<scenario>.speedups.elapsed_speedup_over_naive`
- `summary.by_scenario.<scenario>.speedups.exact_check_reduction_pct`
- `summary.by_scenario.<scenario>.modes.naive_grid.mean_exact_checks`
- `summary.by_scenario.<scenario>.modes.adaptive_pruning.mean_exact_checks`

Interpretation:

- `elapsed_speedup_over_naive > 1.0` means the adaptive search is faster.
- `exact_check_reduction_pct > 0` means the adaptive search performs fewer exact booleans.
- `budget_exhausted = true` means the search failed closed instead of silently accepting an unproven envelope.
- `metadata.geometry_cache_contract.search_loop_reinitializes_trimesh = false`
  means the experiment is validating the exact rule we want in the migration:
  setup once, then reuse cached geometry in memory.
