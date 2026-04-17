---
title: Worker-Renderer Surface Point-Cloud Rendering
status: migration
agents_affected:
  - benchmark_planner
  - benchmark_coder
  - benchmark_reviewer
  - engineer_planner
  - engineer_coder
  - engineer_execution_reviewer
added_at: '2026-04-17T15:47:12Z'
---

# Worker-Renderer Surface Point-Cloud Rendering

<!-- Migration tracker. This corrects the point-cloud contract from pose-history visualization to scene-surface sampling. -->

## Purpose

This migration adds a renderer-owned point-cloud visualization path for CAD
scenes. The target is to render the same built scene used by static preview,
but replace shaded raster surfaces with sampled surface points so operators can
inspect placement and clearances more precisely.

The key constraints are:

1. The source geometry is the scene snapshot or built CAD geometry used for
   static preview, not `objects.parquet` or any other pose-history table.
2. The point-cloud mode lives in `worker-renderer` and reuses the same scene
   assembly, camera framing, bundle materialization, and manifest plumbing as
   the raster preview path.
3. The public `render_cad(...)` helper stays raster-first and does not grow
   point-cloud-specific options.
4. Point-cloud rendering remains callable through a renderer-owned helper or
   route so downstream tools can reuse the path later.
5. The renderer exposes a visualization backend selector for point-cloud
   output. The implementation may support `vtk`, `matplotlib`, or both, but
   it should not require callers to care which one is used internally.
6. The render output is image-first and static. No motion synthesis, playback,
   or physics sampling is part of this migration.

Relevant architecture context:

- [Simulation and Rendering](../../architecture/simulation-and-rendering.md)
- [CAD and other infrastructure](../../architecture/CAD-and-other-infra.md)
- [Shared Scene Builder for Static Preview and Physics](./shared-scene-builder-static-preview-physics.md)

The migration keeps the existing preview and handoff render ownership intact.
Point-cloud rendering is a sibling renderer capability, not a replacement for
the raster preview contract and not a pose-history visualization API.

## Problem Statement

The current render stack can already produce raster previews and persistent
handoff bundles, but point-cloud visualization is not first-class in the shared
scene-render path.

1. Existing preview routes rasterize surfaces; they do not provide a
   scene-surface point-cloud mode.
2. The renderer should sample object surfaces from the built scene, not from a
   pose-history sidecar or a separate geometry export path.
3. Adding point-cloud flags directly to `render_cad(...)` and the 24-view
   bundle helper would make those public surfaces wider than they need to be.
4. The renderer should own surface sampling because sampling, camera framing,
   and image formation are render concerns, not authoring concerns.
5. The point-cloud path must stay deterministic and bundle-scoped so the same
   scene revision can be replayed and reviewed consistently.

## Current-State Inventory

| Area | Current behavior | Why it must change |
| -- | -- | -- |
| `worker_renderer/api/routes.py` | Exposes raster preview routes and a point-cloud route, but the point-cloud path is not yet framed as a scene-surface variant of preview rendering. | The route should share the preview scene pipeline and surface-sampling logic. |
| `worker_renderer/utils/point_cloud_rendering.py` | Contains point-cloud rendering code, but the source contract is pose-history oriented. | The helper needs to sample surface points from built CAD geometry. |
| `shared/workers/schema.py` | Defines a point-cloud request shape that is too specific to the current wrong source and route semantics. | The request contract must describe scene-based point-cloud rendering and renderer-owned selection. |
| `shared/rendering/renderer_client.py` | Exposes a point-cloud helper, but the helper should map to the scene-surface contract instead of a pose-history debug path. | Callers need a stable entrypoint that reuses the renderer boundary. |
| `shared/rendering/preview_scene.py` and `worker_renderer/utils/build123d_rendering.py` | Already own the scene snapshot and camera math used by preview rendering. | These are the right reuse points for point-cloud generation. |
| `tests/integration/architecture_p0/test_architecture_p0.py` | Lacks a live integration slice that proves the point-cloud path uses the same scene contract as preview. | The boundary needs real-system verification. |

## Proposed Target State

1. The renderer worker owns a point-cloud scene-render mode for CAD scenes.
2. The render source is the same scene geometry used by static preview,
   including benchmark fixtures and engineer solution geometry when present.
3. Surface samples are taken from object surfaces after scene assembly. The
   sampling may be area-weighted over tessellated faces or an equivalent
   renderer-owned surface sampler, but it must be deterministic for a fixed
   scene and budget.
4. The point-cloud path uses the same bundle context, scene snapshot, camera
   normalization, manifest writing, and render artifact publication as the
   raster preview path.
5. A dedicated renderer-owned helper or route exposes point-cloud rendering
   for debugging and downstream reuse, but the main `render_cad(...)` helper
   and 24-view bundle builder stay focused on raster preview.
6. The point-cloud helper accepts a backend selector and can render through
   `vtk`, `matplotlib`, or both. The contract is satisfied if at least one
   renderer-owned backend is available and deterministic.
7. If the renderer persists a sampled-point sidecar or cache, that artifact is
   bundle-local and derived from scene geometry. It is not a pose-history
   table.
8. The output stays static: no animation, no playback, and no fallback to
   `worker-heavy`.

## Required Work

### 1. Introduce a shared surface-sampling render core

- Reuse the scene snapshot and camera setup that already power raster preview.
- Build a deterministic point-cloud sampler that operates on scene surfaces.
- Keep axes, framing, and bundle manifest behavior consistent with existing
  preview renders.
- Ensure the point-cloud core can be called from a dedicated route and from any
  future renderer-owned caller that needs the same visualization.

