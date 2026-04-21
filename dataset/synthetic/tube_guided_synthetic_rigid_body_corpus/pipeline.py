from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import structlog
from build123d import Compound

from shared.enums import AgentName
from shared.models.schemas import (
    BenchmarkDefinition,
    CompoundMetadata,
    PayloadTrajectoryDefinition,
)
from shared.simulation.backends import SimulationScene
from shared.simulation.schemas import SimulatorBackendType

from .geometry import (
    box_part_specs_for_route,
    parts_from_specs,
)
from .models import ContactHit, PartSpec, RoutePoint, ScenarioConfig
from .paths import (
    REPO_ROOT,
    copy_tree,
    dump_yaml,
    payload_scene_name,
    write_json,
    write_text,
)

logger = structlog.get_logger(__name__)


def _active_stack_profile() -> str:
    return os.getenv("PROBLEMOLOGIST_STACK_PROFILE", "integration").strip().lower()


def _default_worker_renderer_url() -> str:
    if _active_stack_profile() == "eval":
        return "http://localhost:28003"
    return "http://localhost:18003"


def _default_s3_endpoint() -> str:
    if _active_stack_profile() == "eval":
        return "http://localhost:29000"
    return "http://localhost:19000"


def choose_batch_width(config: ScenarioConfig) -> int:
    lower, upper = config.batch_width_range
    return int(round((lower + upper) / 2.0))


def assert_payload_path_workspace_clear(
    *,
    workspace_root: Path,
    benchmark_definition: BenchmarkDefinition,
    payload_definition: PayloadTrajectoryDefinition,
    session_id: str | None = None,
) -> None:
    from worker_heavy.utils.payload_trajectory_validation import (
        validate_payload_trajectory_swept_clearance,
    )

    logger.info(
        "payload_path_swept_clearance_start",
        workspace_root=str(workspace_root),
        session_id=session_id,
    )
    errors = validate_payload_trajectory_swept_clearance(
        workspace_root=workspace_root,
        benchmark_definition=benchmark_definition,
        payload_definition=payload_definition,
        session_id=session_id,
    )
    if errors:
        raise RuntimeError("; ".join(errors))
    logger.info(
        "payload_path_swept_clearance_done",
        workspace_root=str(workspace_root),
        session_id=session_id,
    )


def contact_body_name(contact, payload_body_name: str) -> str | None:
    if contact.body1 == payload_body_name:
        return contact.body2
    if contact.body2 == payload_body_name:
        return contact.body1
    return None


def capture_contact_cloud(
    *,
    scene_path: Path,
    backend_type: SimulatorBackendType,
    benchmark_definition,
    duration_s: float,
    seed: int,
) -> list[ContactHit]:
    from worker_heavy.simulation.factory import get_physics_backend

    logger.info(
        "capture_contact_cloud_start",
        scene_path=str(scene_path),
        backend=backend_type.value,
        duration_s=duration_s,
        seed=seed,
    )
    backend = get_physics_backend(backend_type, session_id=f"tube-cloud-{seed}")
    backend.load_scene(SimulationScene(scene_path=str(scene_path)))
    payload_name = payload_scene_name(benchmark_definition.payload.label)
    dt = getattr(backend, "timestep", 0.002)
    steps = max(1, int(duration_s / dt))
    hits: list[ContactHit] = []

    try:
        for _ in range(steps):
            result = backend.step(dt)
            if not result.success:
                break
            current_time = float(result.time)
            for contact in backend.get_contact_forces():
                other = contact_body_name(contact, payload_name)
                if other is None:
                    continue
                if not other.startswith("seg_"):
                    continue
                hits.append(
                    ContactHit(
                        time_s=current_time,
                        position_mm=tuple(float(v) for v in contact.position),
                        payload_body=payload_name,
                        other_body=other,
                        force_n=tuple(float(v) for v in contact.force),
                    )
                )
    finally:
        backend.close()
    logger.info(
        "capture_contact_cloud_done",
        scene_path=str(scene_path),
        backend=backend_type.value,
        hit_count=len(hits),
    )
    return hits


