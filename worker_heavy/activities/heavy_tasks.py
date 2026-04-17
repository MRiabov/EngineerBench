import asyncio
import base64
import tempfile
from pathlib import Path

import structlog
from temporalio import activity

from shared.models.simulation import SimulationResult
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.loader import load_component_from_script
from shared.workers.schema import (
    BenchmarkToolResponse,
    HeavyPreviewParams,
    HeavyPreviewResponse,
    HeavySimulationParams,
    HeavySubmitParams,
    HeavyVerifyParams,
    SimulationArtifacts,
)
from worker_heavy.runtime.simulation_runner import run_simulation_in_isolated_process
from worker_heavy.utils import renderer_client
from worker_heavy.utils.handover import submit_for_review
from worker_heavy.utils.verification import run_verification_job

logger = structlog.get_logger(__name__)

_RENDER_SIDE_CAR_FILENAMES = {
    "render_manifest.json",
    "render_index.jsonl",
    "preview_scene.json",
    "frames.jsonl",
    "objects.parquet",
}


def _extract_bundle(bundle_bytes: bytes, target_dir: Path):
    """Extract gzipped tarball to target directory using system tar."""
    import subprocess

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
        tf.write(bundle_bytes)
        tf_path = tf.name
    try:
        subprocess.run(
            ["tar", "-zxf", tf_path, "-C", str(target_dir), "--no-same-owner"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as spe:
        logger.warning("tar_subprocess_failed", stderr=spe.stderr)
        raise RuntimeError(f"tar extraction failed: {spe.stderr}")
    finally:
        if Path(tf_path).exists():
            Path(tf_path).unlink()


def _decode_bundle(bundle_base64: str) -> bytes:
    return base64.b64decode(bundle_base64)


def _is_render_payload_file(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"} or (
        path.name in _RENDER_SIDE_CAR_FILENAMES
    )


def _collect_render_payload_blobs(root: Path) -> dict[str, str]:
    render_blobs_base64: dict[str, str] = {}
    renders_dir = root / "renders"
    if not renders_dir.exists():
        return render_blobs_base64

    for render_path in sorted(renders_dir.rglob("*")):
        if not render_path.is_file() or not _is_render_payload_file(render_path):
            continue
        rel_path = str(render_path.relative_to(root))
        render_blobs_base64[rel_path] = base64.b64encode(
            render_path.read_bytes()
        ).decode("ascii")
    return render_blobs_base64


def _collect_submission_artifacts(
    root: Path, *, session_id: str | None = None
) -> SimulationArtifacts:
    artifacts = SimulationArtifacts()

    validation_result_path = root / "validation_results.json"
    if validation_result_path.exists():
        artifacts.validation_results_json = validation_result_path.read_text(
            encoding="utf-8"
        )

    sim_result_path = root / "simulation_result.json"
    if sim_result_path.exists():
        artifacts.simulation_result_json = sim_result_path.read_text(encoding="utf-8")

    stage_manifest_paths = (
        ".manifests/benchmark_plan_review_manifest.json",
        ".manifests/benchmark_review_manifest.json",
        ".manifests/engineering_plan_review_manifest.json",
        ".manifests/engineering_execution_handoff_manifest.json",
    )
    review_manifests: dict[str, str] = {}
    for rel_path in stage_manifest_paths:
        manifest_path = root / rel_path
        if manifest_path.exists():
            review_manifests[rel_path] = manifest_path.read_text(encoding="utf-8")
    artifacts.review_manifests_json = review_manifests

    render_blobs_base64: dict[str, str] = {}
    renders_dir = root / "renders"
    if renders_dir.exists():
        for render_path in sorted(renders_dir.rglob("*")):
            if not render_path.is_file():
                continue
            if render_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".mp4"}:
                continue
            rel_path = str(render_path.relative_to(root))
            artifacts.render_paths.append(rel_path)
            render_blobs_base64[rel_path] = base64.b64encode(
                render_path.read_bytes()
            ).decode("ascii")
    render_blobs_base64.update(_collect_render_payload_blobs(root))
    artifacts.render_blobs_base64 = render_blobs_base64
    return artifacts


def _collect_simulation_artifacts(
    root: Path, result: SimulationResult, *, session_id: str | None = None
) -> SimulationArtifacts:
    artifacts = SimulationArtifacts(
        render_paths=list(result.render_paths),
        object_store_keys=dict(result.render_object_store_keys),
        mjcf_content=result.mjcf_content,
        failure=result.failure,
        total_cost=result.total_cost,
        total_weight_g=result.total_weight_g,
    )

    sim_result_path = root / "simulation_result.json"
    if sim_result_path.exists():
        artifacts.simulation_result_json = sim_result_path.read_text(encoding="utf-8")

    render_blobs_base64: dict[str, str] = {}
    for raw_path in artifacts.render_paths:
        render_path = root / raw_path
        if not render_path.exists() or not render_path.is_file():
            continue
        suffix = render_path.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".mp4"}:
            continue
        rel_path = str(Path(raw_path))
        if rel_path in artifacts.object_store_keys and suffix == ".mp4":
            continue
        render_blobs_base64[rel_path] = base64.b64encode(
            render_path.read_bytes()
        ).decode("ascii")
    render_blobs_base64.update(_collect_render_payload_blobs(root))
    artifacts.render_blobs_base64 = render_blobs_base64
    return artifacts


