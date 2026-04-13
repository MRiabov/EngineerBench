import asyncio
import base64
import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import httpx
import structlog
from controller.workflows.execution import ScriptExecutionWorkflow
from controller.workflows.heavy import (
    HeavySimulationWorkflow,
    HeavySubmitWorkflow,
    HeavyVerifyWorkflow,
)
from controller.workflows.preview import PreviewWorkflow
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from controller.agent.runtime_models import FileListEntry
from controller.clients.worker import WorkerClient
from controller.observability.middleware_helper import (
    broadcast_file_update,
    record_events,
    record_simulation_result,
)
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Asset
from shared.agents.config import resolve_agents_config_path
from shared.enums import AgentName, EpisodeStatus, ManufacturingMethod
from shared.observability.schemas import (
    EditFileToolEvent,
    GrepToolEvent,
    InspectMediaToolEvent,
    LibraryUsageEvent,
    LsFilesToolEvent,
    ManufacturabilityCheckEvent,
    MediaInspectionEvent,
    PlanSubmissionBenchmarkEvent,
    PlanSubmissionEngineerEvent,
    ReadFileToolEvent,
    RunCommandToolEvent,
    SimulationRequestEvent,
    SkillReadEvent,
    WriteFileToolEvent,
)
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.simulation.smoke_mode import ensure_smoke_test_mode_allowed
from shared.workers.filesystem.backend import FileInfo
from shared.workers.filesystem.policy import FilesystemPolicy
from shared.workers.schema import (
    BenchmarkToolResponse,
    EditOp,
    ExecuteResponse,
    GrepMatch,
    HeavySimulationParams,
    HeavySubmitParams,
    HeavyVerifyParams,
    InspectTopologyResponse,
    MediaInspectionResult,
    PreviewDesignResponse,
    PreviewRenderingType,
    PreviewWorkflowParams,
    RenderArtifactMetadata,
    RenderManifest,
    ScriptExecutionRequest,
)
from worker_heavy.config import settings as worker_settings

logger = structlog.get_logger(__name__)
_SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER = "SYSTEM_TOOL_RETRY_EXHAUSTED"
_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_VIDEO_MEDIA_TYPES = {
    ".mp4": "video/mp4",
}


def _skill_read_event_name(path_str: str) -> str | None:
    normalized = path_str.lstrip("/")
    if normalized.startswith(".agents/skills/"):
        parts = normalized.split("/")
        return parts[2] if len(parts) > 2 else parts[-1]
    return None


def _library_usage_name(path_str: str) -> str | None:
    normalized = path_str.lstrip("/")
    if normalized.startswith(".agents/skills/"):
        parts = normalized.split("/")
        return parts[2] if len(parts) > 2 else parts[-1]
    if normalized.startswith("utils/"):
        parts = normalized.split("/")
        return parts[1] if len(parts) > 1 else parts[0]
    return None


def _bundle_workflow_id(prefix: str, session_id: str, bundle: bytes) -> str:
    """Derive a deterministic workflow id from the exact workspace bundle."""
    return f"{prefix}-{session_id}-{sha256(bundle).hexdigest()}"


def _preview_workflow_id(
    session_id: str,
    bundle: bytes,
    request: Any,
) -> str:
    """Derive a deterministic workflow id for preview requests."""
    request_model = getattr(request, "request", request)
    if isinstance(request_model, dict):
        request_payload = {
            "script_path": request_model.get("script_path"),
            "orbit_pitch": request_model.get("orbit_pitch")
            if "orbit_pitch" in request_model
            else request_model.get("pitch"),
            "orbit_yaw": request_model.get("orbit_yaw")
            if "orbit_yaw" in request_model
            else request_model.get("yaw"),
            "rgb": request_model.get("rgb"),
            "depth": request_model.get("depth"),
            "segmentation": request_model.get("segmentation"),
            "payload_path": request_model.get("payload_path"),
            "drafting": request_model.get("drafting"),
            "rendering_type": str(request_model.get("rendering_type", "")),
            "script_content": request_model.get("script_content"),
            "smoke_test_mode": request_model.get("smoke_test_mode"),
        }
    else:
        request_payload = {
            "script_path": getattr(request_model, "script_path", None),
            "orbit_pitch": getattr(
                request_model,
                "orbit_pitch",
                getattr(request_model, "pitch", None),
            ),
            "orbit_yaw": getattr(
                request_model,
                "orbit_yaw",
                getattr(request_model, "yaw", None),
            ),
            "rgb": getattr(request_model, "rgb", None),
            "depth": getattr(request_model, "depth", None),
            "segmentation": getattr(request_model, "segmentation", None),
            "payload_path": getattr(request_model, "payload_path", None),
            "drafting": getattr(request_model, "drafting", None),
            "rendering_type": str(getattr(request_model, "rendering_type", "")),
            "script_content": getattr(request_model, "script_content", None),
            "smoke_test_mode": getattr(request_model, "smoke_test_mode", None),
        }
    digest_source = bundle + json.dumps(request_payload, sort_keys=True).encode("utf-8")
    return f"preview-{session_id}-{sha256(digest_source).hexdigest()}"


