import os
import time
import uuid
from pathlib import Path

import structlog
from build123d import Compound

from shared.agents.config import load_agents_config
from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.models.schemas import BenchmarkDefinition
from shared.observability.events import emit_event
from shared.rendering import (
    materialize_render_artifacts,
    render_static_preview,
)
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.workers.schema import (
    RenderArtifactMetadata,
    RenderManifest,
    RenderSiblingPaths,
)

logger = structlog.get_logger(__name__)


def _derived_episode_id(session_id: str | None) -> str | None:
    if not session_id:
        return None
    try:
        return str(uuid.UUID(session_id))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))


def _workspace_environment_version(workspace_root: Path | None) -> str | None:
    if workspace_root is None:
        return None

    for rel_path in (
        "benchmark_assembly_definition.yaml",
        "assembly_definition.yaml",
    ):
        definition_path = workspace_root / rel_path
        if not definition_path.exists():
            continue
        try:
            import yaml

            from shared.models.schemas import AssemblyDefinition

            definition = AssemblyDefinition.model_validate(
                yaml.safe_load(definition_path.read_text(encoding="utf-8")) or {}
            )
            version = str(definition.version).strip()
            return version or None
        except Exception:
            continue
    return None


def build_render_manifest(
    artifacts: dict[str, RenderArtifactMetadata],
    *,
    workspace_root: Path | None = None,
    episode_id: str | None = None,
    worker_session_id: str | None = None,
    revision: str | None = None,
    environment_version: str | None = None,
    preview_evidence_paths: list[str] | None = None,
) -> RenderManifest:
    from worker_renderer.utils.rendering import (
        build_render_manifest as _build_render_manifest,
    )

    return _build_render_manifest(
        artifacts,
        workspace_root=workspace_root,
        episode_id=episode_id,
        worker_session_id=worker_session_id,
        revision=revision,
        environment_version=environment_version,
        preview_evidence_paths=preview_evidence_paths,
    )


def _render_group_key(render_path: str) -> tuple[str, str]:
    filename = Path(render_path).name
    stem = Path(render_path).stem
    if filename.endswith("_depth.png"):
        return stem.removesuffix("_depth"), "depth"
    if filename.endswith("_segmentation.png"):
        return stem.removesuffix("_segmentation"), "segmentation"
    if filename.endswith(".mp4"):
        return stem, "unknown"
    return stem, "rgb"


def _infer_render_artifact_metadata(
    render_path: str,
    *,
    existing: RenderArtifactMetadata | None = None,
) -> RenderArtifactMetadata:
    group_key, modality = _render_group_key(render_path)
    rel_path = Path(render_path)
    render_dir = rel_path.parent
    metadata = RenderArtifactMetadata(
        modality=modality,
        group_key=group_key,
        siblings=RenderSiblingPaths(
            rgb=str(render_dir / f"{group_key}.png"),
            depth=str(render_dir / f"{group_key}_depth.png"),
            segmentation=str(render_dir / f"{group_key}_segmentation.png"),
        ),
    )

    if modality == "depth":
        metadata.depth_interpretation = (
            existing.depth_interpretation
            if existing and existing.depth_interpretation
            else "Camera-space depth in meters. False-color pixels are scaled "
            "from the build123d/VTK preview renderer's linear depth buffer; "
            "see depth_min_m and depth_max_m for the metric range."
        )
    elif modality == "segmentation" and existing and existing.segmentation_legend:
        metadata.segmentation_legend = list(existing.segmentation_legend)
    elif modality == "segmentation" and existing and not existing.segmentation_legend:
        metadata.segmentation_legend = []

    if existing is not None:
        if existing.depth_min_m is not None:
            metadata.depth_min_m = existing.depth_min_m
        if existing.depth_max_m is not None:
            metadata.depth_max_m = existing.depth_max_m
        if existing.depth_interpretation and modality != "depth":
            metadata.depth_interpretation = existing.depth_interpretation
        if existing.segmentation_legend and modality != "segmentation":
            metadata.segmentation_legend = list(existing.segmentation_legend)

    return metadata