### 2. Retarget the point-cloud request and client helpers

- Keep the renderer-facing request explicit about scene-surface rendering,
  output naming, sample budget, camera framing, and backend selection.
- Remove any contract language that implies `objects.parquet` or pose-history
  lookup is the source of truth.
- Preserve the same response shape and workspace publication behavior used by
  the other renderer helpers.

### 3. Wire the mode into the renderer boundary

- Keep the public preview helper and 24-view publication path thin.
- Route point-cloud rendering through the same renderer-owned bundle and
  manifest plumbing so the code path stays reusable.
- Avoid a duplicate scene builder or a second render stack just for point
  clouds.

### 4. Add boundary coverage

- Add a live integration test that exercises the renderer with a real scene
  bundle.
- Assert that the endpoint or helper returns a point-cloud image generated
  from scene surfaces.
- Assert that the path remains bounded and deterministic for a fixed scene and
  sample budget.
- Assert that the route uses the shared scene reconstruction path instead of a
  pose-history sidecar.

## Non-Goals

- Do not change static raster preview behavior.
- Do not turn `render_cad(...)` into a point-cloud-specific public API.
- Do not add animation, simulation playback, or motion synthesis.
- Do not make `worker-heavy` responsible for point-cloud rendering.
- Do not keep `objects.parquet` as the primary point-cloud source.
- Do not create a generic geometry export service.
- Do not add a second render bundle format just for point clouds.

## Sequencing

The migration should land in this order:

1. Add the shared surface-sampling core inside `worker-renderer`.
2. Retarget the request and client surface to the scene-surface contract.
3. Wire the point-cloud mode through the renderer bundle plumbing.
4. Add integration coverage and tighten the architecture docs if needed.

## Acceptance Criteria

1. The renderer can produce a static point-cloud image from the same scene
   geometry used by raster preview.
2. The sampled points come from object surfaces, not pose-history data.
3. The point-cloud path reuses the renderer's scene reconstruction, bundle
   publication, and manifest plumbing.
4. Public `render_cad(...)` remains raster-focused and does not gain
   point-cloud-specific options.
5. The point-cloud path is available through a renderer-owned helper or route
   for debug and downstream use.
6. The point-cloud renderer can use `vtk`, `matplotlib`, or both, and callers
   can request the backend explicitly.
7. The narrow integration slice passes through `./scripts/run_integration_tests.sh`.

## File-Level Change Set

- `worker_renderer/api/routes.py`
- `worker_renderer/utils/point_cloud_rendering.py`
- `shared/workers/schema.py`
- `shared/rendering/renderer_client.py`
- `shared/rendering/preview_scene.py`
- `worker_renderer/utils/build123d_rendering.py`
- `tests/integration/architecture_p0/test_architecture_p0.py`

## Migration Checklist

Use this checklist to track the migration from spec to runtime behavior. Do
not close the migration until each unchecked item has either landed or been
explicitly waived with a written rationale.

### Contract plumbing

- [ ] Update `shared/workers/schema.py` so the point-cloud request model is
  explicitly scene-surface based, keeps the backend selector visible, and
  does not describe `objects.parquet` or any pose-history source as the
  contract root.
- [ ] Update `shared/rendering/renderer_client.py` so `render_point_cloud(...)`
  forwards the backend selector and stays the renderer-owned entrypoint for
  the debug path.
- [ ] Keep `render_cad(...)` and the 24-view helper surface raster-focused; do
  not add a point-cloud switch to the public preview API.
- [ ] Preserve the existing render response and bundle manifest shape so the
  point-cloud route publishes through the same workspace-visible plumbing as
  the other renderer helpers.

### Renderer implementation

- [ ] Reuse `shared/rendering/preview_scene.py` and
  `worker_renderer/utils/build123d_rendering.py` so point-cloud rendering
  uses the same scene reconstruction and camera framing as raster preview.
- [ ] Implement the scene-surface sampler in
  `worker_renderer/utils/point_cloud_rendering.py` so sampled points come
  from object surfaces and remain deterministic for a fixed scene and
  sample budget.
- [ ] Keep the backend choice explicit and support at least one renderer-owned
  backend path (`vtk`, `matplotlib`, or both) behind the same public
  request contract.
- [ ] Keep any sampled-point cache or sidecar bundle-local and derived from the
  scene geometry only.
- [ ] Ensure the helper writes the point-cloud image through the existing
  bundle publication flow and never falls back to `worker-heavy`.

### Route wiring

- [ ] Update `worker_renderer/api/routes.py` so `/debug/render_point_cloud`
  calls the shared surface-sampling core through the renderer boundary.
- [ ] Make the route resolve the same scene bundle context as static preview so
  both paths inspect the same scene revision.
- [ ] Fail closed when the scene cannot be resolved, the backend is unsupported,
  or the sampled surface set is empty.
- [ ] Keep the route debug-owned and reusable by downstream callers without
  turning it into a generic geometry export API.

### Validation and docs

- [ ] Add or update the integration test in
  `tests/integration/architecture_p0/test_architecture_p0.py` to render a
  real scene bundle through the point-cloud route.
- [ ] Assert that the output image exists and the bundle manifest points at the
  expected artifact path.
- [ ] Assert that the render is deterministic for a fixed scene and sample
  budget.
- [ ] Assert that the sampled points come from the scene surface path rather
  than pose-history data.
- [ ] Verify the narrow integration slice passes through
  `./scripts/run_integration_tests.sh`.
- [ ] Update architecture wording if any doc still describes the point-cloud
  route as a pose-history debug endpoint.
