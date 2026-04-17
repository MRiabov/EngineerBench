# Rendering

## Scope summary

- Primary focus: render-worker boundary, preview rendering, render bundle layout, visual-evidence inspection, and render-query helper contracts.
- Defines the explicit preview path, the persistent handoff-bundle path, the render index and manifest rules, and the config-driven modality policy that controls what is emitted.
- Use this file for preview renders, point-cloud debug output, render bundle publication, and any contract that depends on `inspect_media(...)` or `render_cad(...)`.

## Dedicated render services

Rendering is split by artifact family:

1. explicit preview renders, preview-style image post-processing, and the scene-surface point-cloud debug path run in a dedicated headless `worker-renderer` container,
2. simulation-video rendering is a switchable contract between `worker-heavy` and `worker-renderer`; the current implementation keeps it on `worker-heavy`/MuJoCo because that is the lowest-overhead route,
3. selection snapshots, depth renders, segmentation renders, point-cloud debug renders, and preview-manifest generation remain in `worker-renderer`.

Static validation does not generate preview artifacts by default. Explicit preview requests use the same renderer worker boundary instead of a validation-time render path.

The render worker does not inherit a host X server as its normal execution path. The active physics backend and the renderer each select their own OpenGL backend through explicit environment variables, with the renderer defaulting to an OSMesa-backed VTK window class for headless reliability.

The render backend is not a single global choice. Rendering is split by purpose:

1. explicit preview renders use the renderer worker's selected backend inside `worker-renderer`,
2. simulation-video rendering is a switchable contract; the current implementation keeps it on `worker-heavy`/MuJoCo because that was the lowest-overhead route,
3. Genesis-native visual outputs follow the selected simulation backend when the artifact depends on backend-native simulation state output.

This split is intentional. Preview evidence does not require Genesis runtime features and therefore stays on the renderer-worker preview path, but it is produced only on demand through the dedicated render worker boundary. The point-cloud helper follows the same renderer boundary and scene reconstruction, but it visualizes sampled object surfaces instead of shaded raster output.

The renderer worker is the only service that owns VTK, EGL, OpenGL, and related graphics backend dependencies.

### Headless backend selection

The renderer worker selects its VTK OpenGL window class explicitly rather than relying on whatever the host process happens to expose.

The runtime rules are:

1. `VTK_DEFAULT_OPENGL_WINDOW` is part of the renderer worker contract and is honored by the render bootstrap,
2. the active physics backend owns its own accepted GL backend list through `PROBLEMOLOGIST_PHYSICS_GL_BACKEND`; MuJoCo currently accepts EGL, while Genesis has a backend-specific list,
3. the current renderer deployment defaults to OSMesa for reliability in headless Linux environments, with EGL still available as an explicit opt-in backend for environments that support it,
4. `PROBLEMOLOGIST_RENDER_GL_BACKEND` selects the renderer backend, and the render bootstrap resolves that into the matching VTK window class,
5. the renderer worker does not depend on Xvfb as its normal launch path,
6. a native `Render()` segfault is a backend/runtime failure, not a valid render completion.

The practical consequence is that the renderer image must contain the required Mesa/VTK runtime pieces for the selected backend, and the machine or container must be checked against a real render probe rather than package presence alone.

## Preview and handoff renders

Preview rendering is explicit, not a validation side effect.

### On-demand preview API

`render_cad(...)` is the worker-light-facing helper for explicit preview evidence. Benchmark callers compose `build()` output with objective overlays reconstructed through the public `utils.objectives_geometry()` helper from the `objectives` section of `benchmark_definition.yaml` before previewing benchmark context, while engineer callers preview their solution geometry directly and may optionally overlay payload-path context with `payload_path=True`. The helper is part of the exposed `utils` package, alongside `render_cad()` and the role-scoped validation helpers (`validate_benchmark()` and `validate_engineering()`), so callers import it instead of defining benchmark-specific geometry logic in agent code. It accepts modality booleans, the optional `payload_path` overlay flag, and multi-view camera inputs, normalizes scalar values into view bundles, returns a job ack, and causes the renderer worker to persist workflow-specific preview artifacts into `renders/current-episode/` while the active stage is running.

The separate `render_point_cloud(bundle_base64: str, sample_limit: int = 50000, point_size_px: int = 4, render_backend: PointCloudRenderBackend = PointCloudRenderBackend.VTK, output_name: str = "point_cloud.png")` helper uses the same renderer boundary and scene reconstruction, but it samples object surfaces into a point cloud instead of producing a raster preview. It accepts an explicit backend selector and may use `vtk` or `matplotlib`; the implementation may support one or both.