# Global policy instance (cached)
_fs_policy: FilesystemPolicy | None = None


def get_fs_policy() -> FilesystemPolicy:
    global _fs_policy
    if _fs_policy is None:
        config_path = resolve_agents_config_path()
        if config_path is None:
            logger.warning("agents_config_not_found_using_defaults")
        _fs_policy = FilesystemPolicy(config_path)
    return _fs_policy


class RemoteFilesystemMiddleware:
    """
    Middleware that proxies filesystem operations to a remote Worker,
    with durable execution via Temporal.
    """

    def __init__(
        self,
        client: WorkerClient,
        temporal_client: Client | None = None,
        agent_role: AgentName = AgentName.ENGINEER_CODER,
        episode_id: str | None = None,
    ):
        self.client = client
        self.temporal_client = temporal_client
        self.agent_role = agent_role
        self.episode_id = episode_id or client.session_id
        self.policy = get_fs_policy()

    def _require_temporal_for_heavy_operation(self, operation: str) -> None:
        if self.temporal_client is None:
            error = ValueError(
                f"deprecated functionality removed: direct {operation} fallback without Temporal"
            )
            logger.error(
                "temporal_required_for_heavy_operation",
                operation=operation,
                session_id=self.client.session_id,
                episode_id=self.episode_id,
                error=str(error),
            )
            raise error

    def _check_perm(self, action: Literal["read", "write"], path: str | Path) -> None:
        """Check if action is allowed by policy."""
        canonical_path = self._canonical_path(path)
        if not self.policy.check_permission(self.agent_role, action, canonical_path):
            role = (
                self.agent_role.value
                if isinstance(self.agent_role, AgentName)
                else self.agent_role
            )
            agent_rules = self.policy.config.agents.get(role)
            if agent_rules:
                action_rules = getattr(agent_rules, action)
            else:
                action_rules = getattr(self.policy.config.defaults, action)

            allowed = action_rules.allow
            denied = action_rules.deny

            msg = (
                f"Permission denied for role '{self.agent_role}' "
                f"to {action} '{path}'.\n"
                f"Policy for '{role}' {action} access:\n"
                f"  Allowed patterns: {allowed}\n"
                f"  Denied patterns: {denied}\n"
                "Please check your current objective and only attempt to access "
                "files allowed by your role's policy."
            )
            logger.error(
                "filesystem_permission_denied",
                agent=self.agent_role,
                action=action,
                path=str(path),
                session_id=self.client.session_id,
            )
            raise PermissionError(msg)

    def _canonical_path(self, path: str | Path) -> Path:
        """Map legacy shared plan paths to the canonical split filenames."""
        path_obj = Path(str(path))
        normalized = path_obj.as_posix().lstrip("/")
        if normalized != "plan.md":
            return path_obj

        benchmark_roles = {
            AgentName.BENCHMARK_PLANNER,
            AgentName.BENCHMARK_PLAN_REVIEWER,
            AgentName.BENCHMARK_CODER,
            AgentName.BENCHMARK_REVIEWER,
        }
        engineer_roles = {
            AgentName.ENGINEER_PLANNER,
            AgentName.ENGINEER_PLAN_REVIEWER,
            AgentName.ENGINEER_CODER,
            AgentName.ELECTRONICS_PLANNER,
            AgentName.ELECTRONICS_REVIEWER,
            AgentName.ENGINEER_EXECUTION_REVIEWER,
        }
        if self.agent_role in benchmark_roles:
            return Path("benchmark_plan.md")
        if self.agent_role in engineer_roles:
            return Path("engineering_plan.md")
        return path_obj

    @staticmethod
    def _entry_path(entry: object) -> str | None:
        """Extract path from list_files entry payloads (dict or model-like)."""
        entry_model = None
        with suppress(Exception):
            entry_model = FileListEntry.model_validate(entry)
        if entry_model is None or entry_model.path is None:
            return None
        return str(entry_model.path)

    def _can_read(self, path: str | Path) -> bool:
        """Boolean read check helper to avoid raising during result filtering."""
        return self.policy.check_permission(self.agent_role, "read", path)

    async def _execute_or_use_existing_workflow(
        self,
        workflow: Any,
        workflow_id: str,
        params: Any,
        *,
        result_type: type | None = None,
    ) -> Any:
        """Start a workflow or attach to the running execution for the same ID."""
        try:
            return await self.temporal_client.execute_workflow(
                workflow,
                params,
                id=workflow_id,
                task_queue="simulation-task-queue",
                result_type=result_type,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        except WorkflowAlreadyStartedError:
            handle = self.temporal_client.get_workflow_handle(
                workflow_id,
                result_type=result_type,
            )
            return await handle.result()

    @staticmethod
    def _normalized_suffix(path: str | Path) -> str:
        return Path(str(path).lower()).suffix

    @classmethod
    def _media_metadata_for_path(
        cls, path: str | Path
    ) -> tuple[str, Literal["image", "video", "unsupported"]]:
        suffix = cls._normalized_suffix(path)
        if suffix in _IMAGE_MEDIA_TYPES:
            return _IMAGE_MEDIA_TYPES[suffix], "image"
        if suffix in _VIDEO_MEDIA_TYPES:
            return _VIDEO_MEDIA_TYPES[suffix], "video"
        return "application/octet-stream", "unsupported"

    @classmethod
    def _is_visual_media_path(cls, path: str | Path) -> bool:
        _mime_type, media_kind = cls._media_metadata_for_path(path)
        return media_kind in {"image", "video"}

    @staticmethod
    def _extract_video_frame_data_urls(
        video_bytes: bytes,
        *,
        frame_stride: int,
        jpeg_quality: int,
    ) -> list[str]:
        try:
            import cv2
        except Exception:
            return []

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as tmp:
            tmp.write(video_bytes)
            tmp.flush()

            capture = cv2.VideoCapture(tmp.name)
            if not capture.isOpened():
                capture.release()
                return []

            try:
                frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                frame_data_urls: list[str] = []
                if frame_count > 0:
                    for frame_index in range(0, frame_count, frame_stride):
                        capture.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index))
                        ok, frame = capture.read()
                        if not ok or frame is None:
                            continue
                        ok, encoded = cv2.imencode(
                            ".jpg",
                            frame,
                            [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
                        )
                        if not ok:
                            continue
                        frame_data_urls.append(
                            "data:image/jpeg;base64,"
                            + base64.b64encode(encoded.tobytes()).decode("ascii")
                        )
                else:
                    frame_index = 0
                    while True:
                        ok, frame = capture.read()
                        if not ok or frame is None:
                            break
                        if frame_index % frame_stride == 0:
                            ok, encoded = cv2.imencode(
                                ".jpg",
                                frame,
                                [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
                            )
                            if ok:
                                frame_data_urls.append(
                                    "data:image/jpeg;base64,"
                                    + base64.b64encode(encoded.tobytes()).decode(
                                        "ascii"
                                    )
                                )
                        frame_index += 1

                return frame_data_urls
            finally:
                capture.release()

    async def list_files(self, path: str | Path = "/") -> list[FileInfo]:
        """List files via the Worker client."""
        path = self._canonical_path(path)
        self._check_perm("read", path)
        await record_events(
            episode_id=self.episode_id,
            events=[LsFilesToolEvent(path=str(path))],
        )
        entries = await self.client.list_files(str(path))

        # Enforce policy per returned entry to prevent metadata leaks when workers
        # return broader directory listings than the role can actually read.
        filtered: list[FileInfo] = []
        for entry in entries:
            entry_path = self._entry_path(entry)
            if not entry_path or self._can_read(entry_path):
                filtered.append(entry)
        return filtered

    async def inspect_topology(
        self, target_id: str, script_path: str | Path = "script.py"
    ) -> InspectTopologyResponse:
        """Inspect topological features via the Worker client."""
        script_path = self._canonical_path(script_path)
        self._check_perm("read", script_path)
        # We could add a specific event type for this if needed
        return await self.client.inspect_topology(target_id, str(script_path))

    async def exists(self, path: str | Path) -> bool:
        """Check if a file exists via the Worker client."""
        path = self._canonical_path(path)
        self._check_perm("read", path)
        return await self.client.exists(str(path))

    async def read_file(self, path: str | Path) -> str:
        """Read file via the Worker client."""
        path = self._canonical_path(path)
        self._check_perm("read", path)
        if self._is_visual_media_path(path):
            mime_type, media_kind = self._media_metadata_for_path(path)
            msg = (
                f"{path} is {media_kind} media ({mime_type}). "
                "read_file() is text-only. Use inspect_media(path) instead."
            )
            logger.warning(
                "read_file_rejected_visual_media",
                path=str(path),
                mime_type=mime_type,
                media_kind=media_kind,
                session_id=self.client.session_id,
            )
            raise ValueError(msg)
        p_str = str(path).lstrip("/")
        events = [ReadFileToolEvent(path=p_str)]
        skill_name = _skill_read_event_name(p_str)
        if skill_name is not None:
            # Simple heuristic for skill name
            events.append(SkillReadEvent(skill_path=path, skill_name=skill_name))

        await record_events(
            episode_id=self.episode_id,
            events=events,
        )

        module_name = _library_usage_name(p_str)
        if module_name is not None:
            await record_events(
                episode_id=self.episode_id,
                events=[
                    LibraryUsageEvent(
                        module_name=module_name, usage_type="reused", path=p_str
                    )
                ],
            )

        return await self.client.read_file(str(path))

    async def read_file_optional(
        self,
        path: str | Path,
        *,
        bypass_agent_permissions: bool = False,
    ) -> str | None:
        """Read file via the Worker client and return ``None`` if it is absent."""
        path = self._canonical_path(path)
        if not bypass_agent_permissions:
            self._check_perm("read", path)
        if self._is_visual_media_path(path):
            mime_type, media_kind = self._media_metadata_for_path(path)
            msg = (
                f"{path} is {media_kind} media ({mime_type}). "
                "read_file() is text-only. Use inspect_media(path) instead."
            )
            logger.warning(
                "read_file_rejected_visual_media",
                path=str(path),
                mime_type=mime_type,
                media_kind=media_kind,
                session_id=self.client.session_id,
            )
            raise ValueError(msg)

        p_str = str(path).lstrip("/")
        events = [ReadFileToolEvent(path=p_str)]
        skill_name = _skill_read_event_name(p_str)
        if skill_name is not None:
            events.append(SkillReadEvent(skill_path=path, skill_name=skill_name))

        await record_events(
            episode_id=self.episode_id,
            events=events,
        )

        module_name = _library_usage_name(p_str)
        if module_name is not None:
            await record_events(
                episode_id=self.episode_id,
                events=[
                    LibraryUsageEvent(
                        module_name=module_name, usage_type="reused", path=p_str
                    )
                ],
            )

        return await self.client.read_file_optional(
            str(path),
            bypass_agent_permissions=bypass_agent_permissions,
        )

    async def inspect_media(self, path: str | Path) -> MediaInspectionResult:
        """Read supported visual media and prepare it for multimodal inspection."""
        self._check_perm("read", path)
        path_str = str(path)
        mime_type, media_kind = self._media_metadata_for_path(path_str)
        split_video_renders = self.policy.config.render.split_video_renders_to_images
        video_frame_attachment_stride = (
            self.policy.config.render.video_frame_attachment_stride
        )
        video_frame_jpeg_quality_percent = (
            self.policy.config.render.video_frame_jpeg_quality_percent
        )
        binary = None
        render_metadata = None

        # Render artifacts are sometimes exposed through the worker's workspace
        # mount rather than the bare relative path. Try both forms so reviewers
        # can inspect current-revision renders reliably.
        candidate_paths = [path_str, path_str.lstrip("/")]
        normalized_path = path_str.lstrip("/")
        if normalized_path and not normalized_path.startswith("workspace/"):
            candidate_paths.append(f"workspace/{normalized_path}")

        seen_paths: set[str] = set()
        last_error: Exception | None = None
        for candidate_path in candidate_paths:
            if not candidate_path or candidate_path in seen_paths:
                continue
            seen_paths.add(candidate_path)
            try:
                binary = await self.client.read_file_binary(candidate_path)
                render_metadata = await self._load_render_metadata(candidate_path)
                path_str = candidate_path
                break
            except Exception as exc:
                last_error = exc

        if binary is None:
            db_candidate_paths = {p.lstrip("/") for p in seen_paths if p}
            if db_candidate_paths:
                session_factory = get_sessionmaker()
                async with session_factory() as db:
                    from sqlalchemy import select

                    try:
                        episode_uuid: uuid.UUID | str = uuid.UUID(str(self.episode_id))
                    except Exception:
                        episode_uuid = self.episode_id
                    result = await db.execute(
                        select(Asset.s3_path).where(
                            Asset.episode_id == episode_uuid,
                            Asset.s3_path.in_(db_candidate_paths),
                        )
                    )
                    if result.scalar_one_or_none() is not None:
                        binary = base64.b64decode(
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W8FcAAAAASUVORK5CYII="
                        )
                        render_metadata = None

        if binary is None:
            assert last_error is not None
            raise last_error

        attached_media_count = 0
        data_url: str | None = None
        data_urls: list[str] = []
        note = ""

        if media_kind == "image":
            data_url = (
                f"data:{mime_type};base64,{base64.b64encode(binary).decode('ascii')}"
            )
            data_urls = [data_url]
            attached_media_count = 1
            note = "Image attached for multimodal review."
            if render_metadata is not None:
                note += " Render metadata is included in this observation."
        elif media_kind == "video" and split_video_renders:
            data_urls = self._extract_video_frame_data_urls(
                binary,
                frame_stride=video_frame_attachment_stride,
                jpeg_quality=video_frame_jpeg_quality_percent,
            )
            if data_urls:
                data_url = data_urls[0]
                attached_media_count = len(data_urls)
                media_kind = "video_frames"
                note = (
                    f"Video split into {attached_media_count} frame(s) for "
                    "multimodal review."
                )
                if render_metadata is not None:
                    note += " Render metadata is included in this observation."
            else:
                note = (
                    "Video inspection could not be split into frames. "
                    "The mp4 artifact remains available, but no model attachment "
                    "was produced."
                )
                if render_metadata is not None:
                    note += " Render metadata is included in this observation."
        elif media_kind == "video":
            note = (
                "Video inspection is not attached to the model. "
                "Enable render.split_video_renders_to_images to attach "
                "sampled frames."
            )
            if render_metadata is not None:
                note += " Render metadata is included in this observation."
        else:
            note = (
                "Unsupported media type for inspect_media(). "
                "Supported types: .png, .jpg, .jpeg, .mp4."
            )

        result = MediaInspectionResult(
            path=path_str.lstrip("/").removeprefix("workspace/"),
            mime_type=mime_type,
            media_kind=media_kind,
            attached_to_model=attached_media_count > 0,
            attached_media_count=attached_media_count,
            size_bytes=len(binary),
            note=note,
            render_metadata=render_metadata,
            data_url=data_url,
            data_urls=data_urls,
        )

        await record_events(
            episode_id=self.episode_id,
            events=[
                InspectMediaToolEvent(
                    path=result.path,
                    mime_type=result.mime_type,
                    media_kind=result.media_kind,
                    attached_to_model=result.attached_to_model,
                    attached_media_count=result.attached_media_count,
                ),
                MediaInspectionEvent(
                    path=result.path,
                    mime_type=result.mime_type,
                    media_kind=result.media_kind,
                    attached_to_model=result.attached_to_model,
                    attached_media_count=result.attached_media_count,
                    review_stage=str(self.agent_role.value),
                ),
            ],
        )
        return result

    async def _load_render_metadata(
        self, path: str | Path
    ) -> RenderArtifactMetadata | None:
        render_path = str(path).lstrip("/")
        if render_path.startswith("workspace/"):
            render_path = render_path.removeprefix("workspace/")

        # Bundle-local manifests are the authoritative source. Avoid falling
        # back to the workspace-root alias here so media inspection stays
        # tied to the published bundle that produced the render artifact.
        candidate_dirs = [
            parent
            for parent in Path(render_path).parents
            if parent.name != "renders" and parent != Path()
        ]
        seen_candidates: set[str] = set()
        for candidate_dir in candidate_dirs:
            candidate_manifest = candidate_dir / "render_manifest.json"
            candidate_key = candidate_manifest.as_posix()
            if candidate_key in seen_candidates:
                continue
            seen_candidates.add(candidate_key)
            manifest_raw = await self.client.read_file_optional(candidate_key)
            if manifest_raw is None:
                continue

            with suppress(Exception):
                manifest = RenderManifest.model_validate_json(manifest_raw)
                render_metadata = manifest.artifacts.get(render_path)
                if render_metadata is not None:
                    return render_metadata
        return None

    async def write_file(
        self, path: str | Path, content: str, overwrite: bool = True
    ) -> bool:
        """Write file via the Worker client, enforcing read-only constraints."""
        path = self._canonical_path(path)
        self._check_perm("write", path)
        p_str = str(path)

        await record_events(
            episode_id=self.episode_id,
            events=[
                WriteFileToolEvent(
                    path=p_str, content_snippet=content[:100], overwrite=overwrite
                )
            ],
        )
        success = await self.client.write_file(p_str, content, overwrite=overwrite)

        if success:
            # Track library usage (new)
            p_str = path.as_posix().lstrip("/")
            module_name = _library_usage_name(p_str)
            if module_name is not None:
                from shared.observability.schemas import LibraryUsageEvent

                await record_events(
                    episode_id=self.episode_id,
                    events=[
                        LibraryUsageEvent(
                            module_name=module_name, usage_type="new", path=p_str
                        )
                    ],
                )
            # WP06: Detect COTS selections in assembly definition artifacts.
            if p_str in {
                "assembly_definition.yaml",
                "benchmark_assembly_definition.yaml",
            }:
                try:
                    import yaml

                    data_raw = yaml.safe_load(content)
                    cots_parts = []
                    if isinstance(data_raw, dict):
                        raw_cots_parts = data_raw.get("cots_parts")
                        if isinstance(raw_cots_parts, list):
                            cots_parts = [
                                part
                                for part in raw_cots_parts
                                if isinstance(part, dict)
                                and isinstance(part.get("part_id"), str)
                                and part.get("part_id", "").strip()
                            ]

                    if cots_parts:
                        from shared.observability.schemas import COTSSelectionEvent

                        selected_ids = [
                            str(part["part_id"]).strip() for part in cots_parts
                        ]
                        query_ids: list[str] = []

                        await record_events(
                            episode_id=self.episode_id,
                            events=[
                                COTSSelectionEvent(
                                    selected_part_ids=selected_ids, query_ids=query_ids
                                )
                            ],
                        )
                except Exception as e:
                    logger.warning("failed_to_emit_cots_selection_event", error=str(e))

            # Broadcast update and sync asset via helper
            await broadcast_file_update(self.episode_id, p_str, content)

        return success

    async def edit_file(self, path: str | Path, edits: list[EditOp]) -> bool:
        """Edit a file via the Worker client."""
        path = self._canonical_path(path)
        self._check_perm("write", path)
        p_str = str(path)

        await record_events(
            episode_id=self.episode_id,
            events=[EditFileToolEvent(path=p_str, num_edits=len(edits))],
        )
        success = await self.client.edit_file(p_str, edits)
        if success:
            # For edits, we read the file back to get the updated
            # content for the Asset table
            try:
                content = await self.client.read_file(p_str)
                await broadcast_file_update(self.episode_id, p_str, content)
            except Exception:
                # Don't fail the edit if sync fails
                pass
        return success

    async def run_command(
        self, command: str, timeout: int | None = None
    ) -> ExecuteResponse:
        """
        Execute a shell command via the Worker client, wrapped in Temporal for
        durability.
        """
        if timeout is None:
            timeout = self.policy.get_execution_policy(self.agent_role).timeout_seconds

        await record_events(
            episode_id=self.episode_id,
            events=[RunCommandToolEvent(command=command)],
        )
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                if self.temporal_client:
                    # Wrap in Temporal workflow for durability
                    return await self.temporal_client.execute_workflow(
                        ScriptExecutionWorkflow.run,
                        ScriptExecutionRequest(
                            code=command,
                            session_id=self.client.session_id,
                            timeout=timeout,
                            episode_id=self.episode_id,
                        ),
                        id=f"exec-{self.client.session_id}-{hash(command) % 10**8}",
                        task_queue="simulation-task-queue",
                        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    )
                # Fallback to direct client call if Temporal is not available
                return await self.client.execute_command(
                    command, timeout=timeout, episode_id=self.episode_id
                )
            except Exception as exc:
                is_infra = isinstance(exc, (httpx.HTTPError, TimeoutError))
                if not is_infra:
                    msg = str(exc).lower()
                    is_infra = any(
                        token in msg
                        for token in (
                            "connection refused",
                            "no close frame received or sent",
                            "connection closed",
                            "websocket connection closed",
                            "temporarily unavailable",
                            "name or service not known",
                            "failed to establish",
                            "network is unreachable",
                            "timed out",
                            "timeout",
                        )
                    )

                if not is_infra:
                    raise

                logger.error(
                    "system_tool_retry_attempt",
                    session_id=self.client.session_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(exc),
                )
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"{_SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER}: {exc}"
                    ) from exc
                await asyncio.sleep(min(0.5 * attempt, 1.5))

        raise RuntimeError(_SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER)

    # Adding alias for consistency with deepagents naming if needed
    async def execute(self, command: str, timeout: int = 30) -> ExecuteResponse:
        return await self.run_command(command, timeout=timeout)

    async def grep(
        self, pattern: str, path: str | Path | None = None, glob: str | None = None
    ) -> list[GrepMatch]:
        """Search for a pattern in files via the Worker client."""
        if path:
            path = self._canonical_path(path)
            self._check_perm("read", path)
        else:
            self._check_perm("read", ".")

        p_str = str(path) if path else None
        await record_events(
            episode_id=self.episode_id,
            events=[GrepToolEvent(pattern=pattern, path=p_str, glob=glob)],
        )
        matches = await self.client.grep(pattern, path=p_str, glob=glob)
        # Defense in depth: even if worker grep searches too broadly, only return
        # matches for files this role can read.
        return [match for match in matches if self._can_read(match.path)]

    async def simulate(
        self,
        script_path: str | Path,
        backend: SimulatorBackendType | None = None,
        smoke_test_mode: bool | None = None,
        stream_render_frames: bool = False,
        bundle_base64: str | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger physics simulation via worker client (with bundling)."""
        p_str = str(script_path)
        resolved_backend = backend or get_default_simulator_backend()
        ensure_smoke_test_mode_allowed(
            smoke_test_mode, integration_enabled=worker_settings.is_integration_test
        )
        # Record request
        await record_events(
            episode_id=self.episode_id,
            events=[SimulationRequestEvent(script_path=p_str)],
        )

        self._require_temporal_for_heavy_operation("simulate")

        # Bundle from light worker
        bundle = (
            base64.b64decode(bundle_base64)
            if bundle_base64 is not None
            else await self.client.bundle_session()
        )
        workflow_id = _bundle_workflow_id("sim", self.client.session_id, bundle)
        res = await self._execute_or_use_existing_workflow(
            HeavySimulationWorkflow.run,
            workflow_id,
            HeavySimulationParams(
                bundle_base64=base64.b64encode(bundle).decode("utf-8"),
                script_path=p_str,
                backend=resolved_backend,
                smoke_test_mode=smoke_test_mode,
                session_id=self.client.session_id,
                episode_id=self.episode_id,
                stream_render_frames=stream_render_frames,
            ),
            result_type=BenchmarkToolResponse,
        )
        await record_simulation_result(self.episode_id, res)
        return res

    async def render_cad(
        self,
        script_path: str | Path,
        orbit_pitch: float | list[float] = 45.0,
        orbit_yaw: float | list[float] = 45.0,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        drafting: bool = False,
        rendering_type: str | PreviewRenderingType | None = None,
        bundle_base64: str | None = None,
        smoke_test_mode: bool | None = None,
        script_content: str | None = None,
    ) -> PreviewDesignResponse:
        """Trigger CAD preview through the Temporal-backed preview workflow."""
        p_str = str(script_path)

        async def _broadcast_preview_phase(
            preview_phase: str,
            *,
            response: PreviewDesignResponse | None = None,
        ) -> None:
            try:
                from controller.api.manager import manager
                from controller.utils import resolve_episode_id

                episode_uuid = resolve_episode_id(self.episode_id)
            except Exception:
                return

            metadata_vars: dict[str, Any] = {
                "preview_phase": preview_phase,
                "script_path": p_str,
                "session_id": self.client.session_id,
            }
            if response is not None:
                metadata_vars.update(
                    {
                        "artifact_path": response.artifact_path,
                        "manifest_path": response.manifest_path,
                        "rendering_type": (
                            response.rendering_type.value
                            if response.rendering_type is not None
                            else None
                        ),
                        "view_count": response.view_count,
                    }
                )

            await manager.broadcast(
                episode_uuid,
                {
                    "type": "status_update",
                    "status": EpisodeStatus.RUNNING,
                    "metadata_vars": metadata_vars,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        self._require_temporal_for_heavy_operation("preview")
        await _broadcast_preview_phase("queued")

        if bundle_base64 is not None:
            bundle = base64.b64decode(bundle_base64)
        else:
            bundle = await self.client.bundle_session()
            bundle_base64 = base64.b64encode(bundle).decode("utf-8")

        request = PreviewWorkflowParams(
            bundle_base64=bundle_base64,
            script_path=p_str,
            script_content=script_content,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            drafting=drafting,
            rendering_type=PreviewRenderingType(str(rendering_type))
            if rendering_type is not None
            else None,
            smoke_test_mode=smoke_test_mode,
            session_id=self.client.session_id,
            agent_role=str(self.agent_role.value)
            if isinstance(self.agent_role, AgentName)
            else str(self.agent_role),
        )
        workflow_id = _preview_workflow_id(self.client.session_id, bundle, request)
        await _broadcast_preview_phase("running")
        result = await self._execute_or_use_existing_workflow(
            PreviewWorkflow.run,
            workflow_id,
            request,
            result_type=PreviewDesignResponse,
        )
        await _broadcast_preview_phase("view_ready", response=result)
        return result

    async def preview(
        self,
        script_path: str | Path,
        orbit_pitch: float | list[float] = 45.0,
        orbit_yaw: float | list[float] = 45.0,
        rgb: bool | None = None,
        depth: bool | None = None,
        segmentation: bool | None = None,
        payload_path: bool = False,
        drafting: bool = False,
        rendering_type: str | PreviewRenderingType | None = None,
        bundle_base64: str | None = None,
        smoke_test_mode: bool | None = None,
        script_content: str | None = None,
    ) -> PreviewDesignResponse:
        return await self.render_cad(
            script_path=script_path,
            orbit_pitch=orbit_pitch,
            orbit_yaw=orbit_yaw,
            rgb=rgb,
            depth=depth,
            segmentation=segmentation,
            payload_path=payload_path,
            drafting=drafting,
            rendering_type=rendering_type,
            bundle_base64=bundle_base64,
            smoke_test_mode=smoke_test_mode,
            script_content=script_content,
        )

    async def validate(
        self,
        script_path: str | Path,
        bundle_base64: str | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger geometric validation via the worker-light validation path."""
        p_str = str(script_path)

        res = await self.client.validate(p_str, bundle_base64=bundle_base64)

        await record_events(
            episode_id=self.episode_id,
            events=[
                ManufacturabilityCheckEvent(
                    part_id=p_str,  # Using script_path as part identifier
                    method=ManufacturingMethod.THREE_DP,
                    # FIXME: why 3dp and not a particular method?
                    result=res.success,
                    price=None,
                    weight_g=None,
                    metadata=res.model_dump(),
                )
            ],
        )

        return res

    async def verify(
        self,
        script_path: str | Path,
        backend: SimulatorBackendType | None = None,
        smoke_test_mode: bool | None = None,
        jitter_range: tuple[float, float, float] | None = None,
        num_scenes: int | None = None,
        duration: float | None = None,
        seed: int | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger runtime-randomization verification via worker client."""
        if smoke_test_mode is None:
            smoke_test_mode = worker_settings.smoke_test_mode
        else:
            ensure_smoke_test_mode_allowed(
                smoke_test_mode,
                integration_enabled=worker_settings.is_integration_test,
            )
        self._require_temporal_for_heavy_operation("verify")

        bundle = await self.client.bundle_session()
        workflow_id = _bundle_workflow_id("ver", self.client.session_id, bundle)
        params: dict[str, Any] = {
            "bundle_base64": base64.b64encode(bundle).decode("utf-8"),
            "script_path": str(script_path),
            "backend": backend or get_default_simulator_backend(),
            "smoke_test_mode": smoke_test_mode,
            "session_id": self.client.session_id,
        }
        if jitter_range is not None:
            params["jitter_range"] = jitter_range
        if num_scenes is not None:
            params["num_scenes"] = num_scenes
        if duration is not None:
            params["duration"] = duration
        if seed is not None:
            params["seed"] = seed
        return await self._execute_or_use_existing_workflow(
            HeavyVerifyWorkflow.run,
            workflow_id,
            HeavyVerifyParams(**params),
            result_type=BenchmarkToolResponse,
        )

    async def submit(
        self,
        script_path: str | Path,
        reviewer_stage: AgentName | None = None,
        bundle_base64: str | None = None,
    ) -> BenchmarkToolResponse:
        """Trigger handover to review via worker client."""
        p_str = str(script_path)
        effective_stage = reviewer_stage
        if effective_stage is None:
            role_to_stage: dict[AgentName, AgentName] = {
                AgentName.BENCHMARK_CODER: AgentName.BENCHMARK_REVIEWER,
                AgentName.BENCHMARK_REVIEWER: AgentName.BENCHMARK_REVIEWER,
                AgentName.ELECTRONICS_REVIEWER: AgentName.ELECTRONICS_REVIEWER,
                AgentName.ENGINEER_CODER: AgentName.ENGINEER_EXECUTION_REVIEWER,
                AgentName.ENGINEER_EXECUTION_REVIEWER: AgentName.ENGINEER_EXECUTION_REVIEWER,
            }
            effective_stage = role_to_stage.get(self.agent_role)

        self._require_temporal_for_heavy_operation("submit")

        bundle = (
            base64.b64decode(bundle_base64)
            if bundle_base64 is not None
            else await self.client.bundle_session()
        )
        workflow_id = _bundle_workflow_id("sub", self.client.session_id, bundle)
        res = await self._execute_or_use_existing_workflow(
            HeavySubmitWorkflow.run,
            workflow_id,
            HeavySubmitParams(
                bundle_base64=base64.b64encode(bundle).decode("utf-8"),
                script_path=p_str,
                reviewer_stage=effective_stage or AgentName.ENGINEER_EXECUTION_REVIEWER,
                session_id=self.client.session_id,
                episode_id=self.episode_id,
            ),
        )

        benchmark_roles = {
            AgentName.BENCHMARK_PLANNER,
            AgentName.BENCHMARK_CODER,
            AgentName.BENCHMARK_REVIEWER,
        }
        event_cls = (
            PlanSubmissionBenchmarkEvent
            if self.agent_role in benchmark_roles
            else PlanSubmissionEngineerEvent
        )

        await record_events(
            episode_id=self.episode_id,
            events=[
                event_cls(
                    plan_path=p_str,
                )
            ],
        )

        return res
