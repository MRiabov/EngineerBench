import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import APIRouter, Header, Request
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from controller.clients.worker import WorkerClient
from controller.config.settings import settings
from controller.middleware.remote_fs import RemoteFilesystemMiddleware
from controller.utils import EpisodeIdentity
from shared.enums import AgentName, SimulationConfidence
from shared.logging import bind_log_context
from shared.script_contracts import authored_script_path_for_agent
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.simulation.smoke_mode import (
    ensure_smoke_test_mode_allowed,
    resolve_default_smoke_test_mode,
)
from shared.workers.schema import (
    BenchmarkToolResponse,
    PreviewDesignResponse,
    PreviewRenderingType,
    SimulationArtifacts,
)

router = APIRouter(prefix="/script-tools", tags=["script-tools"])


class ScriptToolRequest(BaseModel):
    script_path: Path = Field(default=Path("script.py"))
    agent_role: AgentName = Field(default=AgentName.ENGINEER_CODER)
    backend: SimulatorBackendType = Field(default_factory=get_default_simulator_backend)
    smoke_test_mode: bool | None = None
    bundle_base64: str | None = None
    orbit_pitch: float | list[float] = Field(
        default=-45.0,
        validation_alias=AliasChoices("pitch", "orbit_pitch"),
    )
    orbit_yaw: float | list[float] = Field(
        default=45.0,
        validation_alias=AliasChoices("yaw", "orbit_yaw"),
    )
    rgb: bool | None = None
    depth: bool | None = None
    segmentation: bool | None = None
    payload_path: bool = False
    rendering_type: PreviewRenderingType | None = None
    reviewer_stage: AgentName | None = None
    jitter_range: tuple[float, float, float] | None = None
    num_scenes: int | None = None
    duration: float | None = None
    seed: int | None = None
    episode_id: str | None = None
    stream_render_frames: bool = False

    @field_validator("smoke_test_mode", mode="after")
    @classmethod
    def validate_smoke_test_mode(cls, value: bool | None) -> bool | None:
        return ensure_smoke_test_mode_allowed(value)

    @model_validator(mode="after")
    def normalize_script_path(self) -> "ScriptToolRequest":
        if self.script_path == Path("script.py"):
            self.script_path = authored_script_path_for_agent(self.agent_role)
        return self


@asynccontextmanager
async def _controller_script_middleware(
    session_id: str, agent_role: AgentName, request: Request, episode_id: str | None
):
    identity = EpisodeIdentity.from_context(
        session_id=session_id, episode_id=episode_id
    )
    async with httpx.AsyncClient() as http_client:
        client = WorkerClient(
            base_url=settings.worker_light_url,
            session_id=session_id,
            http_client=http_client,
            heavy_url=settings.worker_heavy_url,
            controller_url="",
            agent_role=agent_role,
            light_transport=settings.worker_light_transport,
        )
        middleware = RemoteFilesystemMiddleware(
            client,
            agent_role=agent_role,
            episode_id=str(identity.episode_id),
        )
        yield middleware


async def _retry_busy(callable_):
    delay = 1.5
    max_attempts = 10
    for attempt in range(1, max_attempts + 1):
        try:
            return await callable_()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 503 or attempt == max_attempts:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)