def normalize_render_manifest(
    *,
    render_paths: list[str],
    workspace_root: Path | None = None,
    existing_manifest: RenderManifest | None = None,
    episode_id: str | None = None,
    worker_session_id: str | None = None,
    revision: str | None = None,
    environment_version: str | None = None,
    preview_evidence_paths: list[str] | None = None,
    bundle_path: str | None = None,
    created_at: str | None = None,
    bundle_id: str | None = None,
    scene_hash: str | None = None,
) -> RenderManifest:
    from worker_renderer.utils.rendering import (
        normalize_render_manifest as _normalize_render_manifest,
    )

    return _normalize_render_manifest(
        render_paths=render_paths,
        workspace_root=workspace_root,
        existing_manifest=existing_manifest,
        episode_id=episode_id,
        worker_session_id=worker_session_id,
        revision=revision,
        environment_version=environment_version,
        preview_evidence_paths=preview_evidence_paths,
        bundle_path=bundle_path,
        created_at=created_at,
        bundle_id=bundle_id,
        scene_hash=scene_hash,
    )


def _workspace_root_from_render_dir(render_dir: Path) -> Path:
    parent = render_dir.parent
    if parent.name == "renders":
        return parent.parent
    return parent


def _is_benchmark_role(agent_role: str | None) -> bool:
    return bool(agent_role and agent_role.startswith("benchmark_"))


def _workspace_has_benchmark_preview_context(workspace_root: Path) -> bool:
    return any(
        (workspace_root / rel_path).exists()
        for rel_path in (
            "benchmark_plan.md",
            "benchmark_assembly_definition.yaml",
        )
    )


def _workspace_has_engineer_preview_context(workspace_root: Path) -> bool:
    return any(
        (workspace_root / rel_path).exists()
        for rel_path in (
            "engineering_plan.md",
            "assembly_definition.yaml",
        )
    )


def select_single_preview_render_subdir(
    workspace_root: Path, *, agent_role: str | None = None
) -> str:
    """Choose the single-view render bundle directory for the active workspace."""
    return "current-episode"


def select_static_preview_render_subdir(
    workspace_root: Path, *, agent_role: str | None = None
) -> str:
    """Choose the 24-view static render bundle directory for the workspace."""
    active_role = current_role_agent_name(workspace_root)
    if agent_role is not None and agent_role != active_role.value:
        raise ValueError(
            "select_static_preview_render_subdir received a role that does not "
            f"match .manifests/current_role.json: {agent_role} != {active_role.value}"
        )
    if active_role in {
        AgentName.BENCHMARK_PLANNER,
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
    }:
        return "benchmark_renders"
    if active_role in {
        AgentName.ENGINEER_PLANNER,
        AgentName.ENGINEER_PLAN_REVIEWER,
        AgentName.ENGINEER_CODER,
    }:
        return "engineer_plan_renders"
    return "final_solution_submission_renders"


