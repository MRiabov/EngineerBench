# Worker Renderer Route Map and Signatures

This is the current developer-facing renderer surface. Refresh it from `worker_renderer/api/routes.py` and `shared/rendering/renderer_client.py` when routes or request shapes change.

## Route Map

| Method | Route | Use | Request model | Response model |
| --- | --- | --- | --- | --- |
| `GET` | `/health` | Boot probe | none | health payload |
| `GET` | `/ready` | Admission probe | none | ready/busy payload |
| `GET` | `/` | Service root | none | service metadata |
| `GET` | `/docs` | Swagger UI | none | HTML |
| `GET` | `/openapi.json` | Schema discovery | none | OpenAPI JSON |
| `POST` | `/benchmark/render_cad` | Scratch preview renders | `PreviewDesignRequest` | `PreviewDesignResponse` |
| `POST` | `/benchmark/preview` | Deprecated compatibility alias | `PreviewDesignRequest` | `PreviewDesignResponse` |
| `POST` | `/benchmark/static-preview` | Bundle-backed validation preview | `BenchmarkToolRequest` | `BenchmarkToolResponse` |
| `POST` | `/debug/render_point_cloud` | Point-cloud debug render | `PointCloudRenderRequest` | `BenchmarkToolResponse` |
| `POST` | `/benchmark/simulation-video` | Encode captured frames into MP4 | `SimulationVideoRequest` | `BenchmarkToolResponse` |

## Shared Client Surface

Prefer these helpers from `shared.rendering.renderer_client` when writing repo code:

- `renderer_base_url() -> str`
- `bundle_workspace_base64(root: Path) -> str`
- `render_preview(...) -> PreviewDesignResponse`
- `render_cad(...) -> PreviewDesignResponse` (compatibility alias for `render_preview(...)`)
- `render_static_preview(...) -> BenchmarkToolResponse`
- `render_point_cloud(...) -> BenchmarkToolResponse`
- `render_simulation_video(...) -> BenchmarkToolResponse`
- `materialize_preview_response(...) -> Path | None`
- `materialize_render_artifacts(...) -> list[str]`

## Request Notes

- `PreviewDesignRequest`
  - `bundle_base64`
  - `script_path`
  - `script_content`
  - `orbit_pitch_deg`
  - `orbit_yaw_deg`
  - `rgb`
  - `depth`
  - `segmentation`
  - `payload_path`
  - `rendering_type`
  - `agent_role`
  - `smoke_test_mode`
- `BenchmarkToolRequest`
  - `bundle_base64`
  - `script_path`
  - `script_content`
  - `backend`
  - `smoke_test_mode`
  - `skip_preview_rendering`
  - `particle_budget`
  - `reviewer_stage`
  - `episode_id`
  - `stream_render_frames`
- `PointCloudRenderRequest`
  - `bundle_base64`
  - `sample_limit`
  - `point_size_px`
  - `render_backend`
  - `output_name`
- `SimulationVideoRequest`
  - `bundle_base64`
  - `frame_paths`
  - `output_name`
  - `fps`
  - `session_id`

## Notes

- `X-Session-ID` is the main request-context header.
- `X-Agent-Role` is optional but useful when preview artifacts are role-routed.
- `POST /benchmark/preview` exists only as a compatibility alias; prefer `POST /benchmark/render_cad`.
- `worker-renderer` is single-flight and returns `503 WORKER_BUSY` while a render is active.
- The service is containerized and headless; do not depend on host `DISPLAY`, `XAUTHORITY`, or local VTK/OSMesa bootstrap state.
