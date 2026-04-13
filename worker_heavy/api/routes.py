import asyncio
import base64
import contextlib
import gc
import tempfile
from pathlib import Path
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)

from shared.enums import (
    FailureReason,
)
from shared.models.simulation import (
    SimulationFailure,
)
from shared.rendering import (
    select_single_preview_render_subdir,
)
from shared.workers.loader import load_component_from_script
from shared.workers.persistence import (
    collect_and_cleanup_events,
)
from shared.workers.schema import (
    AnalyzeRequest,
    BenchmarkToolRequest,
    BenchmarkToolResponse,
    ElectronicsValidationRequest,
    PreviewDesignRequest,
    PreviewDesignResponse,
    PreviewRenderingType,
    SimulationArtifacts,
    VerificationRequest,
)
from shared.workers.workbench_models import WorkbenchResult
from worker_heavy.config import settings
from worker_heavy.runtime.simulation_runner import (
    cleanup_simulation_executor,
    run_simulation_in_isolated_process,
)
from worker_heavy.simulation.factory import close_all_session_backends
from worker_heavy.utils import renderer_client, submit_for_review
from worker_heavy.utils.topology import analyze_component
from worker_heavy.utils.verification import run_verification_job

logger = structlog.get_logger(__name__)
heavy_router = APIRouter()

# In heavy worker, we still need a way to access the filesystem
# This usually comes from the bundled session
from shared.workers.filesystem.router import create_filesystem_router


async def get_router(x_session_id: str = Header(...)):
    """Dependency to create a filesystem router for the current session."""
    try:
        from worker_heavy.config import settings

        return create_filesystem_router(
            session_id=x_session_id, base_dir=settings.sessions_dir
        )
    except Exception as e:
        logger.warning("router_creation_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to initialize filesystem")


def _collect_events(
    fs_router, root: Path | None = None, session_id: str | None = None
) -> list[dict[str, Any]]:
    """Read and delete events.jsonl from the workspace."""
    search_root = root or fs_router.local_backend.root
    return collect_and_cleanup_events(search_root, session_id=session_id)


def _normalize_render_paths(root: Path, render_paths: list[str]) -> list[str]:
    normalized: list[str] = []
    resolved_root = root.resolve()
    for raw_path in render_paths:
        try:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                normalized.append(str(candidate.resolve().relative_to(resolved_root)))
            else:
                normalized.append(str(candidate))
        except Exception:
            normalized.append(raw_path)
    return normalized


def _collect_render_payload_blobs(root: Path) -> dict[str, str]:
    render_blobs_base64: dict[str, str] = {}
    renders_dir = root / "renders"
    if not renders_dir.exists():
        return render_blobs_base64

    for render_path in sorted(renders_dir.rglob("*")):
        if not render_path.is_file():
            continue
        if render_path.name not in {
            "render_manifest.json",
            "render_index.jsonl",
            "preview_scene.json",
            "frames.jsonl",
            "objects.parquet",
        }:
            continue
        rel_path = str(render_path.relative_to(root))
        render_blobs_base64[rel_path] = base64.b64encode(
            render_path.read_bytes()
        ).decode("ascii")
    return render_blobs_base64


def _resolve_preview_rendering_type(
    request: PreviewDesignRequest,
    response: PreviewDesignResponse | None = None,
) -> PreviewRenderingType:
    if response is not None and response.rendering_type is not None:
        return response.rendering_type
    if request.rendering_type is not None:
        return request.rendering_type
    if request.rgb:
        return PreviewRenderingType.RGB
    if request.depth:
        return PreviewRenderingType.DEPTH
    return PreviewRenderingType.SEGMENTATION


