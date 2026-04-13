"""Preview design utility for CAD visualization."""

import base64
import os
from pathlib import Path

import structlog
from build123d import Compound, Part
from deprecated import deprecated

from shared.agents import get_image_render_resolution
from shared.models.schemas import BenchmarkDefinition
from shared.rendering import (
    export_preview_scene_bundle,
    materialize_preview_response,
    render_preview,
    select_single_preview_render_subdir,
)
from shared.utils.agent import _script_agent_role
from shared.workers.schema import PreviewDesignResponse, PreviewRenderingType
from worker_renderer.utils.scene_builder import normalize_preview_label

logger = structlog.get_logger(__name__)


@deprecated("Use render_cad instead. preview remains as a compatibility alias only.")
def preview(
    component: Part | Compound,
    orbit_pitch: float | list[float] = 45.0,
    orbit_yaw: float | list[float] = 45.0,
    rgb: bool | None = None,
    depth: bool | None = None,
    segmentation: bool | None = None,
    payload_path: bool = False,
    rendering_type: PreviewRenderingType | str | None = None,
    output_dir: Path | None = None,
    objectives: BenchmarkDefinition | None = None,
    width: int | None = None,
    height: int | None = None,
) -> PreviewDesignResponse:
    """Render a preview of a CAD component and persist it to the preview bucket."""
    if width is None or height is None:
        default_width, default_height = get_image_render_resolution()
        width = default_width if width is None else width
        height = default_height if height is None else height
    del width, height

    workspace_root = Path.cwd()
    session_id = os.getenv("SESSION_ID") or None
    agent_role = _script_agent_role()
    preview_bundle_base64 = export_preview_scene_bundle(
        component,
        objectives=objectives,
        workspace_root=workspace_root,
    )
    preview_script_path = "preview_scene.json"

    response = render_preview(
        bundle_base64=preview_bundle_base64,
        script_path=preview_script_path,
        orbit_pitch=orbit_pitch,
        orbit_yaw=orbit_yaw,
        rgb=rgb,
        depth=depth,
        segmentation=segmentation,
        payload_path=payload_path,
        rendering_type=(
            PreviewRenderingType(str(rendering_type))
            if rendering_type is not None
            else None
        ),
        session_id=session_id,
        agent_role=agent_role,
    )
    if not response.success:
        raise RuntimeError(response.message or "build123d preview render failed")

    if output_dir is None:
        output_dir = (
            workspace_root
            / "renders"
            / select_single_preview_render_subdir(workspace_root, agent_role=agent_role)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    materialized_path = materialize_preview_response(response, output_dir)
    if materialized_path is None:
        image_bytes_base64 = response.image_bytes_base64
        if not image_bytes_base64:
            raise RuntimeError("renderer returned no preview image bytes")
        pitch_value = orbit_pitch[0] if isinstance(orbit_pitch, list) else orbit_pitch
        yaw_value = orbit_yaw[0] if isinstance(orbit_yaw, list) else orbit_yaw
        component_label = normalize_preview_label(getattr(component, "label", None))
        image_name = Path(
            response.image_path
            or (
                f"{component_label}_render_e{abs(int(round(pitch_value)))}_a{int(round(yaw_value))}.png"
                if component_label
                else f"unnamed_1_render_e{abs(int(round(pitch_value)))}_a{int(round(yaw_value))}.png"
            )
        ).name
        materialized_path = output_dir / image_name
        materialized_path.write_bytes(base64.b64decode(image_bytes_base64))
    try:
        response.image_path = str(materialized_path.relative_to(workspace_root))
    except ValueError:
        response.image_path = str(materialized_path)
    response.artifact_path = response.image_path
    response.manifest_path = str(
        materialized_path.parent.relative_to(workspace_root) / "render_manifest.json"
    )
    if isinstance(orbit_pitch, list):
        response.pitch = orbit_pitch[0] if len(orbit_pitch) == 1 else None
    else:
        response.pitch = orbit_pitch
    if isinstance(orbit_yaw, list):
        response.yaw = orbit_yaw[0] if len(orbit_yaw) == 1 else None
    else:
        response.yaw = orbit_yaw
    if response.status_text is None:
        response.status_text = response.message or "Preview generated successfully"

    preview_message = (
        "Preview generated successfully. "
        f"Saved renders to {Path(response.manifest_path).parent}. "
        f"Manifest: {response.manifest_path}."
    )
    response.message = preview_message
    print(preview_message)

    logger.info(
        "preview_saved",
        path=str(materialized_path),
        saved_render_dir=str(materialized_path.parent.relative_to(workspace_root)),
        orbit_pitch=orbit_pitch,
        orbit_yaw=orbit_yaw,
        rendering_type=response.rendering_type.value,
    )
    return response


def render_cad(
    component: Part | Compound,
    orbit_pitch: float | list[float] = 45.0,
    orbit_yaw: float | list[float] = 45.0,
    rgb: bool | None = None,
    depth: bool | None = None,
    segmentation: bool | None = None,
    payload_path: bool = False,
    rendering_type: PreviewRenderingType | str | None = None,
    output_dir: Path | None = None,
    objectives: BenchmarkDefinition | None = None,
    width: int | None = None,
    height: int | None = None,
) -> PreviewDesignResponse:
    return preview(
        component,
        orbit_pitch=orbit_pitch,
        orbit_yaw=orbit_yaw,
        rgb=rgb,
        depth=depth,
        segmentation=segmentation,
        payload_path=payload_path,
        rendering_type=rendering_type,
        output_dir=output_dir,
        objectives=objectives,
        width=width,
        height=height,
    )
