---
name: worker-renderer-rendering
description: Developer-side rendering through the dedicated `worker-renderer` container and the shared renderer client. Use when you need preview renders, static preview bundles, point-cloud debug renders, simulation-video encoding, or renderer health/readiness checks from this repository, especially when `render_cad()` is unavailable, unreliable, or the wrong runtime boundary.
---

# Worker Renderer Rendering

## Overview

Render through `worker-renderer`, not local VTK/OSMesa helpers and not `render_cad()`. In this repository the renderer is containerized, headless, and the only supported place to produce preview images, point-cloud debug renders, and simulation MP4s.

## Core Rules

1. Prefer `shared.rendering.renderer_client` when writing repo code. It already handles base URL selection, busy retries, request validation, and response materialization. Use the explicit helpers first: `render_preview`, `render_static_preview`, `render_point_cloud`, and `render_simulation_video`; treat `render_cad` as a compatibility alias for the preview route.
2. Use direct HTTP only for ad hoc debugging or when you need to confirm the raw route contract.
3. Check `GET /health` and `GET /ready` before debugging a render failure. `503` from `/ready` means the renderer is single-flight busy.
4. Send the smallest request that exercises the needed artifact. Preview requests should include only the modalities and views you need.
5. Materialize returned blobs or object-store keys into the workspace before inspecting files.
6. Do not try to fix rendering by setting local GL, X11, or `DISPLAY` state. The renderer container owns the graphics backend.

## Endpoint Map

- `GET /health` - boot probe.
- `GET /ready` - admission probe; returns `503 WORKER_BUSY` while a render is active.
- `GET /` - service root.
- `GET /docs` and `GET /openapi.json` - schema discovery when route shapes drift.
- `POST /benchmark/render_cad` - scratch preview renders.
- `POST /benchmark/preview` - deprecated compatibility alias for the same preview route.
- `POST /benchmark/static-preview` - bundle-backed static validation preview.
- `POST /debug/render_point_cloud` - point-cloud debug render.
- `POST /benchmark/simulation-video` - encode captured frames into an MP4.

## Request Contract

- Send `X-Session-ID` on render calls; add `X-Agent-Role` when the route needs role-based artifact routing.
- Submit workspace snapshots as `bundle_base64` when the route expects a bundle.
- `PreviewDesignRequest` supports `script_path`, `script_content`, `orbit_pitch_deg`, `orbit_yaw_deg`, `rgb`, `depth`, `segmentation`, `payload_path`, `rendering_type`, `agent_role`, and `smoke_test_mode`.
- `BenchmarkToolRequest` is the static-preview payload; it carries `bundle_base64`, `script_path`, `script_content`, `backend`, `smoke_test_mode`, `skip_preview_rendering`, `particle_budget`, `reviewer_stage`, `episode_id`, and `stream_render_frames`.
- `PointCloudRenderRequest` needs `bundle_base64` plus point-cloud sampling controls.
- `SimulationVideoRequest` needs `bundle_base64`, `frame_paths`, `output_name`, `fps`, and an optional `session_id`.

## Output Handling

- Preview renders return `PreviewDesignResponse`.
- Static preview, point cloud, and simulation video return `BenchmarkToolResponse`.
- Treat `render_manifest_json`, `render_blobs_base64`, `object_store_keys`, and `image_bytes_base64` as artifacts to materialize, not text to summarize.
- Use the shared renderer client helpers to write returned files back into the workspace when you need on-disk inspection.

## Troubleshooting

- If the renderer rejects the request as busy, retry with backoff rather than flooding the service.
- If the render path fails, inspect the request payload, the route schema in `references/function_signatures.md`, and the renderer service logs.
- If the route schema changed, refresh the reference file from `worker_renderer/api/routes.py` and `shared/rendering/renderer_client.py`.

## References

- `references/function_signatures.md` for the current route map, helper surface, and request/response shapes.