@contextlib.contextmanager
def bundle_context(bundle_base64: str | None, default_root: Path):
    """Context manager to optionally extract a workspace bundle."""
    if not bundle_base64:
        yield default_root
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        try:
            bundle_bytes = base64.b64decode(bundle_base64)
            # Use system tar for robustness against metadata/comparison bugs
            import subprocess

            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tf:
                tf.write(bundle_bytes)
                tf_path = tf.name
            try:
                # -z: gzip, -x: extract, -f: file, -C: directory
                # --no-same-owner: avoid permission issues
                # --no-same-permissions: avoid permission issues
                subprocess.run(
                    ["tar", "-zxf", tf_path, "-C", str(tmp_root), "--no-same-owner"],
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

            logger.info(
                "bundle_extracted_via_system_tar", path=str(tmp_root), session_id=None
            )
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            logger.warning("bundle_extraction_failed", error=str(e), traceback=tb)
            raise HTTPException(
                status_code=400, detail=f"Failed to extract bundle: {e}"
            ) from e

        yield tmp_root


# Single-flight admission gate for external heavy jobs.
_HEAVY_ADMISSION_LOCK = asyncio.Lock()
_HEAVY_BUSY = False
_HEAVY_BUSY_CONTEXT: dict[str, str] = {}


def is_heavy_busy() -> bool:
    return _HEAVY_BUSY


def heavy_busy_context() -> dict[str, str]:
    return dict(_HEAVY_BUSY_CONTEXT)


def heavy_busy_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": "WORKER_BUSY",
        "message": "Heavy worker already has an active job",
        "active_job": heavy_busy_context(),
    }
    if settings.is_integration_test:
        active_job = payload.get("active_job")
        if isinstance(active_job, dict) and active_job.get("session_id"):
            payload["busy_session_id"] = active_job["session_id"]
    return payload


def _busy_detail() -> dict[str, Any]:
    return heavy_busy_payload()


@contextlib.asynccontextmanager
async def heavy_operation_admission(operation: str, session_id: str):
    global _HEAVY_BUSY, _HEAVY_BUSY_CONTEXT

    async with _HEAVY_ADMISSION_LOCK:
        if _HEAVY_BUSY:
            raise HTTPException(status_code=503, detail=_busy_detail())
        _HEAVY_BUSY = True
        _HEAVY_BUSY_CONTEXT = {
            "operation": operation,
            "session_id": session_id,
        }

    try:
        yield
    finally:
        async with _HEAVY_ADMISSION_LOCK:
            _HEAVY_BUSY = False
            _HEAVY_BUSY_CONTEXT = {}


async def run_simulation_task(
    script_path,
    root,
    script_content,
    smoke_test_mode,
    backend_type,
    x_session_id,
    episode_id,
    stream_render_frames,
    particle_budget,
):
    """Run simulation in an isolated child process (crash containment boundary)."""
    return await run_simulation_in_isolated_process(
        script_path=script_path,
        session_root=root,
        script_content=script_content,
        output_dir=root,
        smoke_test_mode=smoke_test_mode,
        backend=backend_type,
        session_id=x_session_id,
        episode_id=episode_id,
        stream_render_frames=stream_render_frames,
        particle_budget=particle_budget,
    )


