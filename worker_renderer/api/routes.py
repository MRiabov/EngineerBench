from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shutil
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException
from PIL import Image

from shared.agents import get_image_render_resolution
from shared.agents.config import load_agents_config
from shared.git_utils import repo_revision
from shared.models.schemas import BenchmarkDefinition
from shared.workers.bundling import extract_bundle_base64
from shared.workers.loader import load_component_from_script
from shared.workers.persistence import collect_and_cleanup_events
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    PointCloudRenderRequest,
    PreviewDesignRequest,
    PreviewDesignResponse,
    PreviewRenderingType,
    PreviewViewSpec,
    RenderArtifactMetadata,
    RenderFrameMetadata,
    RenderManifest,
    RenderSiblingPaths,
    SegmentationLegendEntry,
    SimulationArtifacts,
    SimulationVideoRequest,
)
from worker_renderer.utils.build123d_rendering import (
    _OVERLAY_AXES_COLOR,
    _OVERLAY_EDGE_COLOR,
    _RGB_AXES_COLOR,
    _RGB_EDGE_COLOR,
    PreviewScene,
    _build_payload_path_overlay_bundle,
    _build_renderer,
    _composite_non_black,
    _depth_buffer_to_display_rgb,
    _preview_camera_distance,
    _preview_segmentation_legend,
    _render_view,
    camera_position_from_orbit,
    collect_preview_scene,
    render_preview_scene_bundle,
)
from worker_renderer.utils.file_validation import validate_benchmark_definition_yaml
from worker_renderer.utils.payload_path_overlay import resolve_payload_path_points
from worker_renderer.utils.point_cloud_rendering import render_scene_point_cloud
from worker_renderer.utils.rendering import (
    append_render_bundle_index,
    build_render_bundle_index_entry,
    build_render_manifest,
    normalize_render_manifest,
    select_single_preview_render_subdir,
    select_static_preview_render_subdir,
)
from worker_renderer.utils.scene_builder import normalize_preview_label

logger = structlog.get_logger(__name__)
renderer_router = APIRouter()

_RENDER_ADMISSION_LOCK = asyncio.Lock()
_RENDER_BUSY = False
_RENDER_BUSY_CONTEXT: dict[str, str] = {}


def is_renderer_busy() -> bool:
    return _RENDER_BUSY


def renderer_busy_context() -> dict[str, str]:
    return dict(_RENDER_BUSY_CONTEXT)


def _busy_detail() -> dict[str, Any]:
    return {
        "code": "WORKER_BUSY",
        "message": "Renderer worker already has an active job",
        "active_job": renderer_busy_context(),
    }


def _preview_scene_label(scene: PreviewScene) -> str:
    label = normalize_preview_label(getattr(scene, "component_label", None))
    if label:
        return label
    for entity in scene.entities:
        label = normalize_preview_label(entity.label)
        if label:
            return label
    return "unnamed_1"


@contextlib.asynccontextmanager
async def render_operation_admission(operation: str, session_id: str):
    global _RENDER_BUSY, _RENDER_BUSY_CONTEXT

    async with _RENDER_ADMISSION_LOCK:
        if _RENDER_BUSY:
            raise HTTPException(status_code=503, detail=_busy_detail())
        _RENDER_BUSY = True
        _RENDER_BUSY_CONTEXT = {
            "operation": operation,
            "session_id": session_id,
        }

    try:
        yield
    finally:
        async with _RENDER_ADMISSION_LOCK:
            _RENDER_BUSY = False
            _RENDER_BUSY_CONTEXT = {}


@contextlib.contextmanager
def _event_file_context(root: Path):
    previous = os.environ.get("EVENTS_FILE")
    os.environ["EVENTS_FILE"] = str(root / "events.jsonl")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("EVENTS_FILE", None)
        else:
            os.environ["EVENTS_FILE"] = previous


