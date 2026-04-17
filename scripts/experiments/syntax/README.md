# DSPy Tool Syntax Probe

This experiment answers four narrow debugging questions:

1. Does `dspy.ReAct` in our installed DSPy version force the `next_thought` / `next_tool_name` / `next_tool_args` contract?
2. Does `dspy.ChatAdapter` silently fall back to `JSONAdapter` by default?
3. If we bypass `dspy.ReAct`, can DSPy itself still produce native tool calls through `ToolCalls`?
4. Does the provider path support native tool calls independently of DSPy ReAct?

## Run

Inspect the installed DSPy runtime only:

```bash
uv run python scripts/experiments/syntax/probe_dspy_tool_syntax.py
```

Run the live DSPy-native tool-call probe:

```bash
uv run python scripts/experiments/syntax/probe_dspy_tool_syntax.py --live-dspy-native
```

Run the direct provider-native probe:

```bash
uv run python scripts/experiments/syntax/probe_dspy_tool_syntax.py --live-openrouter
```

Run both live probes:

```bash
uv run python scripts/experiments/syntax/probe_dspy_tool_syntax.py \
  --live-dspy-native \
  --live-openrouter
```

## Interpretation

- `react_forces_next_tool_fields=true` means this DSPy ReAct version is inherently using the textual `next_tool_*` protocol.
- `chat_adapter_default.use_json_adapter_fallback=true` means malformed chat output can silently switch parsing modes unless we disable that in runtime code.
- `dspy_native_tool_probe.tool_calls_present=true` means DSPy itself is still usable if we replace `ReAct` with a custom tool loop.
- `openrouter_native_tool_probe.tool_calls_present=true` means the provider path supports native tools, so the text protocol is a DSPy runtime choice rather than an OpenRouter limitation.

# Build123d Construction Signature Probe

This experiment inspects whether `build123d` exposes enough authored object metadata to support a tolerant semantic comparison gate instead of a brittle mesh-equality check.

1. Do primitive objects such as `Box`, `Cylinder`, and `Rectangle` retain their authored parameters on the object?
2. Does the fused `BuildPart` output keep any child history after boolean fusion?
3. What coarse topology metrics remain available on the final `Part`?

## Run

Inspect the installed `build123d` runtime only:

```bash
uv run python scripts/experiments/syntax/probe_build123d_construction_signature.py
```

## Interpretation

- `primitive.visible_dict` shows the authored parameters exposed directly by the primitive object.
- `build123d_part.children_count=0` means the fused output does not keep a direct child tree in this probe, so a validator cannot rely on the final `Part` alone for semantic reconstruction.
- `build123d_part.solids_count`, `faces_count`, `edges_count`, and `wires_count` are the coarse invariants available for fallback comparison.
- The intended conclusion is whether the runtime should compare authored construction metadata first and use coarse geometric invariants only as a fallback.

# Renderer Launchability Probe

This experiment checks whether the renderer can actually complete a minimal `Render()`
call under the current VTK/EGL/OSMesa configuration.

1. Does a minimal offscreen VTK scene survive a render call in a subprocess?
2. Does the build123d preview renderer survive the same launch path?
3. Which render window class is selected in each scenario?

## Run

Inspect the launchability matrix:

```bash
uv run python scripts/experiments/syntax/probe_renderer_launchability.py
```

## Interpretation

- `scenario.returncode=0` means that launch path survived `Render()` and returned
  a structured report.
- `scenario.returncode=139` means the subprocess segfaulted during render.
- `window_class` tells you whether VTK selected `vtkEGLRenderWindow`,
  `vtkOSOpenGLRenderWindow`, or the fallback `vtkRenderWindow`.

# MuJoCo Parallel Step Probe

This experiment checks the actual MuJoCo stepping paths available in the current
wheel and separates the single-scene and batched cases:

1. Does `mj_step(model, data, nstep=...)` work here?
2. Is `mujoco.rollout` available as the official batched rollout path?
3. Does the rollout API support MuJoCo-managed pool reuse via `persistent_pool`
   or a reusable `Rollout` object?

## Run

Inspect the installed MuJoCo runtime only:

```bash
uv run python scripts/experiments/syntax/probe_mujoco_parallel_step.py
```

Use a different model or a wider batch:

```bash
uv run python scripts/experiments/syntax/probe_mujoco_parallel_step.py \
  --model-path tests/worker/minimal.xml \
  --batch-size 4 \
  --steps 2000 \
  --repetitions 3 \
  --workers 4
```

## Interpretation

- `api_probe.mj_step_supports_nstep=true` means the wheel accepts the direct
  single-scene `mj_step(..., nstep=...)` syntax, which removes Python-loop
  overhead for one trajectory.
- `timings.single_scene_nstep.mean_s` should be compared with
  `timings.single_scene_loop.mean_s` to see how much overhead the Python loop is
  adding for one scene.
- `timings.rollout_object.mean_s` and `timings.rollout_persistent_pool.mean_s`
  show the supported batched rollout paths when MuJoCo owns the worker pool.
- `rollout_probe.*.state_shape` shows the official batched rollout output shape
  for the configured batch size.
- `batch_size` is the number of independent trajectories in the batch.
- `nthread` is the number of MuJoCo rollout workers used by the probe.

## Observed Result

On `2026-04-17`, running the probe against `tests/worker/minimal.xml` with
`--batch-size 20 --steps 2000 --repetitions 3 --workers 20` produced:

- Batched Python loop: `0.2358 s` mean.
- `mujoco.rollout` with a fresh pool: `0.0676 s` mean, `3.49x` faster than the Python loop.
- `mujoco.rollout` via reusable `Rollout(nthread=20)`: `0.0670 s` mean, `3.52x` faster.
- `mujoco.rollout` with `persistent_pool=True`: `0.0674 s` mean, `3.50x` faster.
- Single-scene Python loop: `0.0147 s` mean.
- Single-scene `mj_step(..., nstep=2000)`: `0.00954 s` mean, `1.54x` faster.

These numbers are directionally useful for the probe model. They are not yet a
measurement of `verify_with_jitter()` itself.

# Eval Display Environment Probe

This companion experiment records the environment behavior that affected recent
Codex eval runs:

1. Does `build_codex_env()` preserve the host `DISPLAY` and `XAUTHORITY` for local eval workspaces?
2. Does the spawned agent process inherit that `DISPLAY` and keep the host
   `XAUTHORITY`?
3. Does `worker_heavy.utils.vtk_display.ensure_headless_vtk_display()` stay on
   the ambient display path and fail closed if it is unusable?

## Run

Inspect the launcher and runtime display behavior:

```bash
uv run python scripts/experiments/syntax/probe_eval_display_env.py
```

## Interpretation

- `codex_env.DISPLAY=:0` means the eval launcher is preserving the host display
  instead of synthesizing a fallback display.
- `codex_env.XAUTHORITY=/run/user/...` means the Codex child env preserved the
  host Xauthority cookie, which is required for `DISPLAY=:0` to be usable on
  this machine.
- `current_env.DISPLAY` shows what the shell session itself is advertising.
- `ambient_vtk_display` populated with a display number means the worker render
  bootstrap accepted the ambient display.
- `ambient_vtk_display_error` populated instead means the render bootstrap
  failed closed before rendering because the ambient display was unusable.