@heavy_router.post("/benchmark/verify", response_model=BenchmarkToolResponse)
async def api_verify(
    request: VerificationRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Run batched runtime-randomization verification."""
    try:
        async with heavy_operation_admission("verify", x_session_id):
            with bundle_context(
                request.bundle_base64, fs_router.local_backend.root
            ) as root:
                return await run_verification_job(
                    root,
                    request,
                    session_id=x_session_id,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_benchmark_verify_failed", error=str(e))
        return BenchmarkToolResponse(
            success=False,
            message=str(e),
            artifacts=SimulationArtifacts(
                failure=SimulationFailure(
                    reason=FailureReason.VERIFICATION_ERROR, detail=str(e)
                )
            ),
        )


@heavy_router.post("/benchmark/simulate", response_model=BenchmarkToolResponse)
@heavy_router.post("/engineering/simulate", response_model=BenchmarkToolResponse)
async def api_simulate(
    request: BenchmarkToolRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Physics-backed stability check in isolated session."""
    try:
        from shared.simulation.schemas import SimulatorBackendType

        backend_type = request.backend
        if isinstance(backend_type, str):
            backend_type = SimulatorBackendType(backend_type)

        async with heavy_operation_admission("simulate", x_session_id):
            with bundle_context(
                request.bundle_base64, fs_router.local_backend.root
            ) as root:
                result = await run_simulation_task(
                    str(root / request.script_path)
                    if request.bundle_base64
                    else fs_router.local_backend._resolve(request.script_path),
                    root,
                    request.script_content,
                    request.smoke_test_mode,
                    backend_type,
                    x_session_id,
                    request.episode_id,
                    request.stream_render_frames,
                    request.particle_budget,
                )

                summary = result.summary

                events = _collect_events(fs_router, root=root, session_id=x_session_id)
                artifacts = SimulationArtifacts(
                    render_paths=_normalize_render_paths(root, result.render_paths),
                    object_store_keys=dict(result.render_object_store_keys),
                    mjcf_content=result.mjcf_content,
                    stress_summaries=result.stress_summaries,
                    fluid_metrics=result.fluid_metrics,
                    failure=result.failure,
                    total_cost=result.total_cost,
                    total_weight_g=result.total_weight_g,
                )
                sim_result_path = root / "simulation_result.json"
                if sim_result_path.exists():
                    artifacts.simulation_result_json = sim_result_path.read_text(
                        encoding="utf-8"
                    )
                render_blobs_base64: dict[str, str] = {}
                for rel_path in artifacts.render_paths:
                    render_path = root / rel_path
                    if not render_path.exists() or not render_path.is_file():
                        continue
                    suffix = render_path.suffix.lower()
                    if suffix not in {".png", ".jpg", ".jpeg", ".mp4", ".parquet"}:
                        continue
                    if rel_path in artifacts.object_store_keys and suffix == ".mp4":
                        continue
                    render_blobs_base64[rel_path] = base64.b64encode(
                        render_path.read_bytes()
                    ).decode("ascii")
                bundle_manifest_paths = {
                    str(Path(rel_path).parent / "render_manifest.json")
                    for rel_path in artifacts.render_paths
                    if Path(rel_path).suffix.lower()
                    in {".png", ".jpg", ".jpeg", ".mp4"}
                }
                for manifest_rel_path in sorted(bundle_manifest_paths):
                    manifest_path = root / manifest_rel_path
                    if not manifest_path.exists():
                        continue
                    render_blobs_base64[manifest_rel_path] = base64.b64encode(
                        manifest_path.read_bytes()
                    ).decode("ascii")
                render_manifest_path = root / "renders" / "render_manifest.json"
                if render_manifest_path.exists():
                    render_blobs_base64[
                        str(Path("renders") / "render_manifest.json")
                    ] = base64.b64encode(render_manifest_path.read_bytes()).decode(
                        "ascii"
                    )
                render_blobs_base64.update(_collect_render_payload_blobs(root))
                artifacts.render_blobs_base64 = render_blobs_base64
                return BenchmarkToolResponse(
                    success=result.success,
                    message=summary,
                    confidence=result.confidence,
                    artifacts=artifacts,
                    events=events,
                )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning("api_benchmark_simulate_validation_failed", error=str(e))
        return BenchmarkToolResponse(
            success=False,
            message=str(e),
            artifacts=SimulationArtifacts(
                failure=SimulationFailure(
                    reason=FailureReason.VALIDATION_FAILED, detail=str(e)
                )
            ),
        )
    except Exception as e:
        logger.warning("api_benchmark_simulate_failed", error=str(e))
        return BenchmarkToolResponse(
            success=False,
            message=str(e),
            artifacts=SimulationArtifacts(
                failure=SimulationFailure(
                    reason=FailureReason.PHYSICS_INSTABILITY, detail=str(e)
                )
            ),
        )


@heavy_router.post("/benchmark/validate_circuit", response_model=BenchmarkToolResponse)
async def api_validate_circuit(
    request: ElectronicsValidationRequest,
    x_session_id: str = Header(...),
):
    """Run SPICE validation on the provided electronics section."""
    try:
        async with heavy_operation_admission("validate_circuit", x_session_id):
            from shared.circuit_builder import build_circuit_from_section
            from shared.pyspice_utils import validate_circuit

            circuit = build_circuit_from_section(request.section)
            res = validate_circuit(
                circuit, request.section.power_supply, section=request.section
            )

            artifacts = SimulationArtifacts(
                circuit_validation_result=res.model_dump(),
            )
            if not res.valid:
                artifacts.failure = SimulationFailure(
                    reason=FailureReason.VALIDATION_FAILED,
                    detail="; ".join(res.errors),
                )

            return BenchmarkToolResponse(
                success=res.valid,
                message="; ".join(res.errors) if not res.valid else "Circuit is valid",
                artifacts=artifacts,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_validate_circuit_failed", error=str(e))
        return BenchmarkToolResponse(
            success=False,
            message=str(e),
            artifacts=SimulationArtifacts(
                failure=SimulationFailure(
                    reason=FailureReason.VALIDATION_FAILED, detail=str(e)
                )
            ),
        )


@heavy_router.post("/benchmark/analyze", response_model=WorkbenchResult)
async def api_analyze(
    request: AnalyzeRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Component analysis (topology, material, weight) in isolated session."""
    try:
        async with heavy_operation_admission("analyze", x_session_id):
            with bundle_context(
                request.bundle_base64, fs_router.local_backend.root
            ) as root:
                component = load_component_from_script(
                    script_path=root / request.script_path
                    if request.bundle_base64
                    else fs_router.local_backend._resolve(request.script_path),
                    session_root=root,
                    script_content=request.script_content,
                )
                return await asyncio.to_thread(
                    analyze_component,
                    component,
                    output_dir=root,
                    method=request.method,
                    quantity=request.quantity,
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_benchmark_analyze_failed", error=str(e))
        return WorkbenchResult(
            is_manufacturable=False, unit_cost=0.0, violations=[str(e)]
        )


@heavy_router.post(
    "/benchmark/render_cad",
    response_model=PreviewDesignResponse,
    response_model_exclude_none=True,
)
@heavy_router.post(
    "/benchmark/preview",
    response_model=PreviewDesignResponse,
    response_model_exclude_none=True,
    deprecated=True,
)
async def api_preview(
    request: PreviewDesignRequest,
    x_session_id: str = Header(...),
    x_agent_role: str | None = Header(default=None),
    fs_router=Depends(get_router),
):
    """Render a preview of the CAD design from specified camera angles."""
    try:
        async with heavy_operation_admission("preview", x_session_id):
            workspace_root = fs_router.local_backend.root
            resolved_rendering_type = _resolve_preview_rendering_type(request)
            logger.info(
                "worker_heavy_preview_started",
                session_id=x_session_id,
                script_path=request.script_path,
                agent_role=x_agent_role,
                rendering_type=resolved_rendering_type.value,
                orbit_pitch=request.orbit_pitch,
                orbit_yaw=request.orbit_yaw,
            )
            with bundle_context(request.bundle_base64, workspace_root):
                bundle_base64 = (
                    request.bundle_base64
                    or renderer_client.bundle_workspace_base64(workspace_root)
                )
                response = await asyncio.to_thread(
                    renderer_client.render_preview,
                    bundle_base64=bundle_base64,
                    script_path=request.script_path,
                    orbit_pitch=request.orbit_pitch,
                    orbit_yaw=request.orbit_yaw,
                    rendering_type=request.rendering_type,
                    session_id=x_session_id,
                    agent_role=x_agent_role,
                    script_content=request.script_content,
                )
                if not response.success:
                    raise RuntimeError(response.message)
                preview_renders_dir = (
                    workspace_root
                    / "renders"
                    / select_single_preview_render_subdir(
                        workspace_root, agent_role=x_agent_role
                    )
                )
                image_path = renderer_client.materialize_preview_response(
                    response, preview_renders_dir
                )
                if image_path is None:
                    raise RuntimeError("renderer returned no preview image")
                saved_render_dir = str(
                    image_path.parent.relative_to(workspace_root)
                ).replace("\\", "/")
                manifest_path = str(
                    image_path.parent.relative_to(workspace_root)
                    / "render_manifest.json"
                ).replace("\\", "/")
                preview_message = (
                    "Preview generated successfully. "
                    f"Saved renders to {saved_render_dir}. "
                    f"Manifest: {manifest_path}."
                )
                resolved_rendering_type = _resolve_preview_rendering_type(
                    request, response
                )

                logger.info(
                    "worker_heavy_preview_finished",
                    session_id=x_session_id,
                    artifact_path=str(image_path.relative_to(workspace_root)),
                    manifest_path=manifest_path,
                    rendering_type=resolved_rendering_type.value,
                )
                return PreviewDesignResponse(
                    success=response.success,
                    status_text="Preview generated successfully",
                    image_path=str(image_path.relative_to(workspace_root)),
                    artifact_path=str(image_path.relative_to(workspace_root)),
                    manifest_path=manifest_path,
                    rendering_type=resolved_rendering_type,
                    drafting=response.drafting or request.drafting,
                    pitch=request.orbit_pitch,
                    yaw=request.orbit_yaw,
                    image_bytes_base64=response.image_bytes_base64,
                    object_store_keys=response.object_store_keys,
                    render_manifest_json=response.render_manifest_json,
                    events=response.events,
                    message=preview_message,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_benchmark_preview_failed", error=str(e))
        return PreviewDesignResponse(
            success=False,
            message=str(e),
            status_text="Preview generation failed",
            rendering_type=_resolve_preview_rendering_type(request),
            drafting=request.drafting,
            pitch=request.orbit_pitch,
            yaw=request.orbit_yaw,
        )


@heavy_router.post("/benchmark/build", response_model=BenchmarkToolResponse)
async def api_build(
    request: PreviewDesignRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Rebuild simulation assets (GLB) from source without running full simulation."""
    try:
        async with heavy_operation_admission("build", x_session_id):
            with bundle_context(
                request.bundle_base64, fs_router.local_backend.root
            ) as root:
                component = load_component_from_script(
                    script_path=root / request.script_path
                    if request.bundle_base64
                    else fs_router.local_backend._resolve(request.script_path),
                    session_root=root,
                    script_content=request.script_content,
                )

                from worker_heavy.simulation.factory import get_simulation_builder

                builder = get_simulation_builder(root)

                scene_path = await asyncio.to_thread(
                    builder.build_from_assembly,
                    component,
                    smoke_test_mode=request.smoke_test_mode,
                )

                events = _collect_events(fs_router, root=root, session_id=x_session_id)
                return BenchmarkToolResponse(
                    success=True,
                    message=f"Assets rebuilt. Scene saved to {scene_path.name}",
                    artifacts=SimulationArtifacts(
                        scene_path=str(scene_path.relative_to(root))
                    ),
                    events=events,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_benchmark_build_failed", error=str(e))
        return BenchmarkToolResponse(success=False, message=str(e))


@heavy_router.post("/benchmark/submit", response_model=BenchmarkToolResponse)
@heavy_router.post("/engineering/submit", response_model=BenchmarkToolResponse)
async def api_submit(
    request: BenchmarkToolRequest,
    x_session_id: str = Header(...),
    fs_router=Depends(get_router),
):
    """Handover to reviewer in isolated session (moved to heavy due to DFM dependencies)."""
    try:
        async with heavy_operation_admission("submit", x_session_id):
            with bundle_context(
                request.bundle_base64, fs_router.local_backend.root
            ) as root:
                component = load_component_from_script(
                    script_path=root / request.script_path
                    if request.bundle_base64
                    else fs_router.local_backend._resolve(request.script_path),
                    session_root=root,
                    script_content=request.script_content,
                )
                reviewer_stage = request.reviewer_stage
                if reviewer_stage is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "reviewer_stage is required for the submit route. "
                            "Pass one of: benchmark_reviewer, "
                            "engineering_execution_reviewer, electronics_reviewer."
                        ),
                    )
                failure_message: str | None = None
                try:
                    success = submit_for_review(
                        component,
                        cwd=root,
                        session_id=x_session_id,
                        reviewer_stage=reviewer_stage,
                        episode_id=request.episode_id,
                        script_path=request.script_path,
                    )
                except ValueError as exc:
                    success = False
                    failure_message = str(exc)
                events = _collect_events(fs_router, root=root, session_id=x_session_id)
                artifacts = SimulationArtifacts()
                validation_result_path = root / "validation_results.json"
                if validation_result_path.exists():
                    artifacts.validation_results_json = (
                        validation_result_path.read_text(encoding="utf-8")
                    )
                sim_result_path = root / "simulation_result.json"
                if sim_result_path.exists():
                    artifacts.simulation_result_json = sim_result_path.read_text(
                        encoding="utf-8"
                    )
                stage_manifest_paths = (
                    ".manifests/benchmark_plan_review_manifest.json",
                    ".manifests/benchmark_review_manifest.json",
                    ".manifests/engineering_plan_review_manifest.json",
                    ".manifests/engineering_execution_handoff_manifest.json",
                    ".manifests/electronics_review_manifest.json",
                )
                review_manifests: dict[str, str] = {}
                for rel_path in stage_manifest_paths:
                    manifest_path = root / rel_path
                    if manifest_path.exists():
                        review_manifests[rel_path] = manifest_path.read_text(
                            encoding="utf-8"
                        )
                artifacts.review_manifests_json = review_manifests
                render_blobs_base64: dict[str, str] = {}
                renders_dir = root / "renders"
                if renders_dir.exists():
                    for render_path in sorted(renders_dir.rglob("*")):
                        if not render_path.is_file():
                            continue
                        if render_path.suffix.lower() not in {
                            ".png",
                            ".jpg",
                            ".jpeg",
                            ".mp4",
                        }:
                            continue
                        rel_path = str(render_path.relative_to(root))
                        artifacts.render_paths.append(rel_path)
                        render_blobs_base64[rel_path] = base64.b64encode(
                            render_path.read_bytes()
                        ).decode("ascii")
                bundle_manifest_paths = {
                    str(Path(rel_path).parent / "render_manifest.json")
                    for rel_path in artifacts.render_paths
                    if Path(rel_path).suffix.lower()
                    in {".png", ".jpg", ".jpeg", ".mp4"}
                }
                for manifest_rel_path in sorted(bundle_manifest_paths):
                    manifest_path = root / manifest_rel_path
                    if manifest_path.exists():
                        render_blobs_base64[manifest_rel_path] = base64.b64encode(
                            manifest_path.read_bytes()
                        ).decode("ascii")
                render_manifest_path = renders_dir / "render_manifest.json"
                if render_manifest_path.exists():
                    render_blobs_base64[
                        str(Path("renders") / "render_manifest.json")
                    ] = base64.b64encode(render_manifest_path.read_bytes()).decode(
                        "ascii"
                    )
                render_blobs_base64.update(_collect_render_payload_blobs(root))
                artifacts.render_blobs_base64 = render_blobs_base64
                return BenchmarkToolResponse(
                    success=success,
                    message=(
                        "Handover complete"
                        if success
                        else (failure_message or "Handover failed")
                    ),
                    artifacts=artifacts,
                    events=events,
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("api_benchmark_submit_failed", error=str(e))
        return BenchmarkToolResponse(success=False, message=str(e))


@heavy_router.post("/internal/simulation/cleanup")
async def api_simulation_cleanup():
    """
    Internal cleanup endpoint for integration teardown.

    Closes cached simulation backends in both the parent process and the
    persistent simulation child so long-lived worker processes do not keep
    session state across tests.
    """
    parent_closed_backends = close_all_session_backends()
    parent_gc_collected = gc.collect()
    child_cleanup = await cleanup_simulation_executor()
    return {
        "success": True,
        "closed_backends": parent_closed_backends + child_cleanup.child_closed_backends,
        "parent_closed_backends": parent_closed_backends,
        "parent_gc_collected": parent_gc_collected,
        "child_cleanup": {
            "had_executor": child_cleanup.had_executor,
            "child_closed_backends": child_cleanup.child_closed_backends,
            "child_gc_collected": child_cleanup.child_gc_collected,
            "executor_reset": child_cleanup.executor_reset,
        },
    }
