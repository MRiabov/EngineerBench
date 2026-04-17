from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Iterator, cast

import numpy as np
import structlog
import trimesh
from pydantic import BaseModel, ConfigDict

from shared.workers.schema import (
    RenderBundleIndexEntry,
    RenderBundleObjectIdentity,
    RenderBundleObjectPoseRecord,
    RenderBundlePointPickRequest,
    RenderBundlePointPickResult,
    RenderBundleQueryRequest,
    RenderBundleQueryResult,
    RenderFrameMetadata,
    RenderManifest,
)
from worker_renderer.utils.build123d_rendering import (
    PreviewScene,
    _preview_camera_distance,
    camera_position_from_orbit,
)

logger = structlog.get_logger(__name__)


def _tuple3(values: Any) -> tuple[float, float, float]:
    return (float(values[0]), float(values[1]), float(values[2]))


class _BundleManifestResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_root: Path
    manifest_path: Path
    manifest: RenderManifest


def _workspace_root(workspace_root: Path | str | None = None) -> Path:
    return Path(workspace_root) if workspace_root is not None else Path.cwd()


def _normalize_bundle_path(bundle_path: str | Path) -> str:
    return str(Path(bundle_path)).replace("\\", "/").strip("/")


def _candidate_manifest_paths(bundle_root: Path) -> list[Path]:
    return [bundle_root / "render_manifest.json"]


