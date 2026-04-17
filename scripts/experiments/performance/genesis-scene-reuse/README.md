# Genesis Scene Reuse Experiment

This experiment separates three costs that were conflated in earlier discussion:

1. process-global Genesis warmup,
2. same-scene repeat cost inside one warm process,
3. different-scene-next cost inside one warm process.

The experiment intentionally keeps all work inside one process after a single
`gs.init(...)` so that we can see what changes when the scene or object changes
without paying fresh-child startup again.

## What it answers

- Whether the earlier warm-process speedup was only an artifact of repeating the
  exact same scene.
- Whether a different object still pays a large scene-specific rebuild cost even
  when the process is already warm.
- How much reuse remains when the process stays alive but the object changes.

## Scenarios

The script runs two families of scenes:

1. Primitive scenes

   - `primitive_box_1`
   - `primitive_box_2_same`
   - `primitive_sphere_1_diff`
   - `primitive_box_3_after_sphere`

2. Mesh scenes

   - `mesh_box_1`
   - `mesh_box_2_same`
   - `mesh_sphere_1_diff`
   - `mesh_box_3_after_sphere`

The `*_same` scene repeats the same object family in the same warm process.
The `*_diff` scene switches to a different object family in the same warm
process.
The `*_after_sphere` scene reruns the original box after the sphere to check
whether the sphere path poisoned or reset the earlier box warm state.

## Run

From repo root:

```bash
.venv/bin/python scripts/experiments/genesis-scene-reuse/benchmark_same_vs_different_scenes.py --backend cpu
```

The script writes a timestamped JSON result into this folder by default.

For the stricter uncached-geometry version that generates unique intersected-box
meshes with `build123d` and validates that each intersection volume is strictly
smaller than both source boxes:

```bash
.venv/bin/python scripts/experiments/genesis-scene-reuse/benchmark_randomized_intersection_boxes.py --backend cpu
```

Baseline harness from the earlier init/reuse discussion is also persisted here:

- `genesis_init_benchmark_baseline.py`

## Interpretation

- If `same` is much cheaper than the first run, process-local warm reuse is real.
- If `diff` is close to `same`, object-specific rebuild is minor for that case.
- If `diff` is much closer to the first run than to `same`, object-specific
  rebuild dominates for that case.
- If `after_sphere` stays close to `same`, the different-object detour did not
  reset the original box path.
- If `after_sphere` jumps back toward `first`, the different-object detour
  effectively invalidated the earlier warm state for that family.

This experiment does not exercise the full heavy-worker path. It isolates
Genesis scene construction cost inside one process after one init.

The randomized-intersection-box benchmark is the more rigorous follow-up when
you need to rule out same-geometry cache effects.
