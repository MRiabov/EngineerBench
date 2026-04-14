# Render Evidence Function Signatures

This is a generated snapshot of the current render helper surface.
Refresh it from the live helper module when signatures change; do not hand-edit arities from memory.

## Public Preview Surface

```python
from utils.preview import (
    list_render_bundles,
    objectives_geometry,
    pick_preview_pixel,
    pick_preview_pixels,
    render_cad,
    query_render_bundle,
)
```

- `render_cad(component: Part | Compound, orbit_pitch: float | list[float] = 45, orbit_yaw: float | list[float] = 45, rgb: bool | None = None, depth: bool | None = None, segmentation: bool | None = None, payload_path: bool = False, rendering_type: PreviewRenderingType | str | None = None) -> _PreviewResponseProxy`
- `objectives_geometry() -> Any`

## Render-Bundle Helpers

- `list_render_bundles(workspace_root: Path | str | None = None) -> list[RenderBundleIndexEntry]`
- `query_render_bundle(request: RenderBundleQueryRequest | RenderBundlePointPickRequest, *, workspace_root: Path | str | None = None) -> RenderBundleQueryResult | RenderBundlePointPickResult`
- `pick_preview_pixel(request: RenderBundlePointPickRequest | None = None, *, bundle_path: str | Path | None = None, pixel_x: int | None = None, pixel_y: int | None = None, image_width: int | None = None, image_height: int | None = None, orbit_pitch: float = 45.0, orbit_yaw: float = 45.0, view_index: int = 0, manifest_path: str | Path | None = None, workspace_root: Path | str | None = None) -> RenderBundlePointPickResult`
- `pick_preview_pixels(requests: list[RenderBundlePointPickRequest], *, workspace_root: Path | str | None = None) -> list[RenderBundlePointPickResult]`

## Request Shapes

### `PreviewRenderingType`

- `rgb`
- `depth`
- `segmentation`

### `RenderBundlePointPickRequest`

- `bundle_path: str`
- `pixel_x: int`
- `pixel_y: int`
- `image_width: int`
- `image_height: int`
- `orbit_pitch: float = 45.0`
- `orbit_yaw: float = 45.0`
- `view_index: int = 0`
- `bundle_id: str | None = None`
- `manifest_path: str | None = None`
- `rendering_type: PreviewRenderingType | None = None`

### `RenderBundleQueryRequest`

- `bundle_path: str`
- `manifest_path: str | None = None`
- `bundle_id: str | None = None`
- `limit: int | None = None`

## Related References

- [bundle-history.md](bundle-history.md) for bundle selection and history rules.
- [point-pick.md](point-pick.md) for the click-to-world workflow and result fields.
- `from utils.visualize import render_cad as visualize_render_cad` remains a compatibility alias; prefer `utils.preview` for new code.
