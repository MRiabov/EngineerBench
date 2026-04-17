from __future__ import annotations

import base64
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog
from PIL import Image

from shared.agents import get_video_render_resolution
from shared.observability.storage import S3Client, S3Config
from shared.rendering.renderer_client import (
    bundle_workspace_base64,
    render_simulation_video,
)

logger = structlog.get_logger(__name__)


def _stack_profile_s3_endpoint() -> str | None:
    profile = os.getenv("PROBLEMOLOGIST_STACK_PROFILE", "").strip().lower()
    if profile == "integration":
        return "http://127.0.0.1:19000"
    if profile == "eval":
        return "http://127.0.0.1:29000"
    return None


@dataclass(frozen=True)
class RenderedSimulationVideo:
    """Rendered video payload plus its optional object-store key."""

    video_bytes: bytes
    object_store_key: str | None = None


def _simulation_video_s3_client() -> S3Client | None:
    access_key = (
        os.getenv("S3_ACCESS_KEY") or os.getenv("AWS_ACCESS_KEY_ID") or "minioadmin"
    )
    secret_key = (
        os.getenv("S3_SECRET_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or "minioadmin"
    )
    if not access_key or not secret_key:
        return None

    bucket_name = os.getenv("ASSET_S3_BUCKET", "problemologist")
    endpoint_url = _stack_profile_s3_endpoint()
    if endpoint_url is None:
        endpoint_url = os.getenv("S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT")
    logger.info(
        "simulation_video_s3_client_config",
        stack_profile=os.getenv("PROBLEMOLOGIST_STACK_PROFILE"),
        endpoint_url=endpoint_url,
        s3_endpoint=os.getenv("S3_ENDPOINT"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    )
    return S3Client(
        S3Config(
            endpoint_url=endpoint_url,
            access_key_id=access_key,
            secret_access_key=secret_key,
            bucket_name=bucket_name,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
    )


def render_simulation_video_artifact(
    frames: Sequence[np.ndarray],
    *,
    output_name: str,
    fps: int,
    session_id: str,
    width: int | None = None,
    height: int | None = None,
) -> RenderedSimulationVideo:
    if not frames:
        raise ValueError("simulation video requires at least one frame")

    if width is None or height is None:
        default_width, default_height = get_video_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height

    with tempfile.TemporaryDirectory() as tmpdir:
        staging_root = Path(tmpdir)
        frames_dir = staging_root / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        frame_paths: list[str] = []

        for index, frame in enumerate(frames):
            frame_path = frames_dir / f"frame_{index:05d}.png"
            if frame.shape[:2] != (height, width):
                frame = np.array(Image.fromarray(frame).resize((width, height)))
            Image.fromarray(frame).save(frame_path)
            frame_paths.append(str(frame_path.relative_to(staging_root)))

        response = render_simulation_video(
            bundle_base64=bundle_workspace_base64(staging_root),
            frame_paths=frame_paths,
            output_name=output_name,
            fps=fps,
            session_id=session_id,
        )
        if not response.success:
            raise RuntimeError(response.message)
        if response.artifacts is None:
            raise RuntimeError("renderer returned no artifacts")

        render_blobs = response.artifacts.render_blobs_base64 or {}
        object_store_keys = response.artifacts.object_store_keys or {}
        output_key = next(
            (key for key in render_blobs if Path(key).name == output_name),
            None,
        )
        object_store_path = next(
            (
                path
                for path, value in object_store_keys.items()
                if Path(path).name == output_name or Path(value).name == output_name
            ),
            None,
        )
        object_store_key = (
            object_store_keys[object_store_path] if object_store_path else None
        )
        if object_store_key:
            client = _simulation_video_s3_client()
            if client is None:
                raise RuntimeError(
                    "renderer returned an object-store-backed video but S3 is not configured"
                )
            with tempfile.NamedTemporaryFile(suffix=Path(output_name).suffix) as tmp:
                client.download_file(object_store_key, tmp.name)
                video_bytes = Path(tmp.name).read_bytes()
        elif output_key is not None:
            video_bytes = base64.b64decode(render_blobs[output_key])
        else:
            raise RuntimeError("renderer returned no simulation video blob")

        logger.info(
            "simulation_video_rendered",
            session_id=session_id,
            output_name=output_name,
            frame_count=len(frames),
            object_store_key=object_store_key,
        )
        return RenderedSimulationVideo(
            video_bytes=video_bytes,
            object_store_key=object_store_key,
        )


def synthesize_placeholder_frames(
    seed_source: str,
    *,
    frame_count: int = 3,
    width: int = 64,
    height: int = 48,
) -> list[np.ndarray]:
    """Create deterministic placeholder frames for legacy simulation workflows."""
    seed = sum(ord(ch) for ch in seed_source) % 255
    frames: list[np.ndarray] = []
    for idx in range(frame_count):
        color = np.array(
            [
                (seed + idx * 40) % 255,
                (seed + idx * 70 + 85) % 255,
                (seed + idx * 110 + 170) % 255,
            ],
            dtype=np.uint8,
        )
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = color
        frames.append(frame)
    return frames


def render_simulation_video_bytes(
    frames: Sequence[np.ndarray],
    *,
    output_name: str,
    fps: int,
    session_id: str,
    width: int | None = None,
    height: int | None = None,
) -> bytes:
    """Stage frames locally, delegate MP4 encoding to worker-renderer, and return bytes."""
    rendered = render_simulation_video_artifact(
        frames,
        output_name=output_name,
        fps=fps,
        session_id=session_id,
        width=width,
        height=height,
    )
    return rendered.video_bytes