def _build_preview_artifacts(
    saved_paths: list[str],
    legend_by_path: dict[str, list],
    *,
    workspace_root: Path,
) -> tuple[dict[str, RenderArtifactMetadata], list[str]]:
    render_paths = _workspace_relative_render_paths(saved_paths, workspace_root)
    artifacts: dict[str, RenderArtifactMetadata] = {}

    for saved_path, render_path in zip(saved_paths, render_paths, strict=True):
        rel_path = Path(render_path)
        render_dir = rel_path.parent
        filename = rel_path.name
        stem = rel_path.stem
        if filename.endswith("_depth.png"):
            group_key = stem.removesuffix("_depth")
            artifacts[render_path] = RenderArtifactMetadata(
                modality="depth",
                group_key=group_key,
                siblings=RenderSiblingPaths(
                    rgb=str(render_dir / f"{group_key}.png"),
                    depth=str(render_dir / f"{group_key}_depth.png"),
                    segmentation=str(render_dir / f"{group_key}_segmentation.png"),
                ),
                depth_interpretation=(
                    "Camera-space depth in meters. False-color pixels are scaled "
                    "from the build123d/VTK preview renderer's linear depth "
                    "buffer; see depth_min_m and depth_max_m for the metric "
                    "range."
                ),
            )
            continue

        if filename.endswith("_segmentation.png"):
            group_key = stem.removesuffix("_segmentation")
            artifacts[render_path] = RenderArtifactMetadata(
                modality="segmentation",
                group_key=group_key,
                siblings=RenderSiblingPaths(
                    rgb=str(render_dir / f"{group_key}.png"),
                    depth=str(render_dir / f"{group_key}_depth.png"),
                    segmentation=str(render_dir / f"{group_key}_segmentation.png"),
                ),
                segmentation_legend=legend_by_path.get(saved_path, []),
            )
            continue

        group_key = stem
        artifacts[render_path] = RenderArtifactMetadata(
            modality="rgb",
            group_key=group_key,
            siblings=RenderSiblingPaths(
                rgb=str(render_dir / f"{group_key}.png"),
                depth=str(render_dir / f"{group_key}_depth.png"),
                segmentation=str(render_dir / f"{group_key}_segmentation.png"),
            ),
        )

    return artifacts, render_paths


def _workspace_relative_render_paths(
    paths: list[str], workspace_root: Path
) -> list[str]:
    relative_paths: list[str] = []
    for path in paths:
        abs_path = Path(path)
        try:
            rel_path = abs_path.relative_to(workspace_root)
        except ValueError:
            rel_path = abs_path
        relative_paths.append(str(rel_path))
    return relative_paths


