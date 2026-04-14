from __future__ import annotations

import contextlib
import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from shared.current_role import current_role_agent_name
from shared.enums import AgentName
from shared.git_utils import repo_revision
from shared.workers.schema import (
    RenderArtifactMetadata,
    RenderBundleIdentity,
    RenderBundleIndexEntry,
    RenderManifest,
    RenderSiblingPaths,
)


def _derived_episode_id(session_id: str | None) -> str | None:
    if not session_id:
        return None
    try:
        return str(uuid.UUID(session_id))
    except Exception:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, session_id))


def _bundle_path_from_artifacts(
    *,
    workspace_root: Path | None,
    artifacts: dict[str, RenderArtifactMetadata],
) -> str | None:
    candidate_paths = sorted(
        path
        for path in artifacts
        if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
    )
    if not candidate_paths:
        return None

    bundle_parent = Path(candidate_paths[0]).parent
    if workspace_root is not None:
        with contextlib.suppress(Exception):
            bundle_parent = bundle_parent.relative_to(workspace_root)
    return str(bundle_parent).replace("\\", "/")


def _resolve_bundle_scene_hash(
    *,
    workspace_root: Path | None,
    bundle_path: str | None,
    artifacts: dict[str, RenderArtifactMetadata],
) -> str | None:
    if workspace_root is None or not bundle_path:
        return None

    bundle_root = workspace_root / bundle_path
    for candidate in (
        bundle_root / "preview_scene.json",
        bundle_root / "frames.jsonl",
    ):
        if candidate.exists():
            try:
                return hashlib.sha256(candidate.read_bytes()).hexdigest()
            except Exception:
                continue

    candidate_paths = sorted(
        path
        for path in artifacts
        if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
    )
    if not candidate_paths:
        return None

    digest = hashlib.sha256()
    for rel_path in candidate_paths:
        digest.update(str(rel_path).encode("utf-8"))
        digest.update(b"\0")
        candidate = workspace_root / rel_path
        if candidate.exists():
            try:
                digest.update(candidate.read_bytes())
            except Exception:
                continue
    return digest.hexdigest()


def _build_render_identity(
    *,
    workspace_root: Path | None,
    artifacts: dict[str, RenderArtifactMetadata],
    revision: str,
    bundle_path: str | None = None,
    created_at: str | None = None,
    bundle_id: str | None = None,
    scene_hash: str | None = None,
) -> RenderBundleIdentity:
    resolved_bundle_path = bundle_path or _bundle_path_from_artifacts(
        workspace_root=workspace_root,
        artifacts=artifacts,
    )
    resolved_scene_hash = scene_hash or _resolve_bundle_scene_hash(
        workspace_root=workspace_root,
        bundle_path=resolved_bundle_path,
        artifacts=artifacts,
    )
    resolved_created_at = created_at or datetime.now(UTC).isoformat()
    resolved_bundle_id = bundle_id
    if not resolved_bundle_id:
        seed = "|".join(
            part
            for part in (
                revision,
                resolved_bundle_path or "",
                resolved_scene_hash or "",
                resolved_created_at,
            )
            if part
        )
        resolved_bundle_id = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
    return RenderBundleIdentity(
        bundle_id=resolved_bundle_id,
        created_at=resolved_created_at,
        revision=revision,
        scene_hash=resolved_scene_hash,
        bundle_path=resolved_bundle_path,
    )