def _renderer_storage_client():
    access_key = (
        os.getenv("S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or "minioadmin"
    )
    secret_key = (
        os.getenv("S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or "minioadmin"
    )
    if not access_key or not secret_key:
        return None

    try:
        from shared.observability.storage import (
            S3Client,
            S3Config,
        )
    except ModuleNotFoundError:
        return None

    endpoint_url = os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT")
    config = S3Config(
        endpoint_url=endpoint_url,
        access_key_id=access_key,
        secret_access_key=secret_key,
        bucket_name=os.getenv("ASSET_S3_BUCKET", "problemologist"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
    )
    return S3Client(config)


def _maybe_store_large_render_artifact(
    render_path: Path,
    *,
    rel_path: str,
    session_id: str | None = None,
    allow_image_upload: bool = False,
    client: Any | None = None,
) -> str | None:
    suffix = render_path.suffix.lower()
    if suffix != ".mp4" and not (
        allow_image_upload and suffix in {".png", ".jpg", ".jpeg"}
    ):
        return None

    client = client or _renderer_storage_client()
    if client is None:
        logger.info(
            "renderer_object_store_skipped",
            rel_path=rel_path,
            reason="storage_unavailable",
            session_id=session_id,
        )
        return None

    object_key = rel_path
    client.upload_file(str(render_path), object_key)
    logger.info(
        "renderer_object_store_uploaded",
        rel_path=rel_path,
        object_key=object_key,
        session_id=session_id,
    )
    return object_key


@contextlib.contextmanager
def _bundle_context(bundle_base64: str | None):
    if not bundle_base64:
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        extract_bundle_base64(bundle_base64, root)
        yield root


def _load_workspace_benchmark_definition(
    root: Path, *, session_id: str | None = None
) -> BenchmarkDefinition | None:
    benchmark_path = root / "benchmark_definition.yaml"
    if not benchmark_path.exists():
        return None

    raw = benchmark_path.read_text(encoding="utf-8")
    is_valid, objectives_or_errors = validate_benchmark_definition_yaml(
        raw, session_id=session_id
    )
    if not is_valid:
        raise ValueError("; ".join(objectives_or_errors))
    return objectives_or_errors


def _resolve_preview_payload_path_points(
    root: Path, benchmark_definition: BenchmarkDefinition | None
) -> list[tuple[float, float, float]] | None:
    return resolve_payload_path_points(
        root,
        benchmark_definition=benchmark_definition,
    )


def _load_preview_scene_bundle(root: Path) -> tuple[PreviewScene | None, str | None]:
    scene_path = root / "preview_scene.json"
    if not scene_path.exists():
        return None, None
    raw_scene = scene_path.read_text(encoding="utf-8")
    scene = PreviewScene.model_validate_json(raw_scene)
    for entity in scene.entities:
        if not entity.mesh_paths:
            continue
        entity.mesh_paths = [
            str((root / Path(mesh_path)).resolve())
            if not Path(mesh_path).is_absolute()
            else str(Path(mesh_path).resolve())
            for mesh_path in entity.mesh_paths
        ]
    return scene, raw_scene


def _persist_preview_scene_bundle(
    *,
    bundle_root: Path,
    scene: PreviewScene,
    source_mesh_root: Path | None,
    raw_scene_json: str | None = None,
) -> Path:
    """Persist the exact preview scene snapshot used by the renderer."""

    bundle_root.mkdir(parents=True, exist_ok=True)
    bundle_mesh_root = bundle_root / "meshes"
    if source_mesh_root is not None and source_mesh_root.exists():
        shutil.copytree(source_mesh_root, bundle_mesh_root, dirs_exist_ok=True)
    else:
        bundle_mesh_root.mkdir(parents=True, exist_ok=True)

    if raw_scene_json is not None:
        scene_path = bundle_root / "preview_scene.json"
        scene_path.write_text(raw_scene_json, encoding="utf-8")
        return scene_path

    normalized_scene = scene.model_copy(deep=True)
    normalized_source_root = source_mesh_root.resolve() if source_mesh_root else None
    for entity in normalized_scene.entities:
        if not entity.mesh_paths:
            continue
        normalized_paths: list[str] = []
        for mesh_path in entity.mesh_paths:
            mesh_path_obj = Path(mesh_path)
            if mesh_path_obj.is_absolute() and normalized_source_root is not None:
                rel_path = mesh_path_obj.resolve().relative_to(normalized_source_root)
            else:
                rel_path = mesh_path_obj
            normalized_paths.append(str(Path("meshes") / rel_path))
        entity.mesh_paths = normalized_paths

    scene_path = bundle_root / "preview_scene.json"
    scene_path.write_text(normalized_scene.model_dump_json(indent=2), encoding="utf-8")
    return scene_path


def _bundle_sidecar_candidates(
    bundle_root: Path, *, workspace_root: Path
) -> dict[str, Path]:
    candidates: dict[str, Path] = {}
    for rel_path in (
        "preview_scene.json",
        "render_manifest.json",
        "frames.jsonl",
        "objects.parquet",
        "sampled_points.parquet",
    ):
        sidecar_path = bundle_root / rel_path
        if sidecar_path.exists() and sidecar_path.is_file():
            candidates[str(sidecar_path.relative_to(workspace_root))] = sidecar_path

    index_path = workspace_root / "renders" / "render_index.jsonl"
    if index_path.exists() and index_path.is_file():
        candidates[str(index_path.relative_to(workspace_root))] = index_path

    return candidates


def _collect_render_artifacts(
    root: Path,
    render_paths: list[str],
    *,
    session_id: str | None = None,
    store_image_artifacts: bool = False,
) -> SimulationArtifacts:
    normalized_render_paths: list[str] = []
    render_blobs_base64: dict[str, str] = {}
    object_store_keys: dict[str, str] = {}
    upload_candidates: list[tuple[str, Path]] = []
    upload_client = _renderer_storage_client()

    for raw_path in render_paths:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            try:
                rel_path = candidate.resolve().relative_to(root.resolve())
            except Exception:
                rel_path = Path(candidate.name)
            render_path = candidate
        else:
            rel_path = candidate
            render_path = root / candidate
        if not render_path.exists() or not render_path.is_file():
            continue
        suffix = render_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".mp4"}:
            continue
        rel_key = str(rel_path)
        normalized_render_paths.append(rel_key)
        if suffix == ".mp4" or store_image_artifacts:
            upload_candidates.append((rel_key, render_path))
        else:
            render_blobs_base64[rel_key] = base64.b64encode(
                render_path.read_bytes()
            ).decode("ascii")

    if upload_candidates:
        if upload_client is None:
            for rel_key, render_path in upload_candidates:
                if render_path.suffix.lower() == ".mp4":
                    raise RuntimeError(
                        "renderer returned an object-store-backed video but S3 is not configured"
                    )
                render_blobs_base64[rel_key] = base64.b64encode(
                    render_path.read_bytes()
                ).decode("ascii")
        else:
            with ThreadPoolExecutor(
                max_workers=min(8, len(upload_candidates))
            ) as executor:
                futures = {
                    executor.submit(
                        _maybe_store_large_render_artifact,
                        render_path,
                        rel_path=rel_key,
                        session_id=session_id,
                        allow_image_upload=store_image_artifacts,
                        client=upload_client,
                    ): (rel_key, render_path)
                    for rel_key, render_path in upload_candidates
                }
                for future in as_completed(futures):
                    rel_key, render_path = futures[future]
                    object_key = future.result()
                    if object_key is not None:
                        object_store_keys[rel_key] = object_key
                    else:
                        render_blobs_base64[rel_key] = base64.b64encode(
                            render_path.read_bytes()
                        ).decode("ascii")

    bundle_roots = {
        (root / Path(render_path).parent).resolve()
        for render_path in normalized_render_paths
        if render_path
    }
    sidecar_candidates: dict[str, Path] = {}
    for bundle_root in sorted(bundle_roots):
        with contextlib.suppress(Exception):
            sidecar_candidates.update(
                _bundle_sidecar_candidates(bundle_root, workspace_root=root)
            )

    if sidecar_candidates:
        upload_sidecars = {
            rel_key: sidecar_path
            for rel_key, sidecar_path in sidecar_candidates.items()
        }

        if upload_sidecars:
            if upload_client is None:
                for rel_key, sidecar_path in upload_sidecars.items():
                    if rel_key.endswith("sampled_points.parquet"):
                        raise RuntimeError(
                            "renderer returned sampled_points.parquet but S3 is not configured"
                        )
                    render_blobs_base64[rel_key] = base64.b64encode(
                        sidecar_path.read_bytes()
                    ).decode("ascii")
            else:
                with ThreadPoolExecutor(
                    max_workers=min(8, len(upload_sidecars))
                ) as executor:
                    futures = {
                        executor.submit(
                            upload_client.upload_file,
                            str(sidecar_path),
                            rel_key,
                        ): (
                            rel_key,
                            sidecar_path,
                        )
                        for rel_key, sidecar_path in upload_sidecars.items()
                    }
                    for future in as_completed(futures):
                        rel_key, sidecar_path = futures[future]
                        try:
                            object_store_keys[rel_key] = future.result()
                        except Exception as exc:
                            if rel_key.endswith("sampled_points.parquet"):
                                raise RuntimeError(
                                    "renderer failed to upload sampled_points.parquet to object store"
                                ) from exc
                            logger.warning(
                                "renderer_sidecar_object_store_upload_failed",
                                rel_path=rel_key,
                                session_id=session_id,
                                path=str(sidecar_path),
                            )
                            render_blobs_base64[rel_key] = base64.b64encode(
                                sidecar_path.read_bytes()
                            ).decode("ascii")

    existing_manifest = None

    if normalized_render_paths:
        resolved_revision = (
            os.environ.get("REPO_REVISION")
            or repo_revision(Path.cwd())
            or repo_revision(root)
            or repo_revision(Path(__file__).resolve().parents[2])
        )
        bundle_root = root / Path(normalized_render_paths[0]).parent
        bundle_manifest_path = bundle_root / "render_manifest.json"
        if bundle_manifest_path.exists():
            with contextlib.suppress(Exception):
                existing_manifest = RenderManifest.model_validate_json(
                    bundle_manifest_path.read_text(encoding="utf-8")
                )
        synthesized_manifest = normalize_render_manifest(
            render_paths=normalized_render_paths,
            workspace_root=root,
            existing_manifest=existing_manifest,
            episode_id=session_id,
            worker_session_id=session_id,
            revision=resolved_revision,
        )
        bundle_manifest_rel = str(
            (bundle_root / "render_manifest.json").relative_to(root)
        ).replace("\\", "/")
        render_blobs_base64[bundle_manifest_rel] = base64.b64encode(
            synthesized_manifest.model_dump_json(indent=2).encode("utf-8")
        ).decode("ascii")

    artifacts = SimulationArtifacts(render_paths=normalized_render_paths)
    artifacts.render_blobs_base64 = render_blobs_base64
    artifacts.object_store_keys = object_store_keys
    return artifacts


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _single_preview_group_key(
    label: str,
    pitch: float,
    yaw: float,
    *,
    view_index: int | None = None,
    view_count: int = 1,
) -> str:
    base = f"{label}_render_e{abs(round(pitch))}_a{round(yaw)}"
    if view_count > 1:
        if view_index is None:
            raise ValueError("view_index is required for multi-view preview naming")
        return f"{base}_v{view_index}"
    return base


def _resolve_single_preview_group_key(
    output_dir: Path,
    label: str,
    pitch: float,
    yaw: float,
    *,
    view_index: int | None = None,
    view_count: int = 1,
) -> str:
    base_key = _single_preview_group_key(
        label,
        pitch,
        yaw,
        view_index=view_index,
        view_count=view_count,
    )
    candidate_paths = (
        output_dir / f"{base_key}.png",
        output_dir / f"{base_key}_depth.png",
        output_dir / f"{base_key}_segmentation.png",
    )
    if not any(path.exists() for path in candidate_paths):
        return base_key

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    suffix = uuid.uuid4().hex[:8]
    return f"{base_key}_{timestamp}_{suffix}"


def _normalize_preview_views(
    orbit_pitch_deg: float | list[float], orbit_yaw_deg: float | list[float]
) -> list[PreviewViewSpec]:
    pitch_values = (
        orbit_pitch_deg if isinstance(orbit_pitch_deg, list) else [orbit_pitch_deg]
    )
    yaw_values = orbit_yaw_deg if isinstance(orbit_yaw_deg, list) else [orbit_yaw_deg]
    if len(pitch_values) == 1 and len(yaw_values) > 1:
        pitch_values = pitch_values * len(yaw_values)
    elif len(yaw_values) == 1 and len(pitch_values) > 1:
        yaw_values = yaw_values * len(pitch_values)
    elif len(pitch_values) != len(yaw_values):
        raise ValueError(
            "orbit_pitch_deg and orbit_yaw_deg must broadcast or have matching lengths"
        )
    if len(pitch_values) > 64:
        raise ValueError("preview requests are capped at 64 views")
    return [
        PreviewViewSpec(
            view_index=index,
            orbit_pitch_deg=pitch,
            orbit_yaw_deg=yaw,
        )
        for index, (pitch, yaw) in enumerate(zip(pitch_values, yaw_values, strict=True))
    ]


def _render_single_preview(
    scene: PreviewScene,
    *,
    output_dir: Path,
    pitch: float,
    yaw: float,
    view_index: int,
    view_count: int,
    rendering_type: PreviewRenderingType,
    group_key: str | None = None,
    width: int | None = None,
    height: int | None = None,
    include_rgb_axes: bool,
    include_rgb_edges: bool,
    include_depth_axes: bool,
    include_depth_edges: bool,
    include_segmentation_axes: bool,
    include_segmentation_edges: bool,
    payload_path_points: list[tuple[float, float, float]] | None = None,
    include_payload_path_overlay: bool = False,
) -> tuple[Path, dict[str, RenderArtifactMetadata]]:
    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    center = scene.center_mm
    distance = _preview_camera_distance(scene, width=width, height=height)
    camera_position = camera_position_from_orbit(center, distance, pitch, yaw)
    workspace_root = output_dir.parent.parent

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, RenderArtifactMetadata] = {}
    group_key = group_key or _resolve_single_preview_group_key(
        output_dir,
        _preview_scene_label(scene),
        pitch,
        yaw,
        view_index=view_index,
        view_count=view_count,
    )

    if rendering_type == PreviewRenderingType.RGB:
        bundle = _build_renderer(
            scene,
            width=width,
            height=height,
            segmentation=False,
            include_axes=include_rgb_axes,
            include_edges=include_rgb_edges,
            include_fill=True,
            axes_color=_RGB_AXES_COLOR,
            edge_color=_RGB_EDGE_COLOR,
            background=(0.98, 0.98, 0.99),
        )
        try:
            rgb_image, _ = _render_view(
                bundle,
                camera_position=camera_position,
                lookat=center,
                up=(0.0, 0.0, 1.0),
                capture_depth=False,
            )
            if include_payload_path_overlay and payload_path_points:
                overlay_bundle = _build_payload_path_overlay_bundle(
                    payload_path_points,
                    width=width,
                    height=height,
                )
                if overlay_bundle is not None:
                    overlay_image, _ = _render_view(
                        overlay_bundle,
                        camera_position=camera_position,
                        lookat=center,
                        up=(0.0, 0.0, 1.0),
                        capture_depth=False,
                    )
                    rgb_image = _composite_non_black(rgb_image, overlay_image)
        finally:
            del bundle

        image_path = output_dir / f"{group_key}.png"
        Image.fromarray(rgb_image).convert("RGB").save(image_path, "PNG")
        rel_path = str(image_path.relative_to(workspace_root))
        artifacts[rel_path] = RenderArtifactMetadata(
            modality="rgb",
            group_key=group_key,
            view_index=view_index,
            orbit_pitch_deg=pitch,
            orbit_yaw_deg=yaw,
            siblings=RenderSiblingPaths(
                rgb=str(image_path.relative_to(workspace_root)),
                depth=str(
                    (output_dir / f"{group_key}_depth.png").relative_to(workspace_root)
                ),
                segmentation=str(
                    (output_dir / f"{group_key}_segmentation.png").relative_to(
                        workspace_root
                    )
                ),
            ),
        )
        return image_path, artifacts

    if rendering_type == PreviewRenderingType.DEPTH:
        depth_base_bundle = _build_renderer(
            scene,
            width=width,
            height=height,
            segmentation=False,
            include_axes=False,
            include_edges=False,
            include_fill=True,
            axes_color=_OVERLAY_AXES_COLOR,
            edge_color=_OVERLAY_EDGE_COLOR,
            background=(0.98, 0.98, 0.99),
        )
        depth_overlay_bundle: Any | None = None
        if include_depth_axes or include_depth_edges:
            depth_overlay_bundle = _build_renderer(
                scene,
                width=width,
                height=height,
                segmentation=False,
                include_axes=include_depth_axes,
                include_edges=include_depth_edges,
                include_fill=False,
                axes_color=_OVERLAY_AXES_COLOR,
                edge_color=_OVERLAY_EDGE_COLOR,
                background=(0.0, 0.0, 0.0),
            )
        try:
            _, depth_buffer = _render_view(
                depth_base_bundle,
                camera_position=camera_position,
                lookat=center,
                up=(0.0, 0.0, 1.0),
                capture_depth=True,
            )
            if depth_buffer is None:
                raise RuntimeError("depth rendering was disabled for render")
            depth_image, depth_range = _depth_buffer_to_display_rgb(depth_buffer)
            if depth_overlay_bundle is not None:
                depth_overlay, _ = _render_view(
                    depth_overlay_bundle,
                    camera_position=camera_position,
                    lookat=center,
                    up=(0.0, 0.0, 1.0),
                    capture_depth=False,
                )
                depth_image = _composite_non_black(depth_image, depth_overlay)
        finally:
            del depth_base_bundle
            if depth_overlay_bundle is not None:
                del depth_overlay_bundle

        image_path = output_dir / f"{group_key}_depth.png"
        Image.fromarray(depth_image, mode="RGB").save(image_path, "PNG")
        rel_path = str(image_path.relative_to(workspace_root))
        artifacts[rel_path] = RenderArtifactMetadata(
            modality="depth",
            group_key=group_key,
            view_index=view_index,
            orbit_pitch_deg=pitch,
            orbit_yaw_deg=yaw,
            siblings=RenderSiblingPaths(
                rgb=str((output_dir / f"{group_key}.png").relative_to(workspace_root)),
                depth=str(image_path.relative_to(workspace_root)),
                segmentation=str(
                    (output_dir / f"{group_key}_segmentation.png").relative_to(
                        workspace_root
                    )
                ),
            ),
            depth_interpretation=(
                "Camera-space depth in meters. False-color pixels are scaled "
                "from the build123d/VTK preview renderer's linear depth "
                "buffer; see depth_min_m and depth_max_m for the metric range."
            ),
            depth_min_m=depth_range[0],
            depth_max_m=depth_range[1],
        )
        return image_path, artifacts

    if rendering_type == PreviewRenderingType.SEGMENTATION:
        seg_base_bundle = _build_renderer(
            scene,
            width=width,
            height=height,
            segmentation=True,
            include_axes=False,
            include_edges=False,
            include_fill=True,
            axes_color=_OVERLAY_AXES_COLOR,
            edge_color=_OVERLAY_EDGE_COLOR,
            background=(0.0, 0.0, 0.0),
        )
        seg_overlay_bundle: Any | None = None
        if include_segmentation_axes or include_segmentation_edges:
            seg_overlay_bundle = _build_renderer(
                scene,
                width=width,
                height=height,
                segmentation=False,
                include_axes=include_segmentation_axes,
                include_edges=include_segmentation_edges,
                include_fill=False,
                axes_color=_OVERLAY_AXES_COLOR,
                edge_color=_OVERLAY_EDGE_COLOR,
                background=(0.0, 0.0, 0.0),
            )
        try:
            seg_image, _ = _render_view(
                seg_base_bundle,
                camera_position=camera_position,
                lookat=center,
                up=(0.0, 0.0, 1.0),
                capture_depth=False,
            )
            if seg_overlay_bundle is not None:
                seg_overlay, _ = _render_view(
                    seg_overlay_bundle,
                    camera_position=camera_position,
                    lookat=center,
                    up=(0.0, 0.0, 1.0),
                    capture_depth=False,
                )
                seg_image = _composite_non_black(seg_image, seg_overlay)
        finally:
            del seg_base_bundle
            if seg_overlay_bundle is not None:
                del seg_overlay_bundle

        image_path = output_dir / f"{group_key}_segmentation.png"
        Image.fromarray(seg_image, mode="RGB").save(image_path, "PNG")
        rel_path = str(image_path.relative_to(workspace_root))
        artifacts[rel_path] = RenderArtifactMetadata(
            modality="segmentation",
            group_key=group_key,
            view_index=view_index,
            orbit_pitch_deg=pitch,
            orbit_yaw_deg=yaw,
            siblings=RenderSiblingPaths(
                rgb=str((output_dir / f"{group_key}.png").relative_to(workspace_root)),
                depth=str(
                    (output_dir / f"{group_key}_depth.png").relative_to(workspace_root)
                ),
                segmentation=str(image_path.relative_to(workspace_root)),
            ),
            segmentation_legend=_preview_segmentation_legend(scene),
        )
        return image_path, artifacts

    raise ValueError(f"unsupported preview rendering type: {rendering_type}")


def _build_preview_manifest(
    *,
    root: Path,
    bundle_root: Path,
    saved_paths: list[str],
    legend_by_path: dict[str, list[SegmentationLegendEntry]],
    depth_ranges_by_path: dict[str, tuple[float, float]] | None,
    view_metadata_by_path: dict[str, PreviewViewSpec] | None,
    session_id: str | None,
    publish_bundle_index: bool = True,
) -> Path:
    artifacts: dict[str, RenderArtifactMetadata] = {}
    preview_evidence_paths: list[str] = []

    for saved_path in saved_paths:
        rel_path = str(Path(saved_path))
        filename = Path(rel_path).name
        render_dir = Path(rel_path).parent
        stem = Path(rel_path).stem
        view_spec = (
            view_metadata_by_path.get(rel_path) if view_metadata_by_path else None
        )
        view_index = view_spec.view_index if view_spec is not None else None
        orbit_pitch_deg = view_spec.orbit_pitch_deg if view_spec is not None else None
        orbit_yaw_deg = view_spec.orbit_yaw_deg if view_spec is not None else None
        rgb_candidate_jpg = (
            render_dir
            / f"{stem.removesuffix('_depth').removesuffix('_segmentation')}.jpg"
        )
        rgb_candidate_png = (
            render_dir
            / f"{stem.removesuffix('_depth').removesuffix('_segmentation')}.png"
        )
        rgb_sibling = (
            rgb_candidate_png.name
            if rgb_candidate_png.exists()
            else rgb_candidate_jpg.name
        )
        if filename.endswith("_depth.png"):
            group_key = stem.removesuffix("_depth")
            depth_range = None
            if depth_ranges_by_path is not None:
                depth_range = depth_ranges_by_path.get(rel_path)
            artifacts[rel_path] = RenderArtifactMetadata(
                modality="depth",
                group_key=group_key,
                view_index=view_index,
                orbit_pitch_deg=orbit_pitch_deg,
                orbit_yaw_deg=orbit_yaw_deg,
                siblings=RenderSiblingPaths(
                    rgb=str(render_dir / rgb_sibling),
                    depth=str(render_dir / f"{group_key}_depth.png"),
                    segmentation=str(render_dir / f"{group_key}_segmentation.png"),
                ),
                depth_interpretation=(
                    "Camera-space depth in meters. False-color pixels are scaled "
                    "from the build123d/VTK preview renderer's linear depth "
                    "buffer; see depth_min_m and depth_max_m for the metric "
                    "range."
                ),
                depth_min_m=depth_range[0] if depth_range is not None else None,
                depth_max_m=depth_range[1] if depth_range is not None else None,
            )
        elif filename.endswith("_segmentation.png"):
            group_key = stem.removesuffix("_segmentation")
            artifacts[rel_path] = RenderArtifactMetadata(
                modality="segmentation",
                group_key=group_key,
                view_index=view_index,
                orbit_pitch_deg=orbit_pitch_deg,
                orbit_yaw_deg=orbit_yaw_deg,
                siblings=RenderSiblingPaths(
                    rgb=str(render_dir / rgb_sibling),
                    depth=str(render_dir / f"{group_key}_depth.png"),
                    segmentation=str(render_dir / f"{group_key}_segmentation.png"),
                ),
                segmentation_legend=list(legend_by_path.get(rel_path, [])),
            )
        else:
            group_key = stem
            artifacts[rel_path] = RenderArtifactMetadata(
                modality="rgb",
                group_key=group_key,
                view_index=view_index,
                orbit_pitch_deg=orbit_pitch_deg,
                orbit_yaw_deg=orbit_yaw_deg,
                siblings=RenderSiblingPaths(
                    rgb=str(render_dir / rgb_sibling),
                    depth=str(render_dir / f"{group_key}_depth.png"),
                    segmentation=str(render_dir / f"{group_key}_segmentation.png"),
                ),
            )
        preview_evidence_paths.append(rel_path)

    manifest = build_render_manifest(
        artifacts,
        workspace_root=root,
        episode_id=session_id,
        worker_session_id=session_id,
        bundle_path=str(bundle_root.relative_to(root)).replace("\\", "/"),
        preview_evidence_paths=preview_evidence_paths,
    )
    manifest_path = bundle_root / "render_manifest.json"
    _write_text_atomic(manifest_path, manifest.model_dump_json(indent=2))
    if publish_bundle_index:
        index_entry = build_render_bundle_index_entry(
            manifest,
            manifest_path=str(manifest_path.relative_to(root)).replace("\\", "/"),
            primary_media_paths=list(preview_evidence_paths),
        )
        append_render_bundle_index(root, index_entry)
    return manifest_path


def _encode_simulation_video(
    bundle_root: Path,
    *,
    frame_paths: list[str],
    output_name: str,
    fps: int,
) -> Path:
    if not frame_paths:
        raise ValueError("simulation video requires at least one captured frame")

    import cv2

    output_path = bundle_root / output_name
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workspace_root = bundle_root.parents[2]

    first_frame_path = workspace_root / frame_paths[0]
    first_frame = cv2.imread(str(first_frame_path))
    if first_frame is None:
        raise ValueError(f"unable to read simulation frame: {frame_paths[0]}")

    height, width = first_frame.shape[:2]
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    try:
        for rel_path in frame_paths:
            frame_path = workspace_root / rel_path
            frame = cv2.imread(str(frame_path))
            if frame is None:
                raise ValueError(f"unable to read simulation frame: {rel_path}")
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
    finally:
        writer.release()

    logger.info(
        "renderer_simulation_video_complete",
        output_path=str(output_path),
        frame_count=len(frame_paths),
    )
    return output_path


@renderer_router.post(
    "/benchmark/render_cad",
    response_model=PreviewDesignResponse,
    response_model_exclude_none=True,
)
@renderer_router.post(
    "/benchmark/preview",
    response_model=PreviewDesignResponse,
    response_model_exclude_none=True,
    deprecated=True,
)
async def api_preview(
    request: PreviewDesignRequest,
    x_session_id: str = Header(default="renderer"),
    x_agent_role: str | None = Header(default=None),
):
    """Render one or more inspection previews in a dedicated renderer process."""
    try:
        async with render_operation_admission("preview", x_session_id):
            with _bundle_context(request.bundle_base64) as root:
                with _event_file_context(root):
                    objectives = _load_workspace_benchmark_definition(
                        root, session_id=x_session_id
                    )

                    renders_dir = (
                        root
                        / "renders"
                        / select_single_preview_render_subdir(
                            root, agent_role=x_agent_role
                        )
                    )
                    render_policy = load_agents_config().render
                    render_width = render_policy.image_resolution.width
                    render_height = render_policy.image_resolution.height
                    if not any((request.rgb, request.depth, request.segmentation)):
                        raise ValueError(
                            "preview request must enable at least one modality"
                        )
                    if request.rgb and not render_policy.rgb.enabled:
                        raise ValueError("rgb preview rendering is disabled")
                    if request.depth and not render_policy.depth.enabled:
                        raise ValueError("depth preview rendering is disabled")
                    if request.segmentation and not render_policy.segmentation.enabled:
                        raise ValueError("segmentation preview rendering is disabled")
                    payload_path_points = None
                    if (
                        request.payload_path
                        and render_policy.handoff_rgb_payload_path_overlay.enabled
                    ):
                        payload_path_points = _resolve_preview_payload_path_points(
                            root, objectives
                        )

                    view_specs = _normalize_preview_views(
                        request.orbit_pitch_deg, request.orbit_yaw_deg
                    )
                    if not view_specs:
                        raise ValueError(
                            "preview request must include at least one view"
                        )

                    scene, raw_scene_json = _load_preview_scene_bundle(root)
                    source_mesh_root: Path | None = root / "meshes" if scene else None
                    if scene is not None:
                        preview_scene = scene
                        mesh_tmpdir_ctx = contextlib.nullcontext(None)
                        component = None
                    else:
                        component = load_component_from_script(
                            script_path=root / request.script_path,
                            session_root=root,
                            script_content=request.script_content,
                        )
                        mesh_tmpdir_ctx = tempfile.TemporaryDirectory()

                    with mesh_tmpdir_ctx as mesh_tmpdir:
                        if scene is None:
                            source_mesh_root = Path(mesh_tmpdir)
                            preview_scene = await asyncio.to_thread(
                                collect_preview_scene,
                                component,
                                objectives=objectives,
                                workspace_root=root,
                                smoke_test_mode=bool(request.smoke_test_mode),
                                mesh_root=source_mesh_root,
                            )

                        modalities: list[PreviewRenderingType] = []
                        if request.rgb:
                            modalities.append(PreviewRenderingType.RGB)
                        if request.depth:
                            modalities.append(PreviewRenderingType.DEPTH)
                        if request.segmentation:
                            modalities.append(PreviewRenderingType.SEGMENTATION)

                        artifacts: dict[str, RenderArtifactMetadata] = {}
                        saved_paths: list[str] = []
                        legend_by_path: dict[str, list[SegmentationLegendEntry]] = {}
                        depth_ranges_by_path: dict[str, tuple[float, float]] = {}
                        view_metadata_by_path: dict[str, PreviewViewSpec] = {}
                        first_image_path: Path | None = None

                        for view_spec in view_specs:
                            group_key = _resolve_single_preview_group_key(
                                renders_dir,
                                _preview_scene_label(preview_scene),
                                view_spec.orbit_pitch_deg,
                                view_spec.orbit_yaw_deg,
                                view_index=view_spec.view_index,
                                view_count=len(view_specs),
                            )
                            for modality in modalities:
                                image_path, view_artifacts = await asyncio.to_thread(
                                    _render_single_preview,
                                    preview_scene,
                                    output_dir=renders_dir,
                                    pitch=view_spec.orbit_pitch_deg,
                                    yaw=view_spec.orbit_yaw_deg,
                                    view_index=view_spec.view_index,
                                    view_count=len(view_specs),
                                    rendering_type=modality,
                                    group_key=group_key,
                                    include_rgb_axes=render_policy.rgb.axes,
                                    include_rgb_edges=render_policy.rgb.edges,
                                    include_depth_axes=render_policy.depth.axes,
                                    include_depth_edges=render_policy.depth.edges,
                                    include_segmentation_axes=render_policy.segmentation.axes,
                                    include_segmentation_edges=render_policy.segmentation.edges,
                                    payload_path_points=payload_path_points,
                                    include_payload_path_overlay=(
                                        request.payload_path
                                        and render_policy.handoff_rgb_payload_path_overlay.enabled
                                    ),
                                    width=render_width,
                                    height=render_height,
                                )
                                artifacts.update(view_artifacts)
                                rel_path = str(image_path.relative_to(root))
                                if rel_path not in saved_paths:
                                    saved_paths.append(rel_path)
                                view_metadata_by_path[rel_path] = view_spec
                                metadata = view_artifacts[rel_path]
                                if first_image_path is None:
                                    first_image_path = image_path
                                if (
                                    metadata.modality == "segmentation"
                                    and metadata.segmentation_legend
                                ):
                                    legend_by_path[rel_path] = (
                                        metadata.segmentation_legend
                                    )
                                if (
                                    metadata.modality == "depth"
                                    and metadata.depth_min_m is not None
                                    and metadata.depth_max_m is not None
                                ):
                                    depth_ranges_by_path[rel_path] = (
                                        metadata.depth_min_m,
                                        metadata.depth_max_m,
                                    )

                        if first_image_path is None:
                            raise RuntimeError("preview renderer returned no output")

                        _persist_preview_scene_bundle(
                            bundle_root=renders_dir,
                            scene=preview_scene,
                            source_mesh_root=source_mesh_root,
                            raw_scene_json=raw_scene_json,
                        )

                preview_manifest = _build_preview_manifest(
                    root=root,
                    bundle_root=renders_dir,
                    saved_paths=saved_paths,
                    legend_by_path=legend_by_path,
                    depth_ranges_by_path=depth_ranges_by_path or None,
                    view_metadata_by_path=view_metadata_by_path,
                    session_id=x_session_id,
                    publish_bundle_index=False,
                )
                manifest_json = preview_manifest.read_text(encoding="utf-8")

                render_artifacts = _collect_render_artifacts(
                    root,
                    saved_paths,
                    session_id=x_session_id,
                    store_image_artifacts=True,
                )
                events = collect_and_cleanup_events(root, session_id=x_session_id)
                resolved_rendering_type = request.rendering_type
                if resolved_rendering_type is None:
                    resolved_rendering_type = (
                        PreviewRenderingType.RGB
                        if request.rgb
                        else PreviewRenderingType.DEPTH
                        if request.depth
                        else PreviewRenderingType.SEGMENTATION
                    )
                saved_render_dir = str(
                    first_image_path.parent.relative_to(root)
                ).replace("\\", "/")
                manifest_path = str(
                    preview_manifest.parent.relative_to(root) / "render_manifest.json"
                ).replace("\\", "/")
                preview_message = (
                    "Preview generated successfully. "
                    f"Saved renders to {saved_render_dir}. "
                    f"Manifest: {manifest_path}."
                )
                return PreviewDesignResponse(
                    success=True,
                    status_text="Preview generated successfully",
                    message=preview_message,
                    job_id=None,
                    queued=False,
                    view_count=len(view_specs),
                    view_specs=view_specs,
                    artifact_path=str(first_image_path.relative_to(root)),
                    manifest_path=manifest_path,
                    rendering_type=resolved_rendering_type,
                    orbit_pitch_deg=request.orbit_pitch_deg
                    if isinstance(request.orbit_pitch_deg, float)
                    else None,
                    orbit_yaw_deg=request.orbit_yaw_deg
                    if isinstance(request.orbit_yaw_deg, float)
                    else None,
                    image_path=str(first_image_path.relative_to(root)),
                    image_bytes_base64=(
                        None
                        if str(first_image_path.relative_to(root))
                        in render_artifacts.object_store_keys
                        else base64.b64encode(first_image_path.read_bytes()).decode(
                            "ascii"
                        )
                    ),
                    render_blobs_base64=render_artifacts.render_blobs_base64,
                    object_store_keys=render_artifacts.object_store_keys,
                    render_manifest_json=manifest_json,
                    events=events,
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "renderer_preview_failed", error=str(exc), session_id=x_session_id
        )
        return PreviewDesignResponse(
            success=False,
            status_text="Preview generation failed",
            message=str(exc),
            rendering_type=(
                request.rendering_type
                or (
                    PreviewRenderingType.RGB
                    if request.rgb
                    else PreviewRenderingType.DEPTH
                    if request.depth
                    else PreviewRenderingType.SEGMENTATION
                )
            ),
            orbit_pitch_deg=request.orbit_pitch_deg
            if isinstance(request.orbit_pitch_deg, float)
            else None,
            orbit_yaw_deg=request.orbit_yaw_deg
            if isinstance(request.orbit_yaw_deg, float)
            else None,
        )


@renderer_router.post("/benchmark/static-preview", response_model=BenchmarkToolResponse)
async def api_static_preview(
    request: BenchmarkToolRequest,
    x_session_id: str = Header(default="renderer"),
    x_agent_role: str | None = Header(default=None),
):
    """Render the multi-view validation render bundle in a dedicated process."""
    try:
        async with render_operation_admission("static-preview", x_session_id):
            render_policy = load_agents_config().render
            render_width = render_policy.image_resolution.width
            render_height = render_policy.image_resolution.height
            if not any(
                (
                    render_policy.rgb.enabled,
                    render_policy.depth.enabled,
                    render_policy.segmentation.enabled,
                )
            ):
                raise ValueError(
                    "validation preview requires at least one enabled render "
                    "modality (rgb, depth, or segmentation)"
                )
            with _bundle_context(request.bundle_base64) as root:
                with _event_file_context(root):
                    objectives = _load_workspace_benchmark_definition(
                        root, session_id=x_session_id
                    )
                    payload_path_points = None
                    if render_policy.handoff_rgb_payload_path_overlay.enabled:
                        payload_path_points = _resolve_preview_payload_path_points(
                            root, objectives
                        )

                    renders_dir = (
                        root
                        / "renders"
                        / select_static_preview_render_subdir(
                            root, agent_role=x_agent_role
                        )
                    )
                    renders_dir.mkdir(parents=True, exist_ok=True)
                    scene, raw_scene_json = _load_preview_scene_bundle(root)
                    if scene is not None:
                        source_mesh_root = root / "meshes"
                        render_result = await asyncio.to_thread(
                            render_preview_scene_bundle,
                            scene,
                            output_dir=renders_dir,
                            workspace_root=root,
                            smoke_test_mode=bool(request.smoke_test_mode),
                            include_rgb=render_policy.rgb.enabled,
                            include_depth=render_policy.depth.enabled,
                            include_segmentation=render_policy.segmentation.enabled,
                            rgb_axes=render_policy.rgb.axes,
                            rgb_edges=render_policy.rgb.edges,
                            depth_axes=render_policy.depth.axes,
                            depth_edges=render_policy.depth.edges,
                            segmentation_axes=render_policy.segmentation.axes,
                            segmentation_edges=render_policy.segmentation.edges,
                            payload_path_points=payload_path_points,
                            include_payload_path_overlay=(
                                render_policy.handoff_rgb_payload_path_overlay.enabled
                            ),
                            width=render_width,
                            height=render_height,
                        )
                        _persist_preview_scene_bundle(
                            bundle_root=renders_dir,
                            scene=scene,
                            source_mesh_root=source_mesh_root,
                            raw_scene_json=raw_scene_json,
                        )
                        _build_preview_manifest(
                            root=root,
                            bundle_root=renders_dir,
                            saved_paths=render_result.saved_paths,
                            legend_by_path=render_result.legend_by_path,
                            depth_ranges_by_path=render_result.depth_ranges_by_path,
                            view_metadata_by_path=None,
                            session_id=x_session_id,
                            publish_bundle_index=False,
                        )
                    else:
                        component = load_component_from_script(
                            script_path=root / request.script_path,
                            session_root=root,
                            script_content=request.script_content,
                        )
                        mesh_tmpdir = tempfile.TemporaryDirectory()
                        with mesh_tmpdir as mesh_tmpdir_path:
                            source_mesh_root = Path(mesh_tmpdir_path)
                            preview_scene = await asyncio.to_thread(
                                collect_preview_scene,
                                component,
                                objectives=objectives,
                                workspace_root=root,
                                smoke_test_mode=bool(request.smoke_test_mode),
                                mesh_root=source_mesh_root,
                            )
                            render_result = await asyncio.to_thread(
                                render_preview_scene_bundle,
                                preview_scene,
                                output_dir=renders_dir,
                                workspace_root=root,
                                smoke_test_mode=bool(request.smoke_test_mode),
                                width=render_width,
                                height=render_height,
                                include_rgb=render_policy.rgb.enabled,
                                include_depth=render_policy.depth.enabled,
                                include_segmentation=render_policy.segmentation.enabled,
                                rgb_axes=render_policy.rgb.axes,
                                rgb_edges=render_policy.rgb.edges,
                                depth_axes=render_policy.depth.axes,
                                depth_edges=render_policy.depth.edges,
                                segmentation_axes=render_policy.segmentation.axes,
                                segmentation_edges=render_policy.segmentation.edges,
                                payload_path_points=payload_path_points,
                                include_payload_path_overlay=(
                                    render_policy.handoff_rgb_payload_path_overlay.enabled
                                ),
                            )
                            _persist_preview_scene_bundle(
                                bundle_root=renders_dir,
                                scene=preview_scene,
                                source_mesh_root=source_mesh_root,
                            )
                        _build_preview_manifest(
                            root=root,
                            bundle_root=renders_dir,
                            saved_paths=render_result.saved_paths,
                            legend_by_path=render_result.legend_by_path,
                            depth_ranges_by_path=render_result.depth_ranges_by_path,
                            view_metadata_by_path=None,
                            session_id=x_session_id,
                            publish_bundle_index=False,
                        )

                events = collect_and_cleanup_events(root, session_id=x_session_id)
                return BenchmarkToolResponse(
                    success=True,
                    message="Static preview generated successfully",
                    artifacts=_collect_render_artifacts(
                        root, render_result.saved_paths, session_id=x_session_id
                    ),
                    events=events,
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "renderer_static_preview_failed", error=str(exc), session_id=x_session_id
        )
        return BenchmarkToolResponse(success=False, message=str(exc))


@renderer_router.post(
    "/debug/render_point_cloud",
    response_model=BenchmarkToolResponse,
    response_model_exclude_none=True,
)
async def api_render_point_cloud(
    request: PointCloudRenderRequest,
    x_session_id: str = Header(default="renderer"),
    x_agent_role: str | None = Header(default=None),
):
    """Render a static point cloud from the current preview scene bundle."""

    try:
        async with render_operation_admission("point-cloud", x_session_id):
            render_policy = load_agents_config().render
            render_width = render_policy.image_resolution.width
            render_height = render_policy.image_resolution.height
            with _bundle_context(request.bundle_base64) as root:
                with _event_file_context(root):
                    scene, _ = _load_preview_scene_bundle(root)
                    if scene is None:
                        raise FileNotFoundError(
                            "unable to locate preview_scene.json in the workspace"
                        )
                    bundle_root = (
                        root / "renders" / "debug_point_cloud" / uuid.uuid4().hex
                    )
                    bundle_root.mkdir(parents=True, exist_ok=True)
                    source_mesh_root = root / "meshes"
                    if (
                        any(entity.mesh_paths for entity in scene.entities)
                        and not source_mesh_root.exists()
                    ):
                        raise FileNotFoundError(
                            "preview scene bundle is missing the meshes directory"
                        )
                    _persist_preview_scene_bundle(
                        bundle_root=bundle_root,
                        scene=scene,
                        source_mesh_root=(
                            source_mesh_root if source_mesh_root.exists() else None
                        ),
                    )
                    scene_path = bundle_root / "preview_scene.json"

                    render_result = await asyncio.to_thread(
                        render_scene_point_cloud,
                        scene_path,
                        output_dir=bundle_root,
                        output_name=request.output_name,
                        sample_limit=request.sample_limit,
                        point_size_px=request.point_size_px,
                        render_backend=request.render_backend,
                        width=render_width,
                        height=render_height,
                    )

                    output_rel_path = str(
                        render_result.image_path.relative_to(root)
                    ).replace("\\", "/")
                    manifest = normalize_render_manifest(
                        render_paths=[output_rel_path],
                        workspace_root=root,
                        episode_id=x_session_id,
                        worker_session_id=x_session_id,
                        bundle_path=str(bundle_root.relative_to(root)).replace(
                            "\\", "/"
                        ),
                    )
                    manifest_path = bundle_root / "render_manifest.json"
                    _write_text_atomic(
                        manifest_path,
                        manifest.model_dump_json(indent=2),
                    )
                    append_render_bundle_index(
                        root,
                        build_render_bundle_index_entry(
                            manifest,
                            manifest_path=str(manifest_path.relative_to(root)).replace(
                                "\\", "/"
                            ),
                            primary_media_paths=[output_rel_path],
                        ),
                    )

                events = collect_and_cleanup_events(root, session_id=x_session_id)
                artifacts = _collect_render_artifacts(
                    root,
                    [output_rel_path],
                    session_id=x_session_id,
                    store_image_artifacts=False,
                )
                return BenchmarkToolResponse(
                    success=True,
                    message=(
                        "Point cloud rendered successfully "
                        f"from {render_result.source_surface_count} surface meshes "
                        f"using {render_result.sampled_point_count} sampled "
                        "surface points."
                    ),
                    artifacts=artifacts,
                    events=events,
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "renderer_point_cloud_failed",
            error=str(exc),
            session_id=x_session_id,
            agent_role=x_agent_role,
        )
        return BenchmarkToolResponse(success=False, message=str(exc))


@renderer_router.post(
    "/benchmark/simulation-video", response_model=BenchmarkToolResponse
)
async def api_simulation_video(
    request: SimulationVideoRequest,
    x_session_id: str = Header(default="renderer"),
):
    """Encode captured simulation frames into an MP4 in the renderer worker."""
    try:
        async with render_operation_admission("simulation-video", x_session_id):
            with _bundle_context(request.bundle_base64) as root:
                bundle_id = uuid.uuid4().hex
                bundle_root = root / "renders" / "simulation_video" / bundle_id
                with _event_file_context(root):
                    output_path = await asyncio.to_thread(
                        _encode_simulation_video,
                        bundle_root,
                        frame_paths=list(request.frame_paths),
                        output_name=request.output_name,
                        fps=request.fps,
                    )

                output_rel_path = str(output_path.relative_to(root))
                bundle_root = output_path.parent
                frames_sidecar = bundle_root / "frames.jsonl"
                frame_rows = [
                    RenderFrameMetadata(
                        frame_index=index,
                        source_path=str(Path(output_rel_path)),
                        timestamp_s=(index / float(request.fps)),
                    ).model_dump(mode="json")
                    for index, _ in enumerate(request.frame_paths)
                ]
                frames_sidecar.write_text(
                    "\n".join(json.dumps(row, sort_keys=False) for row in frame_rows)
                    + ("\n" if frame_rows else ""),
                    encoding="utf-8",
                )
                manifest = build_render_manifest(
                    {
                        output_rel_path: RenderArtifactMetadata(
                            modality="unknown",
                            group_key=Path(output_rel_path).stem,
                        )
                    },
                    workspace_root=root,
                    episode_id=request.session_id or x_session_id,
                    worker_session_id=x_session_id,
                    bundle_path=str(bundle_root.relative_to(root)).replace("\\", "/"),
                )
                manifest_path = bundle_root / "render_manifest.json"
                _write_text_atomic(manifest_path, manifest.model_dump_json(indent=2))
                append_render_bundle_index(
                    root,
                    build_render_bundle_index_entry(
                        manifest,
                        manifest_path=str(manifest_path.relative_to(root)).replace(
                            "\\", "/"
                        ),
                        primary_media_paths=[output_rel_path],
                    ),
                )

                events = collect_and_cleanup_events(root, session_id=x_session_id)
                return BenchmarkToolResponse(
                    success=True,
                    message="Simulation video generated successfully",
                    artifacts=_collect_render_artifacts(
                        root, [output_rel_path], session_id=x_session_id
                    ),
                    events=events,
                )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "renderer_simulation_video_failed", error=str(exc), session_id=x_session_id
        )
        return BenchmarkToolResponse(success=False, message=str(exc))