@activity.defn(name="worker_run_simulation")
async def run_simulation_activity(
    params: HeavySimulationParams,
) -> BenchmarkToolResponse:
    """Execute physics simulation from a session bundle."""
    bundle_bytes = _decode_bundle(params.bundle_base64)
    script_path = params.script_path
    backend = params.backend
    smoke_test_mode = params.smoke_test_mode
    session_id = params.session_id

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _extract_bundle(bundle_bytes, root)

        # backend might be a string from temporal, convert to enum
        backend_type = SimulatorBackendType(backend)

        result = await run_simulation_in_isolated_process(
            script_path=str(root / script_path),
            session_root=str(root),
            script_content=None,
            output_dir=root,
            smoke_test_mode=smoke_test_mode,
            backend=backend_type,
            session_id=session_id or "",
            episode_id=params.episode_id,
            stream_render_frames=params.stream_render_frames,
            particle_budget=None,
        )
        artifacts = _collect_simulation_artifacts(root, result, session_id=session_id)
        return BenchmarkToolResponse(
            success=result.success,
            message=result.summary,
            confidence=result.confidence,
            artifacts=artifacts,
        )


@activity.defn(name="worker_verify_design")
async def verify_design_activity(
    params: HeavyVerifyParams,
) -> BenchmarkToolResponse:
    """Execute runtime-randomization verification from a session bundle."""
    bundle_bytes = _decode_bundle(params.bundle_base64)
    session_id = params.session_id

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _extract_bundle(bundle_bytes, root)
        return await run_verification_job(root, params, session_id=session_id)


@activity.defn(name="worker_preview_design")
async def preview_design_activity(params: HeavyPreviewParams) -> HeavyPreviewResponse:
    """Render design preview from a session bundle."""
    pitch = params.orbit_pitch_deg
    yaw = params.orbit_yaw_deg
    response = await asyncio.to_thread(
        renderer_client.render_preview,
        bundle_base64=params.bundle_base64,
        script_path=params.script_path,
        orbit_pitch=pitch,
        orbit_yaw=yaw,
        rgb=params.rgb,
        depth=params.depth,
        segmentation=params.segmentation,
        rendering_type=params.rendering_type,
    )

    image_bytes = (
        base64.b64decode(response.image_bytes_base64)
        if response.image_bytes_base64
        else None
    )
    image_path = response.image_path
    if response.image_path:
        filename = Path(response.image_path).name
    elif isinstance(pitch, list) and pitch and isinstance(yaw, list) and yaw:
        filename = f"preview_pitch{int(pitch[0])}_yaw{int(yaw[0])}.png"
    elif isinstance(pitch, list) and pitch:
        filename = f"preview_pitch{int(pitch[0])}_yaw{int(yaw if isinstance(yaw, float) else yaw[0])}.png"
    elif isinstance(yaw, list) and yaw:
        filename = f"preview_pitch{int(pitch if isinstance(pitch, float) else pitch[0])}_yaw{int(yaw[0])}.png"
    else:
        filename = None

    return HeavyPreviewResponse(
        success=response.success,
        image_bytes=image_bytes,
        image_path=image_path,
        filename=filename,
    )


@activity.defn(name="worker_submit_for_review")
async def submit_for_review_activity(
    params: HeavySubmitParams,
) -> BenchmarkToolResponse:
    """Execute review handover submission from a session bundle."""
    bundle_bytes = _decode_bundle(params.bundle_base64)
    script_path = params.script_path
    reviewer_stage = params.reviewer_stage
    session_id = params.session_id

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _extract_bundle(bundle_bytes, root)

        component = load_component_from_script(
            script_path=root / script_path,
            session_root=root,
        )

        failure_message: str | None = None
        try:
            success = await asyncio.to_thread(
                submit_for_review,
                component,
                cwd=root,
                session_id=session_id,
                reviewer_stage=reviewer_stage,
                episode_id=getattr(params, "episode_id", None),
                script_path=script_path,
            )
        except ValueError as exc:
            success = False
            failure_message = str(exc)

        return BenchmarkToolResponse(
            success=success,
            message=(
                "Handover complete"
                if success
                else (failure_message or "Handover failed")
            ),
            artifacts=_collect_submission_artifacts(root, session_id=session_id),
        )