def _load_manifest_from_index(
    *, workspace_root: Path, bundle_path: str
) -> _BundleManifestResolution | None:
    index_candidates = [
        workspace_root / "renders" / "render_index.jsonl",
    ]
    normalized_bundle_path = _normalize_bundle_path(bundle_path)

    for index_path in index_candidates:
        if not index_path.exists():
            continue
        try:
            lines = [
                line
                for line in index_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except Exception:
            continue
        for line in reversed(lines):
            try:
                entry = RenderBundleIndexEntry.model_validate_json(line)
            except Exception:
                continue
            if (
                _normalize_bundle_path(entry.bundle_path or "")
                != normalized_bundle_path
            ):
                continue
            manifest_path = workspace_root / Path(entry.manifest_path)
            if not manifest_path.exists():
                continue
            try:
                manifest = RenderManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            resolved_bundle_path = _normalize_bundle_path(
                manifest.bundle_path or normalized_bundle_path
            )
            resolved_bundle_root = workspace_root / resolved_bundle_path
            if not resolved_bundle_root.exists():
                resolved_bundle_root = manifest_path.parent
            return _BundleManifestResolution(
                bundle_root=resolved_bundle_root,
                manifest_path=manifest_path,
                manifest=manifest,
            )
    return None


def resolve_render_bundle(
    bundle_path: str | Path,
    *,
    workspace_root: Path | str | None = None,
    manifest_path: str | Path | None = None,
) -> _BundleManifestResolution:
    workspace = _workspace_root(workspace_root)
    normalized_bundle_path = _normalize_bundle_path(bundle_path)
    bundle_root = workspace / normalized_bundle_path

    candidate_paths: list[Path] = []
    if manifest_path is not None:
        raw_manifest_path = Path(manifest_path)
        candidate_paths.append(
            raw_manifest_path
            if raw_manifest_path.is_absolute()
            else workspace / raw_manifest_path
        )
    candidate_paths.extend(_candidate_manifest_paths(bundle_root))

    for candidate in candidate_paths:
        if not candidate.exists():
            continue
        try:
            manifest = RenderManifest.model_validate_json(
                candidate.read_text(encoding="utf-8")
            )
        except Exception:
            continue
        resolved_bundle_path = _normalize_bundle_path(
            manifest.bundle_path or normalized_bundle_path
        )
        if resolved_bundle_path != normalized_bundle_path:
            continue
        resolved_bundle_root = workspace / resolved_bundle_path
        if not resolved_bundle_root.exists():
            resolved_bundle_root = candidate.parent
        return _BundleManifestResolution(
            bundle_root=resolved_bundle_root,
            manifest_path=candidate,
            manifest=manifest,
        )

    indexed = _load_manifest_from_index(
        workspace_root=workspace, bundle_path=normalized_bundle_path
    )
    if indexed is not None:
        return indexed

    raise FileNotFoundError(
        f"Unable to resolve render bundle: {normalized_bundle_path}"
    )


def _load_preview_scene(bundle_root: Path) -> PreviewScene:
    scene_path = bundle_root / "preview_scene.json"
    if not scene_path.exists():
        raise FileNotFoundError(f"preview_scene.json missing for bundle: {bundle_root}")
    scene = PreviewScene.model_validate_json(scene_path.read_text(encoding="utf-8"))
    for entity in scene.entities:
        if not entity.mesh_paths:
            continue
        entity.mesh_paths = [
            str((bundle_root / Path(mesh_path)).resolve())
            if not Path(mesh_path).is_absolute()
            else str(Path(mesh_path).resolve())
            for mesh_path in entity.mesh_paths
        ]
    return scene


def _preview_scene_hash(bundle_root: Path) -> str | None:
    scene_path = bundle_root / "preview_scene.json"
    if not scene_path.exists():
        return None
    return hashlib.sha256(scene_path.read_bytes()).hexdigest()


def _normalize_vector(value: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(value))
    if norm <= 0.0:
        return value
    return value / norm


def _camera_ray(
    scene: PreviewScene,
    *,
    pixel_x_px: int,
    pixel_y_px: int,
    image_width_px: int,
    image_height_px: int,
    orbit_pitch_deg: float,
    orbit_yaw_deg: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    distance = _preview_camera_distance(
        scene, width=image_width_px, height=image_height_px
    )
    center = _tuple3(scene.center_mm)
    camera_position = camera_position_from_orbit(
        center,
        distance,
        orbit_pitch_deg,
        orbit_yaw_deg,
    )
    origin = np.asarray(camera_position, dtype=float)
    target = np.asarray(center, dtype=float)
    forward = _normalize_vector(target - origin)
    up = np.asarray((0.0, 0.0, 1.0), dtype=float)
    right = np.cross(forward, up)
    if np.linalg.norm(right) < 1e-9:
        up = np.asarray((0.0, 1.0, 0.0), dtype=float)
        right = np.cross(forward, up)
    right = _normalize_vector(right)
    true_up = _normalize_vector(np.cross(right, forward))

    aspect = max(float(image_width_px) / max(float(image_height_px), 1.0), 1e-6)
    vertical_fov_rad = math.radians(30.0)
    tan_vertical = math.tan(vertical_fov_rad / 2.0)
    tan_horizontal = tan_vertical * aspect

    ndc_x = ((float(pixel_x_px) + 0.5) / float(image_width_px)) * 2.0 - 1.0
    ndc_y = 1.0 - ((float(pixel_y_px) + 0.5) / float(image_height_px)) * 2.0
    direction = _normalize_vector(
        forward + ndc_x * tan_horizontal * right + ndc_y * tan_vertical * true_up
    )
    return _tuple3(origin.tolist()), _tuple3(direction.tolist())


def _load_mesh(mesh_path: Path) -> trimesh.Trimesh | None:
    if not mesh_path.exists():
        return None
    mesh = trimesh.load(mesh_path, force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    if not isinstance(mesh, trimesh.Trimesh):
        return None
    return mesh


def _box_mesh(size: tuple[float, float, float]) -> trimesh.Trimesh:
    extents = [max(float(component) * 2.0, 1e-6) for component in size]
    return trimesh.creation.box(extents=extents)


def _apply_transform(
    mesh: trimesh.Trimesh,
    *,
    pos: tuple[float, float, float],
    euler: tuple[float, float, float],
) -> trimesh.Trimesh:
    transformed = mesh.copy()
    matrix = trimesh.transformations.translation_matrix(pos)
    for angle, axis in zip(euler, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))):
        matrix = matrix @ trimesh.transformations.rotation_matrix(
            math.radians(float(angle)),
            axis,
        )
    transformed.apply_transform(matrix)
    return transformed


def _iter_entity_meshes(
    scene: PreviewScene, bundle_root: Path
) -> Iterator[tuple[Any, trimesh.Trimesh]]:
    for entity in scene.entities:
        if entity.box_size_mm is not None:
            yield (
                entity,
                _apply_transform(
                    _box_mesh(entity.box_size_mm),
                    pos=entity.pos_mm,
                    euler=entity.euler_deg,
                ),
            )
            continue

        if not entity.mesh_paths:
            continue
        for mesh_path in entity.mesh_paths:
            mesh = _load_mesh(
                Path(mesh_path)
                if Path(mesh_path).is_absolute()
                else (bundle_root / Path(mesh_path))
            )
            if mesh is None:
                continue
            yield (
                entity,
                _apply_transform(mesh, pos=entity.pos_mm, euler=entity.euler_deg),
            )


def _pick_hit(
    scene: PreviewScene,
    *,
    bundle_root: Path,
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
) -> tuple[bool, float | None, tuple[float, float, float] | None, Any | None]:
    ray_origin = np.asarray(origin, dtype=float)[None, :]
    ray_direction = np.asarray(direction, dtype=float)[None, :]
    best_distance: float | None = None
    best_point: tuple[float, float, float] | None = None
    best_entity: Any | None = None

    for entity, mesh in _iter_entity_meshes(scene, bundle_root):
        if mesh is None:
            continue
        mesh = cast(trimesh.Trimesh, mesh)
        ray = cast(Any, mesh.ray)
        try:
            locations, index_ray, _ = ray.intersects_location(
                ray_origin,
                ray_direction,
                multiple_hits=False,
            )
        except Exception:
            continue
        if len(locations) == 0 or len(index_ray) == 0:
            continue
        location = np.asarray(locations[0], dtype=float)
        distance = float(np.linalg.norm(location - ray_origin[0]))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_point = _tuple3(location.tolist())
            best_entity = entity

    return best_distance is not None, best_distance, best_point, best_entity


def _object_identity(entity: Any | None) -> RenderBundleObjectIdentity | None:
    if entity is None:
        return None
    return RenderBundleObjectIdentity(
        object_type=getattr(entity, "object_type", None),
        object_id=getattr(entity, "object_id", None),
        label=getattr(entity, "label", None),
        instance_id=getattr(entity, "instance_id", None),
        instance_name=getattr(entity, "instance_name", None),
        semantic_label=getattr(entity, "semantic_label", None),
        body_name=getattr(entity, "body_name", None),
        geom_name=getattr(entity, "geom_name", None),
    )


def list_render_bundles(
    workspace_root: Path | str | None = None,
) -> list[RenderBundleIndexEntry]:
    workspace = _workspace_root(workspace_root)
    index_path = workspace / "renders" / "render_index.jsonl"
    if index_path.exists():
        try:
            entries: list[RenderBundleIndexEntry] = []
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entries.append(RenderBundleIndexEntry.model_validate_json(line))
                except Exception:
                    continue
            return entries
        except Exception:
            logger.warning(
                "render_bundle_index_parse_failed",
                index_path=str(index_path),
            )

    return []


def query_render_bundle(
    request: RenderBundleQueryRequest | RenderBundlePointPickRequest,
    *,
    workspace_root: Path | str | None = None,
) -> RenderBundleQueryResult | RenderBundlePointPickResult:
    workspace = _workspace_root(workspace_root)
    resolution = resolve_render_bundle(
        request.bundle_path,
        workspace_root=workspace,
        manifest_path=getattr(request, "manifest_path", None),
    )
    requested_bundle_id = getattr(request, "bundle_id", None)
    if requested_bundle_id and resolution.manifest.bundle_id != requested_bundle_id:
        raise ValueError(
            "render bundle id mismatch: "
            f"requested={requested_bundle_id} resolved={resolution.manifest.bundle_id}"
        )

    frames: list[RenderFrameMetadata] = []
    frame_path = resolution.bundle_root / "frames.jsonl"
    if frame_path.exists():
        for line in frame_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                frames.append(RenderFrameMetadata.model_validate_json(line))
            except Exception:
                continue
    objects: list[RenderBundleObjectPoseRecord] = []
    objects_path = resolution.bundle_root / "objects.parquet"
    if objects_path.exists():
        try:
            import pyarrow.parquet as pq

            table = pq.read_table(objects_path)
            for record in table.to_pylist():
                objects.append(RenderBundleObjectPoseRecord.model_validate(record))
            objects.sort(
                key=lambda record: (
                    record.frame_index if record.frame_index is not None else -1,
                    record.object_id if record.object_id is not None else -1,
                )
            )
        except Exception:
            logger.warning(
                "render_bundle_objects_parse_failed",
                objects_path=str(objects_path),
            )

    if isinstance(request, RenderBundlePointPickRequest):
        scene = _load_preview_scene(resolution.bundle_root)
        if resolution.manifest.scene_hash is None:
            raise ValueError("render bundle scene hash missing")
        bundle_scene_hash = _preview_scene_hash(resolution.bundle_root)
        if bundle_scene_hash is None:
            raise ValueError("render bundle preview scene snapshot missing")
        if bundle_scene_hash != resolution.manifest.scene_hash:
            raise ValueError(
                "render bundle scene snapshot hash mismatch: "
                f"manifest={resolution.manifest.scene_hash} "
                f"snapshot={bundle_scene_hash}"
            )
        origin, direction = _camera_ray(
            scene,
            pixel_x_px=request.pixel_x_px,
            pixel_y_px=request.pixel_y_px,
            image_width_px=request.image_width_px,
            image_height_px=request.image_height_px,
            orbit_pitch_deg=request.orbit_pitch_deg,
            orbit_yaw_deg=request.orbit_yaw_deg,
        )
        hit, distance, world_point, entity = _pick_hit(
            scene,
            bundle_root=resolution.bundle_root,
            origin=origin,
            direction=direction,
        )
        return RenderBundlePointPickResult(
            bundle_id=resolution.manifest.bundle_id,
            bundle_path=resolution.manifest.bundle_path or request.bundle_path,
            revision=resolution.manifest.revision,
            scene_hash=resolution.manifest.scene_hash,
            manifest_path=str(resolution.manifest_path.relative_to(workspace)).replace(
                "\\", "/"
            ),
            view_index=request.view_index,
            pixel_x_px=request.pixel_x_px,
            pixel_y_px=request.pixel_y_px,
            image_width_px=request.image_width_px,
            image_height_px=request.image_height_px,
            orbit_pitch_deg=request.orbit_pitch_deg,
            orbit_yaw_deg=request.orbit_yaw_deg,
            ray_origin=origin,
            ray_direction=direction,
            hit=hit,
            distance=distance,
            world_point=world_point,
            object_identity=_object_identity(entity),
        )

    query = request
    if query.limit is not None:
        frames = frames[: query.limit]
        objects = objects[: query.limit]

    return RenderBundleQueryResult(
        bundle_id=resolution.manifest.bundle_id,
        bundle_path=resolution.manifest.bundle_path or request.bundle_path,
        revision=resolution.manifest.revision,
        scene_hash=resolution.manifest.scene_hash,
        manifest_path=str(resolution.manifest_path.relative_to(workspace)).replace(
            "\\", "/"
        ),
        preview_evidence_paths=list(resolution.manifest.preview_evidence_paths),
        frames=frames,
        objects=objects,
    )


def pick_preview_pixels(
    requests: list[RenderBundlePointPickRequest],
    *,
    workspace_root: Path | str | None = None,
) -> list[RenderBundlePointPickResult]:
    """Resolve a batch of point-picks, one request object per pick."""

    return [
        pick_preview_pixel(request, workspace_root=workspace_root)
        for request in requests
    ]


def pick_preview_pixel(
    request: RenderBundlePointPickRequest | None = None,
    *,
    bundle_path: str | Path | None = None,
    pixel_x_px: int | None = None,
    pixel_y_px: int | None = None,
    image_width_px: int | None = None,
    image_height_px: int | None = None,
    orbit_pitch_deg: float = 45.0,
    orbit_yaw_deg: float = 45.0,
    view_index: int = 0,
    manifest_path: str | Path | None = None,
    workspace_root: Path | str | None = None,
) -> RenderBundlePointPickResult:
    """Resolve one pixel against a bundle-local preview snapshot."""

    if request is None:
        if bundle_path is None:
            raise ValueError("bundle_path is required")
        if pixel_x_px is None or pixel_y_px is None:
            raise ValueError("pixel_x_px and pixel_y_px are required")
        if image_width_px is None or image_height_px is None:
            raise ValueError("image_width_px and image_height_px are required")
        request = RenderBundlePointPickRequest(
            bundle_path=str(bundle_path),
            pixel_x_px=pixel_x_px,
            pixel_y_px=pixel_y_px,
            image_width_px=image_width_px,
            image_height_px=image_height_px,
            orbit_pitch_deg=orbit_pitch_deg,
            orbit_yaw_deg=orbit_yaw_deg,
            view_index=view_index,
            manifest_path=str(manifest_path) if manifest_path is not None else None,
        )
    result = query_render_bundle(request, workspace_root=workspace_root)
    if not isinstance(result, RenderBundlePointPickResult):
        raise RuntimeError("point-pick query returned the wrong result type")
    return result