async def _collect_render_blobs(
    middleware: RemoteFilesystemMiddleware, render_paths: list[str]
) -> dict[str, str]:
    render_blobs_base64: dict[str, str] = {}
    manifest_candidates: list[str] = []
    render_image_paths: list[str] = []
    requested_paths: list[str] = []

    for raw_path in render_paths:
        rel_path = str(Path(raw_path))
        suffix = Path(rel_path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".mp4"}:
            continue

        manifest_path = str(Path(rel_path).parent / "render_manifest.json")
        if manifest_path not in manifest_candidates:
            manifest_candidates.append(manifest_path)
        if rel_path not in requested_paths:
            requested_paths.append(rel_path)

        if suffix in {".png", ".jpg", ".jpeg"}:
            render_image_paths.append(rel_path)

    for manifest_path in manifest_candidates:
        if manifest_path not in requested_paths:
            requested_paths.append(manifest_path)

    if requested_paths:
        file_blobs = await middleware.client.read_files_binary(requested_paths)
        for rel_path, blob in file_blobs.items():
            render_blobs_base64[rel_path] = base64.b64encode(blob).decode("ascii")

    manifest_found = any(path in render_blobs_base64 for path in manifest_candidates)

    if render_image_paths and not manifest_found:
        raise ValueError(
            "bundle-local render_manifest.json missing for latest render bundle"
        )

    if render_image_paths and not any(
        path.endswith("render_manifest.json") for path in render_blobs_base64
    ):
        raise ValueError(
            "bundle-local render_manifest.json missing for latest render bundle"
        )

    return render_blobs_base64


@router.post("/validate", response_model=BenchmarkToolResponse)
async def validate_script(
    request: Request,
    payload: ScriptToolRequest,
    x_session_id: str = Header(...),
):
    identity = EpisodeIdentity.from_context(
        session_id=x_session_id, episode_id=payload.episode_id
    )
    with bind_log_context(
        session_id=identity.session_id,
        episode_id=str(identity.episode_id),
        agent_role=payload.agent_role.value,
        stage=(payload.reviewer_stage or payload.agent_role).value,
    ):
        async with _controller_script_middleware(
            x_session_id, payload.agent_role, request, payload.episode_id
        ) as middleware:
            result = await middleware.validate(
                payload.script_path, bundle_base64=payload.bundle_base64
            )
            await middleware.client._sync_handover_artifacts_to_light(result)
            return result


@router.post("/simulate", response_model=BenchmarkToolResponse)
async def simulate_script(
    request: Request,
    payload: ScriptToolRequest,
    x_session_id: str = Header(...),
):
    identity = EpisodeIdentity.from_context(
        session_id=x_session_id, episode_id=payload.episode_id
    )
    with bind_log_context(
        session_id=identity.session_id,
        episode_id=str(identity.episode_id),
        agent_role=payload.agent_role.value,
        stage=(payload.reviewer_stage or payload.agent_role).value,
    ):
        ensure_smoke_test_mode_allowed(
            payload.smoke_test_mode,
            integration_enabled=settings.is_integration_test,
        )
        async with _controller_script_middleware(
            x_session_id, payload.agent_role, request, payload.episode_id
        ) as middleware:
            result = await middleware.simulate(
                payload.script_path,
                backend=payload.backend,
                smoke_test_mode=payload.smoke_test_mode,
                stream_render_frames=payload.stream_render_frames,
                bundle_base64=payload.bundle_base64,
            )
            if isinstance(result, BenchmarkToolResponse):
                await middleware.client._sync_handover_artifacts_to_light(result)
                return result
            response = BenchmarkToolResponse(
                success=result.success,
                message=result.summary,
                confidence=getattr(result, "confidence", SimulationConfidence.HIGH),
                artifacts=SimulationArtifacts(
                    render_paths=list(getattr(result, "render_paths", [])),
                    simulation_result_json=result.model_dump_json(),
                    total_cost=getattr(result, "total_cost", None),
                    total_weight_g=getattr(result, "total_weight_g", None),
                ),
            )
            if response.artifacts:
                response.artifacts.render_blobs_base64 = await _collect_render_blobs(
                    middleware,
                    response.artifacts.render_paths,
                )
            await middleware.client._sync_handover_artifacts_to_light(response)
            return response


