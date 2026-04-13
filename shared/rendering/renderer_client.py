from __future__ import annotations

import base64
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from shared.models.simulation import StressFieldData
from shared.workers.bundling import bundle_directory_base64
from shared.workers.schema import (
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    PreviewDesignRequest,
    PreviewDesignResponse,
    PreviewRenderingType,
    SimulationVideoRequest,
    StressHeatmapRequest,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from shared.observability.storage import S3Client


def renderer_base_url() -> str:
    return os.getenv("WORKER_RENDERER_URL", "http://worker-renderer:8003").rstrip("/")


def bundle_workspace_base64(root: Path) -> str:
    return bundle_directory_base64(root)


def _session_headers(session_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if session_id:
        headers["x-session-id"] = session_id
    return headers


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _storage_client_from_env() -> S3Client | None:
    try:
        from shared.observability.storage import S3Client, S3Config
    except ModuleNotFoundError:
        return None

    access_key = os.getenv("S3_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID"))
    secret_key = os.getenv("S3_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY"))
    if not access_key or not secret_key:
        return None

    return S3Client(
        S3Config(
            endpoint_url=os.getenv("S3_ENDPOINT"),
            access_key_id=access_key,
            secret_access_key=secret_key,
            bucket_name=os.getenv("ASSET_S3_BUCKET", "problemologist"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    )


def _post_json_with_busy_retry(
    *,
    url: str,
    payload: dict[str, Any],
    session_id: str | None,
    timeout: float,
    extra_headers: dict[str, str] | None = None,
    attempts: int | None = None,
    initial_delay_s: float = 0.5,
    max_delay_s: float = 5.0,
) -> dict[str, Any]:
    """POST JSON to the renderer, retrying transient worker-busy responses."""

    delay_s = initial_delay_s
    busy_retry_deadline_s = time.monotonic() + timeout
    attempt = 0

    while True:
        attempt += 1
        headers = _session_headers(session_id)
        if extra_headers:
            headers.update(extra_headers)
        with httpx.Client(timeout=timeout, headers=headers) as client:
            response = client.post(url, json=payload)
            try:
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError:
                if response.status_code != 503:
                    raise
                if attempts is not None and attempt >= attempts:
                    raise
                if time.monotonic() >= busy_retry_deadline_s:
                    raise

                logger.warning(
                    "renderer_busy_retry",
                    url=url,
                    attempt=attempt,
                    attempts=attempts,
                    delay_s=delay_s,
                    session_id=session_id,
                )
                remaining_s = busy_retry_deadline_s - time.monotonic()
                if remaining_s <= 0:
                    raise
                time.sleep(min(delay_s, remaining_s))
                delay_s = min(delay_s * 1.5, max_delay_s)


def render_preview(
    *,
    bundle_base64: str | None,
    script_path: str,
    orbit_pitch: float | list[float],
    orbit_yaw: float | list[float],
    rgb: bool | None = None,
    depth: bool | None = None,
    segmentation: bool | None = None,
    payload_path: bool = False,
    rendering_type: PreviewRenderingType | None = None,
    session_id: str | None = None,
    agent_role: str | None = None,
    script_content: str | None = None,
    smoke_test_mode: bool | None = None,
) -> PreviewDesignResponse:
    payload = PreviewDesignRequest(
        bundle_base64=bundle_base64,
        script_path=script_path,
        agent_role=agent_role,
        orbit_pitch=orbit_pitch,
        orbit_yaw=orbit_yaw,
        rgb=rgb,
        depth=depth,
        segmentation=segmentation,
        payload_path=payload_path,
        drafting=False,
        rendering_type=rendering_type,
        script_content=script_content,
        smoke_test_mode=smoke_test_mode,
    ).model_dump(mode="json")
    url = f"{renderer_base_url()}/benchmark/render_cad"
    data = _post_json_with_busy_retry(
        url=url,
        payload=payload,
        session_id=session_id,
        extra_headers={"x-agent-role": agent_role} if agent_role else None,
        timeout=60.0,
    )
    return PreviewDesignResponse.model_validate(data)


def render_cad(
    *,
    bundle_base64: str | None,
    script_path: str,
    orbit_pitch: float | list[float],
    orbit_yaw: float | list[float],
    session_id: str | None = None,
    agent_role: str | None = None,
    script_content: str | None = None,
    smoke_test_mode: bool | None = None,
    rgb: bool | None = None,
    depth: bool | None = None,
    segmentation: bool | None = None,
    payload_path: bool = False,
    rendering_type: PreviewRenderingType | str | None = None,
) -> PreviewDesignResponse:
    return render_preview(
        bundle_base64=bundle_base64,
        script_path=script_path,
        orbit_pitch=orbit_pitch,
        orbit_yaw=orbit_yaw,
        session_id=session_id,
        agent_role=agent_role,
        script_content=script_content,
        smoke_test_mode=smoke_test_mode,
        rgb=rgb,
        depth=depth,
        segmentation=segmentation,
        payload_path=payload_path,
        rendering_type=rendering_type,
    )


def render_static_preview(
    *,
    bundle_base64: str | None,
    script_path: str,
    session_id: str,
    agent_role: str | None = None,
    smoke_test_mode: bool | None = None,
    particle_budget: int | None = None,
    script_content: str | None = None,
) -> BenchmarkToolResponse:
    payload = BenchmarkToolRequest(
        bundle_base64=bundle_base64,
        script_path=script_path,
        smoke_test_mode=smoke_test_mode,
        particle_budget=particle_budget,
        script_content=script_content,
    ).model_dump(mode="json")
    payload["session_id"] = session_id
    url = f"{renderer_base_url()}/benchmark/static-preview"
    data = _post_json_with_busy_retry(
        url=url,
        payload=payload,
        session_id=session_id,
        extra_headers={"x-agent-role": agent_role} if agent_role else None,
        timeout=120.0,
    )
    return BenchmarkToolResponse.model_validate(data)


def render_simulation_video(
    *,
    bundle_base64: str | None,
    frame_paths: list[str],
    output_name: str,
    fps: int,
    session_id: str,
) -> BenchmarkToolResponse:
    payload = SimulationVideoRequest(
        bundle_base64=bundle_base64,
        frame_paths=frame_paths,
        output_name=output_name,
        fps=fps,
        session_id=session_id,
    ).model_dump(mode="json")
    url = f"{renderer_base_url()}/benchmark/simulation-video"
    data = _post_json_with_busy_retry(
        url=url,
        payload=payload,
        session_id=session_id,
        timeout=120.0,
    )
    return BenchmarkToolResponse.model_validate(data)


def render_stress_heatmap(
    *,
    bundle_base64: str | None,
    stress_field: StressFieldData,
    output_name: str,
    session_id: str,
    mesh_path: str | None = None,
    width: int = 800,
    height: int = 600,
) -> BenchmarkToolResponse:
    payload = StressHeatmapRequest(
        bundle_base64=bundle_base64 or "",
        stress_field=stress_field,
        output_name=output_name,
        mesh_path=mesh_path,
        width=width,
        height=height,
        session_id=session_id,
    ).model_dump(mode="json")
    url = f"{renderer_base_url()}/benchmark/stress-heatmap"
    data = _post_json_with_busy_retry(
        url=url,
        payload=payload,
        session_id=session_id,
        timeout=120.0,
    )
    return BenchmarkToolResponse.model_validate(data)


def materialize_preview_response(
    response: PreviewDesignResponse,
    output_dir: Path,
) -> Path | None:
    """Persist a preview response payload into the local workspace."""
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = output_dir.parent.parent
    first_materialized: Path | None = None
    object_store_keys = response.object_store_keys or {}
    storage_client = None

    if object_store_keys:
        storage_client = _storage_client_from_env()
        missing_object_store_paths = [
            rel_path
            for rel_path in object_store_keys
            if rel_path not in response.render_blobs_base64
        ]
        if storage_client is None and missing_object_store_paths:
            raise RuntimeError(
                "preview response referenced object-store-backed renders but no "
                "S3 client is configured"
            )

    if response.render_blobs_base64:
        for rel_path, blob in response.render_blobs_base64.items():
            target = workspace_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(blob))
            if first_materialized is None and target.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
            }:
                first_materialized = target

    if object_store_keys and storage_client is not None:
        for rel_path, object_key in object_store_keys.items():
            target = workspace_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            storage_client.download_file(object_key, target)
            if first_materialized is None and target.suffix.lower() in {
                ".png",
                ".jpg",
                ".jpeg",
            }:
                first_materialized = target

    if response.image_bytes_base64:
        image_name = Path(response.image_path or "preview.png").name
        image_path = output_dir / image_name
        image_path.write_bytes(base64.b64decode(response.image_bytes_base64))
        if first_materialized is None:
            first_materialized = image_path

    if response.image_path and first_materialized is None:
        candidate = (
            Path(response.image_path)
            if Path(response.image_path).is_absolute()
            else workspace_root / response.image_path
        )
        if candidate.exists():
            first_materialized = candidate
        else:
            raise RuntimeError(
                f"preview image {response.image_path} was not materialized"
            )

    if response.render_manifest_json:
        manifest_path = output_dir / "render_manifest.json"
        _write_text_atomic(manifest_path, response.render_manifest_json)

    return first_materialized


def materialize_render_artifacts(
    artifacts: Any, workspace_root: Path, *, default_subdir: str = "renders"
) -> list[str]:
    """Persist renderer artifact blobs into the caller's workspace."""
    render_paths: list[str] = []
    render_blobs = getattr(artifacts, "render_blobs_base64", None) or {}
    object_store_keys = getattr(artifacts, "object_store_keys", None) or {}
    storage_client = None
    for rel_path, blob in render_blobs.items():
        target = workspace_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(blob))
        render_paths.append(str(Path(rel_path)))
    if object_store_keys:
        storage_client = _storage_client_from_env()
    for rel_path, object_key in object_store_keys.items():
        if rel_path in render_blobs:
            continue
        if storage_client is None:
            continue
        target = workspace_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        storage_client.download_file(object_key, target)
        render_paths.append(str(Path(rel_path)))
    if not render_paths:
        render_paths = [
            str(Path(path)) for path in getattr(artifacts, "render_paths", [])
        ]
    return render_paths