def hits_by_part(contact_hits: list[ContactHit]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for hit in contact_hits:
        counter[hit.other_body] += 1
    return counter


def prune_segment_specs(
    specs: list[PartSpec],
    contact_hits: list[ContactHit],
    *,
    min_hits: int = 1,
) -> list[PartSpec]:
    by_name = hits_by_part(contact_hits)
    grouped: dict[tuple[int, int], list[PartSpec]] = defaultdict(list)
    for spec in specs:
        grouped[(spec.segment_index, spec.split_index)].append(spec)

    kept: list[PartSpec] = []
    for key in sorted(grouped):
        group = grouped[key]
        selected = [spec for spec in group if by_name[spec.name] >= min_hits]
        if not selected:
            logger.info(
                "prune_segment_specs_drop_span",
                segment_index=key[0],
                split_index=key[1],
                part_count=len(group),
            )
            continue

        kept.extend(
            sorted(
                selected,
                key=lambda spec: (spec.segment_index, spec.split_index, spec.side),
            )
        )

    return kept


def build_scene_xml(
    *,
    benchmark_definition,
    assembly,
    output_dir: Path,
    backend_type: SimulatorBackendType,
) -> Path:
    from worker_heavy.simulation.factory import get_simulation_builder

    builder = get_simulation_builder(
        output_dir=output_dir,
        backend_type=backend_type,
        use_vhacd=False,
    )
    return builder.build_from_assembly(
        assembly, objectives=benchmark_definition, payload_parts=None
    )


def write_bundle(
    *,
    root_dir: Path,
    benchmark_definition_yaml: dict[str, Any],
    benchmark_assembly_text: str,
    benchmark_script_text: str,
    assembly_definition_yaml: dict[str, Any],
    evidence_script_text: str,
    solution_script_text: str | None = None,
    payload_trajectory_yaml: dict[str, Any] | None = None,
    markdown_files: dict[str, str] | None = None,
    extra_files: dict[str, str] | None = None,
    copy_reviews_from: Path | None = None,
) -> None:
    logger.info("write_bundle_start", root_dir=str(root_dir))
    root_dir.mkdir(parents=True, exist_ok=True)
    solution_dir = root_dir / ".solution"
    solution_dir.mkdir(parents=True, exist_ok=True)

    root_payloads: dict[str, Any] = {
        "benchmark_definition.yaml": benchmark_definition_yaml,
        "benchmark_assembly_definition.yaml": benchmark_assembly_text,
        "benchmark_script.py": benchmark_script_text,
        "assembly_definition.yaml": assembly_definition_yaml,
        "solution_plan_evidence_script.py": evidence_script_text,
    }
    if solution_script_text is not None:
        root_payloads["solution_script.py"] = solution_script_text
    if payload_trajectory_yaml is not None:
        root_payloads["payload_trajectory_definition.yaml"] = payload_trajectory_yaml
    if markdown_files:
        root_payloads.update(markdown_files)
    if extra_files:
        root_payloads.update(extra_files)

    for name, payload in root_payloads.items():
        target = root_dir / name
        if isinstance(payload, str):
            write_text(target, payload)
        else:
            dump_yaml(target, payload)

    for name, payload in root_payloads.items():
        target = solution_dir / name
        if isinstance(payload, str):
            write_text(target, payload)
        else:
            dump_yaml(target, payload)

    if copy_reviews_from and copy_reviews_from.exists():
        copy_tree(copy_reviews_from, root_dir / "reviews")
        copy_tree(copy_reviews_from, solution_dir / "reviews")
    logger.info(
        "write_bundle_done",
        root_dir=str(root_dir),
        file_count=len(root_payloads),
    )


def update_dataset_row(path: Path, row: dict[str, Any]) -> None:
    logger.info("update_dataset_row", path=str(path), row_id=row.get("id"))
    rows = []
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
        rows = [existing for existing in rows if existing.get("id") != row["id"]]
    rows.append(row)
    rows.sort(key=lambda item: str(item.get("id", "")))
    write_json(path, rows)


def role_row(
    *,
    row_id: str,
    agent: AgentName,
    bundle_dir: Path,
    scenario_id: str,
    description: str,
) -> dict[str, Any]:
    task = (
        f"Use the seeded artifacts in the workspace to finish the {scenario_id} "
        f"{agent.value} handoff."
    )
    expected = description
    return {
        "id": row_id,
        "task": task,
        "seed_artifact_dir": str(bundle_dir.as_posix()),
        "expected_criteria": expected,
        "complexity_level": 2,
    }


def render_debug_plots(
    *,
    output_dir: Path,
    route_points: list[RoutePoint],
    tube_radius_mm: float,
    contact_hits: list[ContactHit],
    part_specs: list[PartSpec],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    route = np.asarray([point.pos_mm for point in route_points], dtype=float)
    contacts = (
        np.asarray([hit.position_mm for hit in contact_hits], dtype=float)
        if contact_hits
        else np.empty((0, 3))
    )

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(
        route[:, 0],
        route[:, 1],
        route[:, 2],
        color="#214d9c",
        linewidth=2.5,
        label="route",
    )
    if len(contacts):
        ax.scatter(
            contacts[:, 0],
            contacts[:, 1],
            contacts[:, 2],
            color="#c0392b",
            s=16,
            label="wall contacts",
        )
    for spec in part_specs[: min(24, len(part_specs))]:
        cx, cy, cz = spec.center_mm
        ax.scatter([cx], [cy], [cz], color="#2e8b57", s=10, alpha=0.6)
    ax.set_title(f"tube radius {tube_radius_mm:.2f} mm")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(output_dir / "route_contacts_3d.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].plot(route[:, 0], route[:, 1], color="#214d9c")
    axes[0].scatter(route[:, 0], route[:, 1], color="#214d9c")
    axes[0].set_title("XY")
    axes[1].plot(route[:, 0], route[:, 2], color="#214d9c")
    axes[1].scatter(route[:, 0], route[:, 2], color="#214d9c")
    axes[1].set_title("XZ")
    axes[2].plot(route[:, 1], route[:, 2], color="#214d9c")
    axes[2].scatter(route[:, 1], route[:, 2], color="#214d9c")
    axes[2].set_title("YZ")
    for axis in axes:
        axis.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "route_projections.png", dpi=180)
    plt.close(fig)


def log_verification_failure_diagnostics(
    *,
    retry_seed: int,
    backend_type: SimulatorBackendType,
    verify_result: Any,
    route_points: list[RoutePoint],
    simulation_bounds_mm: Any | None = None,
) -> dict[str, Any]:
    failed_result = next(
        (
            result
            for result in getattr(verify_result, "individual_results", [])
            if not result.success
        ),
        None,
    )
    failure_reason = None
    failure_detail = None
    monitor_state = None
    stuck_body_name = None
    stuck_position_mm: list[float] | None = None
    stuck_position_source = "unknown"
    failure_position_mm: list[float] | None = None
    failure_step_index: int | None = None
    failure_step_count: int | None = None
    failure_time_s: float | None = None

    if failed_result is not None:
        failure_reason = str(getattr(failed_result, "fail_reason", None) or "")
        failure = getattr(failed_result, "failure", None)
        if failure is not None:
            failure_detail = getattr(failure, "detail", None)
            monitor_state = getattr(failure, "payload_trajectory_monitor", None)
            raw_failure_position = getattr(failure, "failure_position_mm", None)
            if raw_failure_position is not None:
                failure_position_mm = [float(v) for v in raw_failure_position]
            raw_failure_step_index = getattr(failure, "failure_step_index", None)
            if raw_failure_step_index is not None:
                failure_step_index = int(raw_failure_step_index)
                failure_step_count = failure_step_index + 1
            raw_failure_time_s = getattr(failure, "failure_time_s", None)
            if raw_failure_time_s is not None:
                failure_time_s = float(raw_failure_time_s)
        if monitor_state is None:
            monitor_state = getattr(failed_result, "payload_trajectory_monitor", None)
    else:
        fail_reasons = list(getattr(verify_result, "fail_reasons", []) or [])
        if fail_reasons:
            failure_reason = str(fail_reasons[0])

    if failure_position_mm is not None:
        stuck_position_mm = failure_position_mm
        stuck_position_source = "simulation_failure"
    elif monitor_state is not None:
        observed_position = getattr(monitor_state, "observed_position_mm", None)
        if observed_position is not None:
            stuck_position_mm = [float(v) for v in observed_position]
            stuck_position_source = "payload_trajectory_monitor"
        stuck_body_name = getattr(monitor_state, "failure_detail", None)

    if stuck_body_name is None and failure_detail:
        stuck_body_name = str(failure_detail)
    if stuck_body_name is None and failure_reason and ":" in failure_reason:
        stuck_body_name = failure_reason.split(":", 1)[1].strip() or None

    if stuck_position_mm is None:
        stuck_position_mm = [float(v) for v in route_points[0].pos_mm]
        stuck_position_source = "route_start_hint"

    summary = {
        "retry_seed": retry_seed,
        "backend": backend_type.value,
        "success_rate": float(getattr(verify_result, "success_rate", 0.0)),
        "failure_reason": failure_reason,
        "failure_detail": failure_detail,
        "stuck_body_name": stuck_body_name,
        "stuck_position_mm": stuck_position_mm,
        "stuck_position_source": stuck_position_source,
        "failure_position_mm": failure_position_mm,
        "failure_step_index": failure_step_index,
        "failure_step_count": failure_step_count,
        "failure_time_s": failure_time_s,
        "first_route_point_mm": [float(v) for v in route_points[0].pos_mm],
        "goal_route_point_mm": [float(v) for v in route_points[-1].pos_mm],
        "simulation_bounds_mm": (
            simulation_bounds_mm.model_dump()
            if simulation_bounds_mm is not None
            else None
        ),
    }
    logger.info("verification_stuck_summary", **summary)
    return summary


def render_startup_workspace_preview(
    *,
    workspace_root: Path,
    artifact_root: Path | None = None,
    orbit_pitch_deg: float = 45.0,
    orbit_yaw_deg: float = 45.0,
    payload_path: bool = True,
) -> dict[str, Any]:
    from shared.rendering.renderer_client import (
        bundle_workspace_base64,
        materialize_preview_response,
        render_cad,
    )

    os.environ.setdefault("WORKER_RENDERER_URL", _default_worker_renderer_url())
    materialization_root = artifact_root or workspace_root

    try:
        response = render_cad(
            bundle_base64=bundle_workspace_base64(workspace_root),
            script_path="solution_script.py",
            orbit_pitch=orbit_pitch_deg,
            orbit_yaw=orbit_yaw_deg,
            rgb=True,
            depth=False,
            segmentation=False,
            payload_path=payload_path,
        )
    except Exception as exc:
        logger.warning("startup_render_preview_failed", error=str(exc))
        return {
            "success": False,
            "status_text": str(exc),
            "message": str(exc),
            "image_path": None,
            "artifact_path": None,
            "manifest_path": None,
            "materialized_paths": {},
            "artifact_root": str(materialization_root),
        }

    materialized_paths: dict[str, str] = {}
    preview_output_dir = materialization_root / "renders" / "current-episode"
    image_path = materialize_preview_response(response, preview_output_dir)

    if response.render_blobs_base64:
        for rel_path in response.render_blobs_base64:
            materialized_paths[rel_path] = str(materialization_root / rel_path)
    if response.object_store_keys:
        for rel_path, object_key in response.object_store_keys.items():
            materialized_paths[rel_path] = str(materialization_root / rel_path)
    if response.image_bytes_base64 and response.image_path:
        materialized_paths[response.image_path] = str(image_path)
    if response.render_manifest_json:
        manifest_path = preview_output_dir / "render_manifest.json"
        materialized_paths[str(manifest_path.relative_to(materialization_root))] = str(
            manifest_path
        )

    return {
        "success": response.success,
        "status_text": response.status_text,
        "message": response.message,
        "image_path": str(image_path)
        if image_path is not None
        else response.image_path,
        "artifact_path": (
            str(materialization_root / response.artifact_path)
            if response.artifact_path and not Path(response.artifact_path).is_absolute()
            else response.artifact_path
        ),
        "manifest_path": (
            str(materialization_root / response.manifest_path)
            if response.manifest_path and not Path(response.manifest_path).is_absolute()
            else response.manifest_path
        ),
        "object_store_keys": response.object_store_keys,
        "render_blobs_base64": response.render_blobs_base64,
        "materialized_paths": materialized_paths,
        "artifact_root": str(materialization_root),
    }


def render_simulation_video_preview(
    *,
    backend_type: SimulatorBackendType,
    script_content: str,
    session_id: str,
    workspace_root: Path,
    artifact_root: Path | None = None,
) -> dict[str, Any]:
    from shared.models.simulation import SimulationResult
    from shared.observability.storage import S3Client, S3Config
    from shared.rendering.renderer_client import bundle_workspace_base64
    from shared.utils.agent import simulate_benchmark_script_content

    with tempfile.TemporaryDirectory() as staging_dir:
        staging_root = Path(staging_dir)
        required_sources = {
            ".manifests/current_role.json": REPO_ROOT
            / ".manifests"
            / "current_role.json",
            "benchmark_definition.yaml": workspace_root / "benchmark_definition.yaml",
            "payload_trajectory_definition.yaml": (
                workspace_root / "payload_trajectory_definition.yaml"
            ),
            "assembly_definition.yaml": workspace_root / "assembly_definition.yaml",
        }
        for rel_path, source in required_sources.items():
            if not source.exists():
                raise FileNotFoundError(
                    f"render_simulation_video_preview missing required artifact: "
                    f"{source}"
                )
            target = staging_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        response = simulate_benchmark_script_content(
            script_content=script_content,
            script_path="solution_script.py",
            backend=backend_type,
            smoke_test_mode=False,
            skip_preview_rendering=True,
            session_id=session_id,
            bundle_base64=bundle_workspace_base64(staging_root),
        )
    artifacts = response.artifacts
    render_paths = list(artifacts.render_paths) if artifacts else []
    object_store_keys = dict(artifacts.object_store_keys) if artifacts else {}
    video_path = next(
        (path for path in render_paths if Path(path).suffix.lower() == ".mp4"),
        None,
    )
    object_pose_path = next(
        (path for path in render_paths if Path(path).name == "objects.parquet"),
        None,
    )
    render_blobs = dict(artifacts.render_blobs_base64) if artifacts else {}
    local_video_path = None
    if video_path and video_path in render_blobs:
        local_video_path = workspace_root / video_path
        local_video_path.parent.mkdir(parents=True, exist_ok=True)
        local_video_path.write_bytes(base64.b64decode(render_blobs[video_path]))
    local_object_pose_path = None
    if object_pose_path and object_pose_path in render_blobs:
        local_object_pose_path = workspace_root / object_pose_path
        local_object_pose_path.parent.mkdir(parents=True, exist_ok=True)
        local_object_pose_path.write_bytes(
            base64.b64decode(render_blobs[object_pose_path])
        )
    if object_store_keys:
        s3_endpoint = os.getenv("S3_ENDPOINT", _default_s3_endpoint())
        access_key = os.getenv(
            "S3_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
        )
        secret_key = os.getenv(
            "S3_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
        )
        bucket_name = os.getenv("ASSET_S3_BUCKET", "problemologist")
        storage = S3Client(
            S3Config(
                endpoint_url=s3_endpoint,
                access_key_id=access_key,
                secret_access_key=secret_key,
                bucket_name=bucket_name,
                region_name=os.getenv("AWS_REGION", "us-east-1"),
            )
        )
        for rel_path, object_key in object_store_keys.items():
            target_path = workspace_root / rel_path
            if target_path.exists():
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            storage.download_file(object_key, target_path)
            if rel_path == video_path:
                local_video_path = target_path
            if rel_path == object_pose_path:
                local_object_pose_path = target_path
    summary = {
        "success": bool(response.success),
        "status_text": response.message,
        "message": response.message,
        "video_path": video_path,
        "object_pose_path": object_pose_path,
        "local_video_path": str(local_video_path) if local_video_path else None,
        "local_object_pose_path": (
            str(local_object_pose_path) if local_object_pose_path else None
        ),
        "render_paths": render_paths,
        "object_store_keys": object_store_keys,
        "failure_reason": str(artifacts.failure)
        if artifacts and artifacts.failure
        else None,
        "simulation_result_json": (
            artifacts.simulation_result_json if artifacts else None
        ),
        "artifact_root": str(artifact_root) if artifact_root is not None else None,
    }
    if artifacts and artifacts.simulation_result_json:
        try:
            simulation_result = SimulationResult.model_validate_json(
                artifacts.simulation_result_json
            )
            render_provenance = simulation_result.render_provenance
            payload_monitor = simulation_result.payload_trajectory_monitor
            summary["render_provenance"] = (
                render_provenance.model_dump(mode="json")
                if render_provenance is not None
                else None
            )
            summary["tracked_body_names"] = (
                list(payload_monitor.tracked_body_names)
                if payload_monitor is not None
                else []
            )
            summary["resolved_camera_name"] = (
                render_provenance.resolved_camera_name
                if render_provenance is not None
                else None
            )
            summary["camera_candidates"] = (
                list(render_provenance.camera_candidates)
                if render_provenance is not None
                else []
            )
        except Exception as exc:
            summary["simulation_result_parse_error"] = str(exc)
    if artifact_root is not None:
        copy_tree(workspace_root / "renders", artifact_root / "renders")
        if (workspace_root / "simulation_result.json").exists():
            (artifact_root / "simulation_result.json").parent.mkdir(
                parents=True, exist_ok=True
            )
            shutil.copy2(
                workspace_root / "simulation_result.json",
                artifact_root / "simulation_result.json",
            )
    logger.info("simulation_video_rendered", **summary)
    return summary


def stage_bundle_root(
    *,
    root: Path,
    benchmark_definition_yaml: dict[str, Any],
    benchmark_script_text: str,
    benchmark_assembly_text: str,
    assembly_definition_yaml: dict[str, Any],
    evidence_script_text: str,
    solution_script_text: str | None = None,
    payload_trajectory_yaml: dict[str, Any] | None = None,
    markdown_files: dict[str, str] | None = None,
    copy_reviews_from: Path | None = None,
) -> None:
    logger.info("stage_bundle_root", root=str(root))
    write_bundle(
        root_dir=root,
        benchmark_definition_yaml=benchmark_definition_yaml,
        benchmark_assembly_text=benchmark_assembly_text,
        benchmark_script_text=benchmark_script_text,
        assembly_definition_yaml=assembly_definition_yaml,
        evidence_script_text=evidence_script_text,
        solution_script_text=solution_script_text,
        payload_trajectory_yaml=payload_trajectory_yaml,
        markdown_files=markdown_files,
        copy_reviews_from=copy_reviews_from,
    )


def candidate_layout_summary(
    part_specs: list[PartSpec],
) -> dict[tuple[int, int], list[str]]:
    grouped: dict[tuple[int, int], list[str]] = defaultdict(list)
    for spec in part_specs:
        grouped[(spec.segment_index, spec.split_index)].append(spec.side)
    return grouped


def build_candidate_assembly(
    *,
    route_points: list[RoutePoint],
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    seed: int,
    material_id: str,
) -> tuple[list[PartSpec], Compound]:
    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=seed,
        material_id=material_id,
    )
    parts = parts_from_specs(specs)
    compound = Compound(children=parts)
    compound.label = "synthetic_route_candidate"
    compound.metadata = CompoundMetadata(is_fixed=True)
    return specs, compound


def backfill_source_solution(
    *,
    source_seed_bundle_dir: Path,
    solved_coder_root: Path,
) -> None:
    source_solution_root = source_seed_bundle_dir / ".solution"
    solved_solution_root = solved_coder_root / ".solution"
    if not solved_solution_root.exists():
        raise FileNotFoundError(
            f"Missing solved solution bundle at {solved_solution_root}"
        )
    if source_solution_root.exists():
        shutil.rmtree(source_solution_root)
    shutil.copytree(solved_solution_root, source_solution_root)
    logger.info(
        "backfill_source_solution_done",
        source_seed_bundle_dir=str(source_seed_bundle_dir),
        source_solution_root=str(source_solution_root),
        solved_solution_root=str(solved_solution_root),
    )