@router.post("/verify", response_model=BenchmarkToolResponse)
async def verify_script(
    request: Request,
    payload: ScriptToolRequest,
    x_session_id: str = Header(...),
):
    identity = EpisodeIdentity.from_context(
        session_id=x_session_id, episode_id=payload.episode_id
    )
    with bind_log_context(
        session_id=identity.session_id,
        episode_id=str(identity.episode_id),
        agent_role=payload.agent_role.value,
        stage=(payload.reviewer_stage or payload.agent_role).value,
    ):
        smoke_test_mode = payload.smoke_test_mode
        if smoke_test_mode is None:
            smoke_test_mode = resolve_default_smoke_test_mode(
                integration_enabled=settings.is_integration_test
            )
        else:
            ensure_smoke_test_mode_allowed(
                smoke_test_mode,
                integration_enabled=settings.is_integration_test,
            )
        async with _controller_script_middleware(
            x_session_id, payload.agent_role, request, payload.episode_id
        ) as middleware:
            num_scenes = payload.num_scenes
            duration = payload.duration
            if smoke_test_mode and num_scenes is None:
                num_scenes = 1
            if smoke_test_mode and duration is None:
                duration = 1.0
            result = await _retry_busy(
                lambda: middleware.verify(
                    payload.script_path,
                    backend=payload.backend,
                    smoke_test_mode=smoke_test_mode,
                    jitter_range=payload.jitter_range,
                    num_scenes=num_scenes,
                    duration=duration,
                    seed=payload.seed,
                )
            )
            if isinstance(result, BenchmarkToolResponse):
                await middleware.client._sync_handover_artifacts_to_light(result)
                return result
            response = BenchmarkToolResponse(
                success=result.success,
                message=result.message,
                confidence=getattr(result, "confidence", SimulationConfidence.HIGH),
                artifacts=getattr(result, "artifacts", None),
            )
            await middleware.client._sync_handover_artifacts_to_light(response)
            return response


@router.post("/preview", response_model=PreviewDesignResponse)
async def preview_script(
    request: Request,
    payload: ScriptToolRequest,
    x_session_id: str = Header(...),
):
    identity = EpisodeIdentity.from_context(
        session_id=x_session_id, episode_id=payload.episode_id
    )
    with bind_log_context(
        session_id=identity.session_id,
        episode_id=str(identity.episode_id),
        agent_role=payload.agent_role.value,
        stage=(payload.reviewer_stage or payload.agent_role).value,
    ):
        async with _controller_script_middleware(
            x_session_id, payload.agent_role, request, payload.episode_id
        ) as middleware:
            result = await middleware.render_cad(
                payload.script_path,
                orbit_pitch=payload.orbit_pitch,
                orbit_yaw=payload.orbit_yaw,
                rgb=payload.rgb,
                depth=payload.depth,
                segmentation=payload.segmentation,
                payload_path=payload.payload_path,
                rendering_type=payload.rendering_type,
                bundle_base64=payload.bundle_base64,
                smoke_test_mode=payload.smoke_test_mode,
            )
            return result


@router.post("/submit", response_model=BenchmarkToolResponse)
async def submit_script(
    request: Request,
    payload: ScriptToolRequest,
    x_session_id: str = Header(...),
):
    identity = EpisodeIdentity.from_context(
        session_id=x_session_id, episode_id=payload.episode_id
    )
    with bind_log_context(
        session_id=identity.session_id,
        episode_id=str(identity.episode_id),
        agent_role=payload.agent_role.value,
        stage=(payload.reviewer_stage or payload.agent_role).value,
    ):
        async with _controller_script_middleware(
            x_session_id, payload.agent_role, request, payload.episode_id
        ) as middleware:
            result = await _retry_busy(
                lambda: middleware.submit(
                    payload.script_path,
                    reviewer_stage=payload.reviewer_stage,
                    bundle_base64=payload.bundle_base64,
                )
            )
            if isinstance(result, BenchmarkToolResponse):
                await middleware.client._sync_handover_artifacts_to_light(result)
                return result
            response = BenchmarkToolResponse(
                success=result.success,
                message=result.message or "Submission completed",
                confidence=getattr(result, "confidence", "high"),
                artifacts=getattr(result, "artifacts", None),
            )
            await middleware.client._sync_handover_artifacts_to_light(response)
            return response