def _workspace_environment_version(workspace_root: Path | None) -> str | None:
    if workspace_root is None:
        return None

    for rel_path in ("benchmark_assembly_definition.yaml", "assembly_definition.yaml"):
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
    bundle_path: str | None = None,
    created_at: str | None = None,
    bundle_id: str | None = None,
    scene_hash: str | None = None,
    source_script_sha256: str | None = None,
) -> RenderManifest:
    resolved_revision = revision
    if not resolved_revision:
        resolved_revision = os.getenv("REPO_REVISION")
    if not resolved_revision:
        resolved_revision = repo_revision(Path.cwd())
    if not resolved_revision and workspace_root is not None:
        resolved_revision = repo_revision(workspace_root)
    if not resolved_revision:
        resolved_revision = repo_revision(Path(__file__).resolve().parents[2])

    if environment_version is None:
        environment_version = _workspace_environment_version(workspace_root)

    if preview_evidence_paths is None:
        preview_evidence_paths = sorted(
            path
            for path in artifacts
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
        )

    identity = _build_render_identity(
        workspace_root=workspace_root,
        artifacts=artifacts,
        revision=resolved_revision,
        bundle_path=bundle_path,
        created_at=created_at,
        bundle_id=bundle_id,
        scene_hash=scene_hash,
    )
    return RenderManifest(
        bundle_id=identity.bundle_id,
        created_at=identity.created_at,
        episode_id=_derived_episode_id(episode_id),
        worker_session_id=worker_session_id,
        revision=resolved_revision,
        scene_hash=identity.scene_hash,
        bundle_path=identity.bundle_path,
        environment_version=environment_version,
        source_script_sha256=source_script_sha256,
        preview_evidence_paths=preview_evidence_paths,
        artifacts=artifacts,
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
    workspace_root: Path | None = None,
    existing: RenderArtifactMetadata | None = None,
) -> RenderArtifactMetadata:
    group_key, modality = _render_group_key(render_path)
    rel_path = Path(render_path)
    render_dir = rel_path.parent
    svg_candidate = rel_path.with_suffix(".svg")
    dxf_candidate = rel_path.with_suffix(".dxf")
    svg_path = None
    dxf_path = None
    if workspace_root is not None:
        if (workspace_root / svg_candidate).exists():
            svg_path = svg_candidate.as_posix()
        if (workspace_root / dxf_candidate).exists():
            dxf_path = dxf_candidate.as_posix()
    metadata = RenderArtifactMetadata(
        modality=modality,
        group_key=group_key,
        siblings=RenderSiblingPaths(
            rgb=str(render_dir / f"{group_key}.png"),
            depth=str(render_dir / f"{group_key}_depth.png"),
            segmentation=str(render_dir / f"{group_key}_segmentation.png"),
            svg=svg_path,
            dxf=dxf_path,
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
    source_script_sha256: str | None = None,
) -> RenderManifest:
    existing_artifacts = dict(existing_manifest.artifacts) if existing_manifest else {}
    normalized_artifacts: dict[str, RenderArtifactMetadata] = {}
    for render_path in render_paths:
        suffix = Path(render_path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".mp4"}:
            continue
        normalized_artifacts[render_path] = _infer_render_artifact_metadata(
            render_path,
            workspace_root=workspace_root,
            existing=existing_artifacts.get(render_path),
        )

    resolved_revision = revision
    if not resolved_revision and existing_manifest is not None:
        resolved_revision = existing_manifest.revision
    resolved_environment_version = environment_version
    if resolved_environment_version is None and existing_manifest is not None:
        resolved_environment_version = existing_manifest.environment_version
    resolved_source_script_sha256 = source_script_sha256
    if resolved_source_script_sha256 is None and existing_manifest is not None:
        resolved_source_script_sha256 = existing_manifest.source_script_sha256

    return build_render_manifest(
        normalized_artifacts,
        workspace_root=workspace_root,
        episode_id=episode_id,
        worker_session_id=worker_session_id,
        revision=resolved_revision,
        environment_version=resolved_environment_version,
        preview_evidence_paths=preview_evidence_paths,
        bundle_path=bundle_path,
        created_at=created_at,
        bundle_id=bundle_id,
        scene_hash=scene_hash,
        source_script_sha256=resolved_source_script_sha256,
    )


def build_render_bundle_index_entry(
    manifest: RenderManifest,
    *,
    manifest_path: str,
    primary_media_paths: list[str] | None = None,
) -> RenderBundleIndexEntry:
    """Build the append-only discovery row for one published bundle."""

    return RenderBundleIndexEntry(
        bundle_id=manifest.bundle_id,
        created_at=manifest.created_at,
        revision=manifest.revision,
        scene_hash=manifest.scene_hash,
        bundle_path=manifest.bundle_path,
        manifest_path=manifest_path,
        preview_evidence_paths=list(manifest.preview_evidence_paths),
        primary_media_paths=primary_media_paths
        or list(manifest.preview_evidence_paths),
    )


def append_render_bundle_index(root: Path, entry: RenderBundleIndexEntry) -> Path:
    """Append a render bundle history row to the append-only index."""

    index_path = root / "renders" / "render_index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json())
        handle.write("\n")
    return index_path


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
    return "current-episode"


def select_scratch_preview_render_subdir(
    workspace_root: Path, *, agent_role: str | None = None
) -> str:
    return "current-episode"


def select_static_preview_render_subdir(
    workspace_root: Path, *, agent_role: str | None = None
) -> str:
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