When the overlay flag is enabled, the renderer composites the finest available payload-path artifact for the current workflow into the static render bundle; the overlay is review context only and does not establish build-safe starts or goal-zone finish semantics.

Manual preview artifacts are ephemeral scratch: they are deleted at handoff and never promoted into the persisted handoff bundles.

### Preview file naming

The canonical RGB preview filename rule is `{part_name}_render_{angle_1}_{angle_2}.png`, where `part_name` comes from the rendered component label. The default 45/45 orbit for `Part(Box(), label="test_part")` therefore produces `test_part_render_e45_a45.png`.

### Persistent handoff bundles

Preview evidence is generated explicitly, not as a validation side effect. The default policy is:

1. `/benchmark/validate` performs validation only and does not generate preview artifacts by default,
2. `render_cad(...)` generates ephemeral manual render evidence under `renders/current-episode/` for the active stage,
3. stage handoffs generate 24-view persistent bundles separately under:
   1. benchmark render evidence under `renders/benchmark_renders/`,
   2. engineering planner handoff evidence under `renders/engineer_plan_renders/`,
   3. final solution submission evidence under `renders/final_solution_submission_renders/`.

These persistent bundles are read-only to agent roles; only backend/runtime utilities write them, and `renders/current-episode/` is cleared at handoff.

For renderer-backed handoff renders, the requested modality set is persisted under the selected persistent bundle directory and the manifest records the modality-specific artifact path and request-scoped view index for each requested view. RGB handoff bundles display the payload-path overlay specified by the relevant benchmark or engineer motion contract by default. RGB previews preserve material colors. Depth and segmentation previews remain PNG-based, and segmentation renders carry a legend mapping colors to object identity.

Those persistent bundle files are context artifacts for downstream agents and reviewers. They follow the same persistence/discovery flow as the existing preview images rather than introducing a second artifact channel, and the render path itself encodes whether the evidence belongs to benchmark input, engineer planning, or final solution submission. The scratch tree under `renders/current-episode/` is excluded from this promotion flow.

### Render bundle layout and sidecars

Persistent render outputs are published as immutable bundle directories under `renders/benchmark_renders/`, `renders/engineer_plan_renders/`, and `renders/final_solution_submission_renders/`. Each bundle carries a bundle-local render manifest plus any sidecars needed for later lookup. Any PNG/JPG path declared by the manifest must exist in the same bundle, and the manifest image set must stay consistent with `preview_evidence_paths`. The append-only discovery surface is `renders/render_index.jsonl`, which records `bundle_id`, `created_at`, `revision`, `scene_hash`, bundle path, and primary media paths for each published bundle. `renders/current-episode/` is scratch-only and does not enter the index. `renders/render_manifest.json` may remain as a latest-bundle compatibility alias for current-revision tooling, but the bundle-local manifest and history index are the source of truth for historical lookup.

Bundle-local sidecars are allowed when they help agent tooling resolve the exact render state:

1. `preview_scene.json` stores the exact scene snapshot used for preview rendering, including any runtime benchmark payload entity when the benchmark declares one,
2. `frames.jsonl` stores sparse frame metadata for video evidence,
3. `objects.parquet` stores dense, frame-indexed object pose tables for query helpers. The active `PhysicsBackend` export path samples poses at the video-capture cadence and produces this file without per-step logging overhead, so both MuJoCo and Genesis can emit it.

When the manifest advertises MP4 evidence, the matching `frames.jsonl` and `objects.parquet` sidecars are required rather than optional.

The worker-light render-query helper family resolves against these bundle-local artifacts when it needs a point coordinate from a render. It does not infer coordinates from the video bytes alone.

For segmentation renders, the bundle-local manifest must contain a legend mapping rendered colors to object identity. The legend is instance-aware:

1. `semantic_label` is the model-facing semantic name,
2. `instance_id` / `instance_name` distinguishes repeated instances of the same semantic part,
3. repeated parts therefore appear as multiple legend rows that may share `semantic_label` but must not share `instance_id`.

When `inspect_media(...)` reads a render artifact, it resolves metadata from the bundle-local manifest for that bundle. The global `renders/render_manifest.json` path remains compatibility plumbing for current-revision tooling.

### Render modality policy

Render-modality emission is config-driven through `config/agents_config.yaml`:

```yaml
render:
  split_video_renders_to_images: true
  video_frame_attachment_stride: 6
  video_frame_jpeg_quality_percent: 85
  rgb:
    enabled: true
    axes: true
    edges: true
  depth:
    enabled: true
    axes: true
    edges: true
  segmentation:
    enabled: true
    axes: true
    edges: true
  handoff_rgb_payload_path_overlay:
    enabled: true
```

If one of the `enabled` flags is set to `false`, the corresponding preview artifact type is not emitted into `renders/**`. This switch controls static preview artifact persistence, not the higher-level worker routing policy.

`split_video_renders_to_images` is separate from the static preview modality flags. When enabled, agent-facing media inspection may decode persisted `.mp4` artifacts into representative image frames for multimodal review. The sampling cadence is controlled by `video_frame_attachment_stride`, which means the tool attaches every Nth frame rather than imposing a fixed cap. `video_frame_jpeg_quality_percent` controls the JPEG encoding quality as a percent value. These settings do not change which artifacts are stored, only how `inspect_media(...)` attaches them to the model.

Each modality can independently enable world-coordinate axes and edge emphasis. Those overlays are controlled by `render.<modality>.axes` and `render.<modality>.edges`.

The RGB static preview can overlay adaptive world-coordinate axes with tick labels and a subtle CAD-style edge emphasis. Depth and segmentation previews can use the same axes overlay, and their edge highlights use a visible non-black accent so they do not disappear into the background or read as void. The handoff RGB payload-path overlay is controlled separately by `render.handoff_rgb_payload_path_overlay.enabled`; it defaults to on for persistent handoff bundles and can be disabled when a workflow needs a clean RGB bundle. That switch affects only the persistent handoff bundle path, not explicit scratch previews requested with `render_cad(..., payload_path=True)`.

### Simulation video evidence

Agent-facing inspection of persisted simulation video is config-driven. When `config/agents_config.yaml` sets `render.split_video_renders_to_images=true`, `inspect_media(...)` may decode an `.mp4` artifact into representative image frames and attach those frames to the model instead of exposing the raw video bytes as a dead end. The sampling stride is controlled by `render.video_frame_attachment_stride`, so a 60-frame video with stride 6 yields 10 attached frames, while a 6-frame video yields 1 attached frame. `render.video_frame_jpeg_quality_percent` controls the JPEG encoding quality as a percent value. The stored MP4 remains the canonical simulation artifact; the split only affects multimodal review.

The low-frequency simulation-time frame sync path is an opt-in websocket stream for simulation evidence. The stream targets roughly one PNG every 0.5s of simulated time and is designed to stay manageable because the cadence is low; the final MP4 remains the canonical persisted artifact. Incremental S3 upload of those live frames remains an extension point if a future revision needs bundle-backed persistence for the stream itself.

### Render profile ownership

The render contract for dynamic simulation evidence is runtime-resolved and recorded with the simulation result, not by benchmark-level task config or agent config.

The rule is:

01. simulation video is intended to be a backend/service switch,
02. the runtime-selected simulation render choice is serialized in `simulation_result.json` so reviewers can replay the exact evidence path,
03. explicit preview remains a separate preview contract, executed by the renderer worker, and continues to live in the preview manifest path,
04. the renderer-owned `render_point_cloud(...)` helper is a sibling scene-surface debug path with its own backend selector, and it may use `vtk`, `matplotlib`, or both,
05. `render_cad(...)` is the ephemeral on-demand path that writes into `renders/current-episode/` for the active stage,
06. when `render_cad(..., payload_path=True)` is requested, the static render bundle may also include a motion-path overlay, but the overlay is review context only and does not affect validation or simulation semantics,
07. every persistent handoff render request publishes an immutable 24-view bundle directory with a bundle-local manifest, using the established 8-azimuth by 3-elevation view family,
08. the render bundle path itself identifies whether the evidence belongs to benchmark input, engineer planning, or final solution submission,
09. final solution submission bundles must be composed from the benchmark-owned scene, including any declared benchmark payload, plus the approved engineer solution so benchmark fixtures and objective overlays are present by default,
10. if a backend cannot satisfy the selected render path, the failure should surface as a validation/runtime contract error rather than being hidden behind an unrelated global fallback,
11. all static rendering, ever, should be worker-renderer, not scattered around the codebase.

The preview and render bundle paths stay containerized because that avoids EGL and OSMesa misconfiguration drift. Any renderer-emitted file that crosses the `worker-renderer` boundary should already be backed by S3, with worker-light or controller code using the object key to re-materialize it locally if needed.

This keeps MuJoCo and Genesis distinct while still allowing each backend to use its own canonical default view when the runtime resolver allows that.