def prerender_24_views(
    component: Compound,
    output_dir: str | None = None,
    workspace_root: Path | None = None,
    objectives: BenchmarkDefinition | None = None,
    backend_type: SimulatorBackendType | None = None,
    session_id: str | None = None,
    scene_path: str | Path | None = None,
    smoke_test_mode: bool | None = None,
    particle_budget: int | None = None,
    revision: str | None = None,
    environment_version: str | None = None,
    publish_bundle_index: bool = True,
) -> list[str]:
    """
    Generates 24 renders (8 angles x 3 elevation levels) of the component.
    Saves to output_dir.
    """
    from shared.rendering import export_preview_scene_bundle
    from worker_heavy.config import settings
    from worker_renderer.utils.build123d_rendering import PREVIEW_BACKEND_NAME

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode
    requested_backend = backend_type or get_default_simulator_backend()
    requested_backend_value = (
        requested_backend.value
        if hasattr(requested_backend, "value")
        else str(requested_backend)
    )

    if output_dir is None:
        output_dir = os.getenv("RENDERS_DIR", "./renders")

    output_path = Path(output_dir)
    resolved_workspace_root = workspace_root or _workspace_root_from_render_dir(
        output_path
    )
    render_policy = load_agents_config().render
    logger.info(
        "prerender_24_views_start",
        output_dir=str(output_path),
        backend=PREVIEW_BACKEND_NAME,
        requested_backend=requested_backend_value,
        session_id=session_id,
        scene_path=str(scene_path) if scene_path else None,
        smoke_test_mode=smoke_test_mode,
        particle_budget=particle_budget,
        rgb_enabled=render_policy.rgb.enabled,
        depth_enabled=render_policy.depth.enabled,
        segmentation_enabled=render_policy.segmentation.enabled,
        rgb_axes_enabled=render_policy.rgb.axes,
        rgb_edges_enabled=render_policy.rgb.edges,
        depth_axes_enabled=render_policy.depth.axes,
        depth_edges_enabled=render_policy.depth.edges,
        segmentation_axes_enabled=render_policy.segmentation.axes,
        segmentation_edges_enabled=render_policy.segmentation.edges,
    )

    if not any(
        (
            render_policy.rgb.enabled,
            render_policy.depth.enabled,
            render_policy.segmentation.enabled,
        )
    ):
        logger.error(
            "prerender_requires_at_least_one_enabled_modality",
            session_id=session_id,
            rgb_enabled=render_policy.rgb.enabled,
            depth_enabled=render_policy.depth.enabled,
            segmentation_enabled=render_policy.segmentation.enabled,
        )
        raise ValueError(
            "validation preview requires at least one enabled render modality "
            "(rgb, depth, or segmentation)"
        )

    output_path.mkdir(parents=True, exist_ok=True)

    saved_files = []

    try:
        from worker_renderer.utils.rendering import (
            append_render_bundle_index,
            build_render_bundle_index_entry,
        )
        from worker_renderer.utils.rendering import (
            normalize_render_manifest as renderer_normalize_render_manifest,
        )

        emit_event(
            {
                "event_type": "validation_preview_backend_selected",
                "requested_physics_backend": requested_backend_value,
                "actual_preview_backend": PREVIEW_BACKEND_NAME,
                "purpose": "validation_static_preview",
                "session_id": session_id,
            }
        )

        preview_start = time.time()
        bundle_base64 = export_preview_scene_bundle(
            component,
            objectives=objectives,
            workspace_root=resolved_workspace_root,
            smoke_test_mode=smoke_test_mode,
        )
        response = render_static_preview(
            bundle_base64=bundle_base64,
            script_path="preview_scene.json",
            session_id=session_id or "renderer",
            agent_role=current_role_agent_name(resolved_workspace_root).value,
            smoke_test_mode=smoke_test_mode,
            particle_budget=particle_budget,
        )
        if not response.success:
            raise RuntimeError(response.message or "renderer returned failure")
        if response.artifacts is None:
            raise RuntimeError("renderer returned no artifacts")

        render_paths = materialize_render_artifacts(
            response.artifacts, resolved_workspace_root
        )
        render_paths = [
            path
            for path in render_paths
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
        ]
        if not render_paths:
            raise RuntimeError("renderer returned no preview image artifacts")
        bundle_path = str(Path(render_paths[0]).parent).replace("\\", "/")
        manifest_path = resolved_workspace_root / bundle_path / "render_manifest.json"
        existing_manifest = None
        if manifest_path.exists():
            try:
                existing_manifest = RenderManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except Exception:
                existing_manifest = None

        manifest = renderer_normalize_render_manifest(
            render_paths=render_paths,
            workspace_root=resolved_workspace_root,
            existing_manifest=existing_manifest,
            episode_id=session_id,
            worker_session_id=session_id,
            revision=revision,
            environment_version=environment_version,
            bundle_path=bundle_path,
        )
        manifest_path.write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )
        if publish_bundle_index:
            compat_manifest_path = (
                resolved_workspace_root / "renders" / "render_manifest.json"
            )
            if compat_manifest_path != manifest_path:
                compat_manifest_path.write_text(
                    manifest.model_dump_json(indent=2),
                    encoding="utf-8",
                )
            append_render_bundle_index(
                resolved_workspace_root,
                build_render_bundle_index_entry(
                    manifest,
                    manifest_path=str(
                        manifest_path.relative_to(resolved_workspace_root)
                    ).replace("\\", "/"),
                    primary_media_paths=list(render_paths),
                ),
            )
        saved_files = list(render_paths)

        emit_event(
            {
                "event_type": "validation_preview_render_complete",
                "preview_backend": PREVIEW_BACKEND_NAME,
                "image_count": len(render_paths),
                "elapsed_render_time": time.time() - preview_start,
                "artifact_paths": render_paths,
                "session_id": session_id,
            }
        )

        if not saved_files:
            saved_files = list(render_paths)

        logger.info(
            "prerender_complete",
            count=len(saved_files),
            session_id=session_id,
            backend=PREVIEW_BACKEND_NAME,
        )
        return saved_files
    except Exception as e:
        import traceback

        logger.warning(
            "prerender_failed",
            error=str(e),
            stack=traceback.format_exc(),
            session_id=session_id,
        )
        raise
