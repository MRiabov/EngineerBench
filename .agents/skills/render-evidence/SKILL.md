---
name: render-evidence
description: Shared render-evidence workflow for Problemologist agents. Use when previewing scenes with `render_cad(...)` for live scene inspection, inspecting render or video media through the runtime's visual-inspection path, selecting benchmark/engineer/final render bundles, resolving a screen-space pixel to a world-space hit with bundle-local render-query helpers such as `list_render_bundles(...)`, `pick_preview_pixel(...)`, `pick_preview_pixels(...)`, and `query_render_bundle(...)`, or inspecting frame-indexed `objects.parquet` pose-history sidecars.
---

# Render Evidence

## Overview

Use render artifacts as evidence, not as filenames or summaries. This skill tells agents when to materialize a new preview, when to inspect existing media, how to select the right bundle or revision, and how to perform point-pick queries against immutable bundle snapshots.

The concrete media-inspection tool name depends on the backend. In controller/API-backed runs, use the controller-provided media-inspection tool. In Codex CLI-backed runs, use the visual-inspection path the runtime exposes instead of assuming the controller tool name exists.

## Import Paths

Prefer the dedicated namespace module for preview and render-query helpers:

```python
from utils.preview import (
    list_render_bundles,
    pick_preview_pixel,
    pick_preview_pixels,
    render_cad,
    query_render_bundle,
)
```

The current callable signatures and request shapes live in [function_signatures.md](references/function_signatures.md); use that snapshot instead of re-running `help(...)` for every eval.

## Read This First

- `references/bundle-history.md` when you need to select or verify the correct render bundle.
- `references/media-inspection.md` when you need to inspect images or videos.
- `references/function_signatures.md` when you need the current render-helper signatures or the point-pick / bundle-lookup split.
- `references/point-pick.md` when you need a world-space hit or bundle-local query result from a pixel.

## Core Workflow

1. Decide whether you need a fresh render, existing evidence inspection, or a point-pick query.
2. Select a single bundle and revision for the judgment. Do not mix benchmark, engineer, and final bundles in one decision. Use `list_render_bundles()` when you need to resolve the exact bundle from history.
3. If the view or modality does not exist yet, call `render_cad(...)` to materialize it.
4. If media already exists, inspect the artifact path itself with the runtime's media-inspection tool.
5. If the task asks what is under a pixel or how a click maps into world space, call `pick_preview_pixel(...)` with the bundle path, `pixel_x`, `pixel_y`, `image_width`, `image_height`, and the matching `view_index` for that preview. If you already have a structured request, pass `RenderBundlePointPickRequest` directly. Use `pick_preview_pixels(...)` for multiple clicks.
6. Record the bundle identity, revision, view index, and artifact path in notes or review artifacts when evidence matters.

## Preview Contract

- Use `render_cad(...)` for live scene, objective-overlay, or render-bundle render evidence.
- In RGB handoff renders, a thin red line usually indicates the payload-path or motion-path overlay from the current motion contract. Treat it as review context, not as physical geometry; use the bundle's motion artifact source when you need to interpret it.

## Bundle Rules

- Prefer the latest revision only when the task is revision-scoped.
- For history or replay, resolve the bundle from the append-only render index and then read its bundle-local manifest.
- Treat `renders/render_manifest.json` as compatibility plumbing only when the runtime still exposes it.
- Simulation bundles may also persist `frames.jsonl` and `objects.parquet` sidecars at the video-capture cadence. Treat `frames.jsonl` as sparse timestamps and `objects.parquet` as the frame-indexed pose-history sidecar; inspect the MP4 and that sidecar together when motion or timing matters.
- Never infer coordinates from raw pixels or stale manifests. Filename stems such as `e0_a0` are generated from the render request and encode the rounded orbit angles for that preview; use the bundle-local manifest when you need structured metadata or exact provenance.

## Inspection Rules

- Use RGB for general scene understanding.
- Use depth for clearance, collision, and spatial separation.
- Use segmentation for identity, overlap, and repeated-instance checks.
- Inspect the actual image or video path, not a directory listing or text summary.
- If the RGB image shows a red overlay line, do not read it as a part edge or guide rail. Verify the underlying motion source before using it as evidence about geometry.
- For motion evidence, inspect the first useful frames before changing geometry.
- If the view could be front or rear, confirm camera orientation before assuming a mirror flip.
- If the task depends on exact bundle identity or revision history, resolve the bundle first and then inspect or query that bundle-local snapshot.
- If the same issue keeps failing, inspect the exact bundle again before the next change; after three consecutive failures on the same issue, keep inspecting render evidence on every subsequent retry until the blocker changes.

## Point-Pick Rules

- Query only the bundle-local scene snapshot that produced the render.
- Keep bundle identity, revision, and scene hash aligned with the queried artifact.
- Supply replayable inputs: `bundle_path`, `pixel_x`, `pixel_y`, `image_width`, `image_height`, and `view_index` are required; `orbit_pitch`, `orbit_yaw`, `bundle_id`, and `manifest_path` disambiguate the snapshot when needed.
- Treat the result as a structured hit record. Read `hit`, `world_point`, `distance`, `ray_origin`, `ray_direction`, and `object_identity` instead of treating the helper as a boolean.
- Return or record bundle identity, view identity, pixel coordinates, ray data, world point, hit state, and object identity if the helper provides them.
- Fail closed if the requested bundle, snapshot, or revision does not match the artifact on disk.

## Common Failure Modes

- Looking at the wrong revision.
- Reading filenames instead of pixels.
- Mixing benchmark, engineer, and final render buckets.
- Assuming a rear view is a mirrored front view.
- Treating inspection summaries as proof without looking at media.
- Using point-pick queries on stale bundles or mismatched snapshots.

## Role Notes

- Use this skill from benchmark planner, benchmark coder, benchmark reviewer, engineering planner, engineering coder, engineering plan reviewer, and engineering execution reviewer when render evidence is involved, including `render_cad(...)` outputs.
- Load it before making a render-based judgment or before adding render-specific guidance to a handoff.
- Keep backend-specific tool names out of Codex CLI-facing instructions unless the runtime actually exposes them.
