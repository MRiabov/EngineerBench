import ast
import asyncio
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import dspy
import structlog
import yaml
from pydantic import TypeAdapter
from sqlalchemy import func, select

from controller.agent.config import (
    LiteLLMRequestConfig,
    _is_transient_provider_rate_error,
    build_dspy_lm,
    settings,
)
from controller.agent.context_usage import update_episode_context_usage
from controller.agent.execution_limits import (
    AgentHardFailError,
    accumulate_episode_credit_usage,
    evaluate_agent_hard_fail,
    mark_episode_execution_window_start,
)
from controller.agent.prompt_manager import PromptManager
from controller.agent.provider_tool_call_adapters import extract_tool_calls
from controller.agent.runtime_models import (
    FileListEntry,
    MessageContentBlock,
    NativeProviderMessage,
    ProviderResponseEnvelope,
)
from controller.clients.worker import WorkerClient
from controller.middleware.remote_fs import RemoteFilesystemMiddleware
from controller.observability.database import DatabaseCallbackHandler
from controller.observability.langfuse import (
    init_tracing,
    report_usage_to_current_observation,
)
from controller.observability.tracing import record_worker_events
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Asset, Trace
from controller.utils import EpisodeIdentity, resolve_episode_id
from shared.agents.config import load_agents_config
from shared.enums import AgentName, TraceType
from shared.git_utils import repo_revision
from shared.models.schemas import CodeReference, ReviewResult, TraceMetadata
from shared.observability.schemas import LlmMediaAttachedEvent
from shared.script_contracts import authored_script_path_for_agent
from shared.workers.filesystem.policy import VisualInspectionPolicy
from shared.workers.schema import (
    MediaInspectionResult,
    RenderBundleIndexEntry,
    RenderManifest,
)

if TYPE_CHECKING:
    from controller.agent.state import AgentState

logger = structlog.get_logger(__name__)
_SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER = "SYSTEM_TOOL_RETRY_EXHAUSTED"
_NATIVE_TOOL_COMPLETION_MAX_TOKENS = 1024


@dataclass
class SharedNodeContext:
    """Shared dependencies and state for agent nodes."""

    worker_light_url: str
    session_id: str  # Langfuse/Worker session (string)
    episode_id: str  # Database episode ID (UUID string)
    pm: PromptManager
    dspy_lm: Any
    worker_client: WorkerClient
    fs: RemoteFilesystemMiddleware
    main_loop: asyncio.AbstractEventLoop

    @classmethod
    def create(
        cls,
        worker_light_url: str,
        session_id: str,
        episode_id: str | None = None,
        worker_client: WorkerClient | None = None,
        fs: RemoteFilesystemMiddleware | None = None,
        agent_role: AgentName = AgentName.ENGINEER_CODER,
    ) -> "SharedNodeContext":
        main_loop = asyncio.get_running_loop()
        identity = EpisodeIdentity.from_context(
            session_id=session_id, episode_id=episode_id
        )

        structlog.contextvars.bind_contextvars(
            session_id=identity.session_id,
            episode_id=str(identity.episode_id),
            agent_role=agent_role.value,
            stage=agent_role.value,
        )

        if not worker_client:
            worker_client = WorkerClient(
                base_url=worker_light_url,
                session_id=session_id,
                heavy_url=settings.worker_heavy_url,
                agent_role=agent_role,
            )

        if not fs:
            fs = RemoteFilesystemMiddleware(
                worker_client,
                agent_role=agent_role,
                episode_id=str(identity.episode_id),
            )

        request_config = settings.resolve_dspy_lm_request_config(settings.llm_model)
        # T025: Initialize native tracing
        init_tracing()

        logger.info(
            "lm_client_initialized",
            provider=request_config.provider,
            model=request_config.model,
            api_base=request_config.api_base,
            planner_token_cap=settings.llm_max_tokens
            if "planner" in agent_role.value
            else None,
        )
        dspy_lm = build_dspy_lm(
            settings.llm_model,
            session_id=session_id,
            agent_role=agent_role.value,
        )

        return cls(
            worker_light_url=worker_light_url,
            session_id=identity.session_id,
            episode_id=str(identity.episode_id),
            pm=PromptManager(),
            dspy_lm=dspy_lm,
            worker_client=worker_client,
            fs=fs,
            main_loop=main_loop,
        )

    def get_database_recorder(
        self, episode_id: str | None = None
    ) -> DatabaseCallbackHandler:
        """Creates a database recorder for traces."""
        eid = episode_id or self.episode_id
        return DatabaseCallbackHandler(episode_id=eid, loop=self.main_loop)

    def get_callbacks(self) -> list[DatabaseCallbackHandler]:
        """WP08: Support manual callback retrieval for integration tests."""
        recorder = self.get_database_recorder()
        return [recorder]


class BaseNode:
    """Base class for agent nodes providing common utilities."""

    def __init__(self, context: SharedNodeContext):
        self.ctx = context
        self._tool_usage_counts: dict[str, int] = {}
        self._inspected_media_paths: list[str] = []

    def _reset_tool_usage_tracking(self) -> None:
        self._tool_usage_counts = {}
        self._inspected_media_paths = []

    def _record_tool_usage(self, tool_name: str, result: Any) -> None:
        self._tool_usage_counts[tool_name] = (
            self._tool_usage_counts.get(tool_name, 0) + 1
        )
        if (
            tool_name == "inspect_media"
            and isinstance(result, MediaInspectionResult)
            and result.attached_to_model
            and result.media_kind in {"image", "video_frames"}
        ):
            self._inspected_media_paths.append(
                self._normalize_inspected_media_path(result.path)
            )

    def _used_tool(self, tool_name: str) -> bool:
        return self._tool_usage_counts.get(tool_name, 0) > 0

    def _inspected_media_path_count(self) -> int:
        return len(self._inspected_media_paths)

    def _inspected_unique_media_path_count(self) -> int:
        return len(set(self._inspected_media_paths))

    def _normalized_inspected_media_path_set(self) -> set[str]:
        return {
            self._normalize_inspected_media_path(path)
            for path in self._inspected_media_paths
        }

    def _count_inspected_render_media_paths(self, render_paths: list[str]) -> int:
        inspected_paths = self._normalized_inspected_media_path_set()
        current_render_paths = {
            self._normalize_inspected_media_path(path)
            for path in render_paths
            if self._is_image_media_path(path)
        }
        return len(inspected_paths.intersection(current_render_paths))

    async def _list_current_revision_render_paths(self) -> list[str]:
        current_revision = repo_revision(Path(__file__).resolve().parents[2])
        if not current_revision:
            return []

        index_candidates = (
            "renders/render_index.jsonl",
            "workspace/renders/render_index.jsonl",
        )
        for candidate in index_candidates:
            if not await self.ctx.worker_client.exists(
                candidate, bypass_agent_permissions=True
            ):
                continue
            try:
                index_raw = await self.ctx.worker_client.read_file(
                    candidate, bypass_agent_permissions=True
                )
            except Exception:
                continue

            for line in reversed(
                [row for row in index_raw.splitlines() if row.strip()]
            ):
                try:
                    entry = RenderBundleIndexEntry.model_validate_json(line)
                except Exception:
                    continue
                if not entry.revision:
                    continue
                if entry.revision.strip().lower() != current_revision.lower():
                    continue
                manifest_path = entry.manifest_path.lstrip("/")
                if not await self.ctx.worker_client.exists(
                    manifest_path, bypass_agent_permissions=True
                ):
                    continue
                try:
                    manifest_raw = await self.ctx.worker_client.read_file(
                        manifest_path, bypass_agent_permissions=True
                    )
                    render_manifest = RenderManifest.model_validate_json(manifest_raw)
                except Exception:
                    continue
                preview_paths = [
                    path.lstrip("/")
                    for path in render_manifest.preview_evidence_paths
                    if path and path.lower().endswith((".png", ".jpg", ".jpeg"))
                ]
                if preview_paths:
                    return sorted(dict.fromkeys(preview_paths))
                artifact_paths = [
                    path.lstrip("/")
                    for path in render_manifest.artifacts.keys()
                    if path and path.lower().endswith((".png", ".jpg", ".jpeg"))
                ]
                if artifact_paths:
                    return sorted(dict.fromkeys(artifact_paths))

        manifest_candidates = [
            "renders/benchmark_renders/render_manifest.json",
            "renders/engineer_plan_renders/render_manifest.json",
            "renders/final_solution_submission_renders/render_manifest.json",
            "workspace/renders/benchmark_renders/render_manifest.json",
            "workspace/renders/engineer_plan_renders/render_manifest.json",
            "workspace/renders/final_solution_submission_renders/render_manifest.json",
        ]
        for candidate in manifest_candidates:
            if not await self.ctx.worker_client.exists(
                candidate, bypass_agent_permissions=True
            ):
                continue
            try:
                manifest_raw = await self.ctx.worker_client.read_file(
                    candidate, bypass_agent_permissions=True
                )
                render_manifest = RenderManifest.model_validate_json(manifest_raw)
            except Exception:
                continue

            if not render_manifest.revision:
                continue
            if render_manifest.revision.strip().lower() != current_revision.lower():
                continue

            preview_paths = [
                path.lstrip("/")
                for path in render_manifest.preview_evidence_paths
                if path and path.lower().endswith((".png", ".jpg", ".jpeg"))
            ]
            if preview_paths:
                return sorted(dict.fromkeys(preview_paths))

            artifact_paths = [
                path.lstrip("/")
                for path in render_manifest.artifacts.keys()
                if path and path.lower().endswith((".png", ".jpg", ".jpeg"))
            ]
            if artifact_paths:
                return sorted(dict.fromkeys(artifact_paths))

        return []

    async def _ensure_current_revision_render_inspection(self) -> list[str]:
        """
        Deterministically inspect at least one current-revision render when present.

        Reviewer roles must not short-circuit around visual inspection simply
        because they are about to reject on another gate.
        """

        render_paths = await self._list_current_revision_render_paths()
        if render_paths:
            db_callback = self.ctx.get_database_recorder(self.ctx.episode_id)
            input_data = json.dumps({"args": [render_paths[0]]})
            trace_id = db_callback.record_tool_start_sync("inspect_media", input_data)
            try:
                result = await self.ctx.fs.inspect_media(render_paths[0])
            except Exception as exc:
                db_callback.record_tool_end_sync(trace_id, str(exc), is_error=True)
                raise
            self._record_tool_usage("inspect_media", result)
            db_callback.record_tool_end_sync(
                trace_id, self._serialize_tool_observation(result)
            )
            return [render_paths[0]]

        for preview_path in (
            "renders/render_e45_a45.png",
            "renders/dof_review_preview.png",
        ):
            preview_exists = await self.ctx.worker_client.exists(preview_path)
            if not preview_exists:
                continue
            db_callback = self.ctx.get_database_recorder(self.ctx.episode_id)
            input_data = json.dumps({"args": [preview_path]})
            trace_id = db_callback.record_tool_start_sync("inspect_media", input_data)
            try:
                result = await self.ctx.fs.inspect_media(preview_path)
            except Exception as exc:
                db_callback.record_tool_end_sync(trace_id, str(exc), is_error=True)
                raise
            self._record_tool_usage("inspect_media", result)
            db_callback.record_tool_end_sync(
                trace_id, self._serialize_tool_observation(result)
            )
            return [preview_path]
        return []

    def _get_visual_inspection_policy(
        self, node_type: AgentName
    ) -> VisualInspectionPolicy:
        return self.ctx.fs.policy.get_visual_inspection_policy(node_type)

    async def _read_optional_workspace_file(self, path: str, missing_text: str) -> str:
        """Read a workspace file if present, otherwise return a placeholder."""
        with suppress(Exception):
            content = await self.ctx.worker_client.read_file_optional(path)
            if content is not None:
                return content
        return missing_text

    async def _read_required_workspace_file(self, path: str) -> str:
        """Read a workspace file and fail closed if it is missing."""
        content = await self.ctx.worker_client.read_file_optional(path)
        if content is None:
            raise ValueError(f"required workspace file missing: {path}")
        return content

    async def _next_review_round(self, review_slug: str) -> int:
        pattern = re.compile(rf"^{re.escape(review_slug)}-decision-round-(\d+)\.yaml$")
        max_round = 0
        try:
            entries = await self.ctx.worker_client.list_files(
                "reviews", bypass_agent_permissions=True
            )
        except Exception:
            return 1

        for entry in entries:
            if entry.is_dir:
                continue
            match = pattern.fullmatch(entry.name)
            if match:
                max_round = max(max_round, int(match.group(1)))
        return max_round + 1

    async def _persist_review_result(
        self,
        review: ReviewResult,
        review_slug: str,
        *,
        round_number: int | None = None,
    ) -> tuple[str, str]:
        next_round = round_number or await self._next_review_round(review_slug)
        decision_path = f"reviews/{review_slug}-decision-round-{next_round}.yaml"
        comments_path = f"reviews/{review_slug}-comments-round-{next_round}.yaml"

        comments: list[str] = []
        reason = review.reason.strip()
        if reason:
            comments.append(reason)
        comments.extend(
            fix.strip() for fix in review.required_fixes if fix and fix.strip()
        )
        if not comments:
            comments.append(f"{review.decision.value} review")

        decision_content = yaml.safe_dump(
            {"decision": review.decision.value},
            sort_keys=False,
            allow_unicode=False,
        )
        summary = (
            f"{review.decision.value}: {reason}"
            if reason
            else f"{review.decision.value}: (no reason provided)"
        )
        comments_content = yaml.safe_dump(
            {
                "summary": summary,
                "comments": comments,
                "required_fixes": [
                    fix.strip()
                    for fix in review.required_fixes
                    if isinstance(fix, str) and fix.strip()
                ],
                "checklist": dict(review.checklist or {}),
            },
            sort_keys=False,
            allow_unicode=False,
        )
        decision_written = await self.ctx.worker_client.write_file(
            decision_path,
            decision_content,
            overwrite=True,
            bypass_agent_permissions=True,
        )
        comments_written = await self.ctx.worker_client.write_file(
            comments_path,
            comments_content,
            overwrite=True,
            bypass_agent_permissions=True,
        )
        if not decision_written:
            decision_written = await self.ctx.worker_client.write_file(
                decision_path,
                decision_content,
                overwrite=True,
                bypass_agent_permissions=True,
            )
        if not comments_written:
            comments_written = await self.ctx.worker_client.write_file(
                comments_path,
                comments_content,
                overwrite=True,
                bypass_agent_permissions=True,
            )
        if (
            not decision_written
            or not comments_written
            or not await self.ctx.worker_client.exists(
                decision_path, bypass_agent_permissions=True
            )
            or not await self.ctx.worker_client.exists(
                comments_path, bypass_agent_permissions=True
            )
        ):
            raise RuntimeError(
                "review files were not materialized at "
                f"{decision_path} and {comments_path}"
            )
        return decision_path, comments_path

    def _get_runtime_prompt(self, key: str, **kwargs: Any) -> str:
        prompt = str(self.ctx.pm.get_prompt_value(key)).strip()
        return prompt.format(**kwargs) if kwargs else prompt

    @staticmethod
    def _runtime_prompt_scope(node_type: AgentName) -> str:
        if node_type in {
            AgentName.BENCHMARK_PLANNER,
            AgentName.BENCHMARK_PLAN_REVIEWER,
            AgentName.BENCHMARK_CODER,
            AgentName.BENCHMARK_REVIEWER,
        }:
            return "benchmark_generator.runtime"
        return "engineer.runtime"

    def _runtime_prompt_key(self, node_type: AgentName, key: str) -> str:
        return f"{self._runtime_prompt_scope(node_type)}.{key}"

    @staticmethod
    def _tool_response_message(
        *,
        tool_call_id: str,
        tool_name: str,
        content: str,
    ) -> dict[str, str]:
        """
        Tool responses are runtime-owned/system-origin messages semantically,
        but provider-native tool loops require them to be encoded with
        `role="tool"` and linked to the original tool_call_id.
        """
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": content,
        }

    @staticmethod
    def _parse_native_tool_arguments(
        tool_name: str,
        raw_arguments: Any,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if isinstance(raw_arguments, dict):
            payload = raw_arguments
        else:
            serialized_arguments = raw_arguments
            if serialized_arguments in (None, ""):
                serialized_arguments = "{}"
            if not isinstance(serialized_arguments, str):
                return None, (
                    f"Tool arguments for {tool_name} must be a JSON object string; "
                    f"got {type(raw_arguments).__name__}."
                )
            try:
                payload = json.loads(serialized_arguments)
            except json.JSONDecodeError as exc:
                return None, (
                    f"Invalid JSON arguments for {tool_name}: {exc}. "
                    "Re-emit the tool call with a valid JSON object."
                )

        if not isinstance(payload, dict):
            return None, f"Tool arguments for {tool_name} must be a JSON object."
        return payload, None

    @staticmethod
    def _is_image_media_path(path: str) -> bool:
        return path.lower().endswith((".png", ".jpg", ".jpeg"))

    @staticmethod
    def _normalize_inspected_media_path(path: str) -> str:
        normalized = Path(path).as_posix()
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    async def _list_render_media_paths(self) -> list[str]:
        with suppress(Exception):
            pending_dirs = ["/renders"]
            media_paths: list[str] = []
            visited_dirs: set[str] = set()
            while pending_dirs:
                current_dir = pending_dirs.pop()
                if current_dir in visited_dirs:
                    continue
                visited_dirs.add(current_dir)
                entries = await self.ctx.worker_client.list_files(current_dir)
                for entry in entries:
                    entry_model = None
                    with suppress(Exception):
                        entry_model = FileListEntry.model_validate(entry)
                    path = (entry_model.path if entry_model else None) or ""
                    if not path:
                        continue
                    if entry_model is not None and entry_model.is_dir:
                        pending_dirs.append(path.rstrip("/"))
                        continue
                    if self._is_image_media_path(path):
                        media_paths.append(path.lstrip("/"))
            media_paths.sort()
            return media_paths
        return []

    async def _workspace_has_render_media(self) -> bool:
        return bool(await self._list_render_media_paths())

    def _list_render_media_paths_sync(self) -> list[str]:
        with suppress(Exception):
            future = asyncio.run_coroutine_threadsafe(
                self._list_render_media_paths(),
                self.ctx.main_loop,
            )
            return future.result(timeout=10.0)
        return []

    async def _get_visual_inspection_context(
        self, node_type: AgentName
    ) -> tuple[VisualInspectionPolicy, list[str]]:
        policy = self._get_visual_inspection_policy(node_type)
        if not policy.required:
            return policy, []
        return policy, await self._list_render_media_paths()

    def _build_visual_inspection_reminder(
        self,
        *,
        policy: VisualInspectionPolicy,
        media_paths: list[str],
    ) -> str:
        inspected = self._inspected_unique_media_path_count()
        examples = ", ".join(media_paths[: min(3, len(media_paths))])
        return self._get_runtime_prompt(
            self._runtime_prompt_key(
                self.ctx.fs.agent_role, "visual_inspection_reminder"
            ),
            min_images=policy.min_images,
            inspected=inspected,
            examples=examples,
        )

    def _get_visual_inspection_requirement_message(
        self,
        *,
        policy: VisualInspectionPolicy,
        media_paths: list[str],
    ) -> str | None:
        if not policy.required or not media_paths:
            return None
        if self._inspected_unique_media_path_count() >= policy.min_images:
            return None
        return self._build_visual_inspection_reminder(
            policy=policy,
            media_paths=media_paths,
        )

    def _create_dspy_adapter(
        self, *, use_native_function_calling: bool = False
    ) -> dspy.ChatAdapter:
        """Use the explicit ChatAdapter contract and fail closed on parse mismatch."""
        return dspy.ChatAdapter(
            use_native_function_calling=use_native_function_calling,
            use_json_adapter_fallback=False,
        )

    @staticmethod
    def _field_desc(field_info: Any) -> str | None:
        extra = getattr(field_info, "json_schema_extra", None) or {}
        desc = extra.get("desc")
        return desc if isinstance(desc, str) and desc.strip() else None

    @staticmethod
    def _field_type(field_info: Any, fallback: type[Any] = str) -> type[Any]:
        annotation = getattr(field_info, "annotation", None)
        return annotation if isinstance(annotation, type) or annotation else fallback

    def _should_use_native_tool_loop(
        self, *, node_type: AgentName, program_cls: type[dspy.Module]
    ) -> bool:
        """Native tool calls are enabled incrementally for unstable ReAct nodes."""
        return program_cls is dspy.ReAct and node_type in {
            AgentName.BENCHMARK_PLANNER,
            AgentName.BENCHMARK_PLAN_REVIEWER,
            AgentName.BENCHMARK_CODER,
            AgentName.BENCHMARK_REVIEWER,
            AgentName.COTS_SEARCH,
            AgentName.ENGINEER_PLANNER,
            AgentName.ENGINEER_CODER,
            AgentName.ENGINEER_PLAN_REVIEWER,
            AgentName.ENGINEER_EXECUTION_REVIEWER,
        }

    def _build_native_tool_signature(
        self,
        *,
        signature_cls: type[dspy.Signature],
        inputs: dict[str, Any],
        node_type: AgentName,
    ) -> type[dspy.Signature]:
        output_fields = ", ".join(signature_cls.output_fields.keys())
        completion_tool_name = self._completion_tool_name(node_type)
        instructions = signature_cls.instructions or ""
        native_instructions = self._get_runtime_prompt(
            self._runtime_prompt_key(node_type, "native_tool_signature_contract"),
            completion_tool_name=completion_tool_name,
            output_fields=output_fields,
        )
        if node_type == AgentName.BENCHMARK_PLANNER:
            native_instructions = (
                native_instructions
                + "\n"
                + self._get_runtime_prompt(
                    self._runtime_prompt_key(
                        node_type, "benchmark_planner_native_tool_signature_suffix"
                    )
                )
            )

        field_defs: dict[str, tuple[type[Any], Any]] = {}
        for name, value in inputs.items():
            field_info = signature_cls.input_fields.get(name)
            field_defs[name] = (
                self._field_type(
                    field_info,
                    fallback=(type(value) if value is not None else str),
                ),
                dspy.InputField(desc=self._field_desc(field_info)),
            )

        field_defs["trajectory"] = (
            str,
            dspy.InputField(
                desc="Prior tool calls and observations for the current node."
            ),
        )
        field_defs["tools"] = (
            list[dspy.Tool],
            dspy.InputField(desc="Available tools for native function calling."),
        )
        field_defs["tool_calls"] = (
            dspy.ToolCalls,
            dspy.OutputField(desc="Native tool call(s) to execute this turn."),
        )

        signature_name = (
            f"{node_type.value.title().replace(' ', '').replace('_', '')}"
            "NativeToolSignature"
        )
        return dspy.make_signature(
            field_defs,
            instructions=(
                f"{instructions}\n\n{native_instructions}"
                if instructions
                else native_instructions
            ),
            signature_name=signature_name,
        )

    def _build_finish_tool(
        self, signature_cls: type[dspy.Signature]
    ) -> tuple[dspy.Tool, list[str]]:
        output_field_names = list(signature_cls.output_fields.keys())
        properties: dict[str, Any] = {}
        for name, field_info in signature_cls.output_fields.items():
            field_type = self._field_type(field_info)
            try:
                schema = TypeAdapter(field_type).json_schema()
            except Exception:
                schema = {"type": "string"}
            desc = self._field_desc(field_info)
            if desc:
                schema["description"] = desc
            properties[name] = schema

        def finish(**kwargs: Any) -> dict[str, Any]:
            return kwargs

        finish_tool = dspy.Tool(
            finish,
            name="finish",
            desc=(
                "Call this exactly once when the node is done. "
                "Provide the final output fields for the node."
            ),
            args=properties,
        )
        return finish_tool, output_field_names

    def _resolve_native_dspy_model(
        self, *, prefer_multimodal: bool = False
    ) -> LiteLLMRequestConfig:
        model_name = settings.llm_model
        if prefer_multimodal:
            multimodal_model = load_agents_config().llm.multimodal_model
            if multimodal_model:
                model_name = multimodal_model
        return settings.resolve_dspy_lm_request_config(model_name)

    def _resolve_native_litellm_model(
        self, *, prefer_multimodal: bool = False
    ) -> LiteLLMRequestConfig:
        """Backward-compatible alias for the DSPy model resolver."""
        return self._resolve_native_dspy_model(prefer_multimodal=prefer_multimodal)

    @staticmethod
    def _native_schema_type(annotation: Any) -> str:
        if annotation is bool:
            return "boolean"
        if annotation is int:
            return "integer"
        if annotation is float:
            return "number"
        if annotation in {dict, dict[str, Any]}:
            return "object"
        if annotation in {list, list[str], list[Any]}:
            return "array"
        return "string"

    def _build_native_tool_schemas(
        self,
        tool_fns: dict[str, Callable],
        *,
        extra_schemas: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for tool_name, tool_fn in tool_fns.items():
            signature = inspect.signature(tool_fn)
            properties: dict[str, Any] = {}
            required: list[str] = []

            for param_name, param in signature.parameters.items():
                if param.kind not in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ):
                    continue
                annotation = (
                    param.annotation
                    if param.annotation is not inspect.Signature.empty
                    else str
                )
                properties[param_name] = {
                    "type": self._native_schema_type(annotation),
                }
                if param.default is inspect.Signature.empty:
                    required.append(param_name)
                else:
                    properties[param_name]["default"] = param.default

            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": inspect.getdoc(tool_fn) or "",
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                            "additionalProperties": False,
                        },
                    },
                }
            )

        if extra_schemas:
            schemas.extend(extra_schemas)
        return schemas

    def _build_finish_tool_schema(
        self,
        signature_cls: type[dspy.Signature],
        *,
        tool_name: str = "finish",
    ) -> tuple[dict[str, Any], list[str]]:
        output_field_names = list(signature_cls.output_fields.keys())
        properties: dict[str, Any] = {}
        required: list[str] = []

        for name, field_info in signature_cls.output_fields.items():
            field_type = self._field_type(field_info)
            try:
                schema = TypeAdapter(field_type).json_schema()
            except Exception:
                schema = {"type": "string"}
            desc = self._field_desc(field_info)
            if desc:
                schema["description"] = desc
            properties[name] = schema
            required.append(name)

        return (
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": (
                        "Call this exactly once when the node is done. "
                        "Provide the final output fields for the node."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            },
            output_field_names,
        )

    @staticmethod
    def _is_reviewer_completion_node(node_type: AgentName) -> bool:
        return node_type in {
            AgentName.BENCHMARK_PLAN_REVIEWER,
            AgentName.BENCHMARK_REVIEWER,
            AgentName.ENGINEER_PLAN_REVIEWER,
            AgentName.ENGINEER_EXECUTION_REVIEWER,
        }

    def _completion_tool_name(self, node_type: AgentName) -> str:
        if self._is_reviewer_completion_node(node_type):
            return "submit_review"
        return "finish"

    @staticmethod
    def _coerce_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            text_chunks: list[str] = []
            for block in content:
                if isinstance(block, str):
                    if block.strip():
                        text_chunks.append(block.strip())
                    continue
                if isinstance(block, dict):
                    text_value = block.get("text")
                    if isinstance(text_value, str) and text_value.strip():
                        text_chunks.append(text_value.strip())
                        continue
                    nested_text = block.get("content")
                    if isinstance(nested_text, str) and nested_text.strip():
                        text_chunks.append(nested_text.strip())
                        continue
                block_model = None
                with suppress(Exception):
                    block_model = MessageContentBlock.model_validate(block)
                if block_model is None:
                    continue
                if isinstance(block_model.text, str) and block_model.text.strip():
                    text_chunks.append(block_model.text.strip())
                    continue
                if isinstance(block_model.content, str) and block_model.content.strip():
                    text_chunks.append(block_model.content.strip())
            if text_chunks:
                return "\n".join(text_chunks)
        if content is None:
            return ""
        return str(content).strip()

    def _extract_native_tool_calls(
        self, message: Any, *, model_name: str | None = None
    ) -> tuple[str, list[dict[str, Any]]]:
        message_model = None
        with suppress(Exception):
            message_model = NativeProviderMessage.model_validate(message)
        assistant_text = self._coerce_message_text(
            message_model.content if message_model is not None else None
        )
        parsed = extract_tool_calls(
            message,
            assistant_text=assistant_text,
            model_name=model_name,
        )
        if parsed.adapter_name:
            logger.info(
                "provider_tool_call_adapter_used",
                adapter=parsed.adapter_name,
                model_name=model_name,
                session_id=self.ctx.session_id,
            )
        return parsed.assistant_text, parsed.tool_calls

    def _assistant_message_with_tool_calls(
        self,
        message: Any,
        *,
        model_name: str | None = None,
        assistant_text: str | None = None,
        tool_calls_payload: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if assistant_text is None or tool_calls_payload is None:
            assistant_text, tool_calls_payload = self._extract_native_tool_calls(
                message,
                model_name=model_name,
            )
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_text,
            "tool_calls": tool_calls_payload,
        }
        message_model = None
        with suppress(Exception):
            message_model = NativeProviderMessage.model_validate(message)
        provider_specific_fields = (
            message_model.provider_specific_fields
            if message_model is not None
            else None
        )
        if isinstance(provider_specific_fields, dict) and provider_specific_fields:
            assistant_message["provider_specific_fields"] = provider_specific_fields
        return assistant_message

    @staticmethod
    def _requires_submit_plan(node_type: AgentName) -> bool:
        return node_type in {
            AgentName.ENGINEER_PLANNER,
        }

    @staticmethod
    def _planner_submission_tool_names(node_type: AgentName) -> tuple[str, ...]:
        if node_type == AgentName.BENCHMARK_PLANNER:
            return ("submit_benchmark_plan", "submit_plan")
        if node_type in {
            AgentName.ENGINEER_PLANNER,
        }:
            return ("submit_engineering_plan", "submit_plan")
        return ("submit_plan",)

    @classmethod
    def _planner_submission_tool_name(cls, node_type: AgentName) -> str:
        return cls._planner_submission_tool_names(node_type)[0]

    @staticmethod
    def _requires_script_artifact(node_type: AgentName) -> bool:
        return node_type in {
            AgentName.BENCHMARK_CODER,
            AgentName.ENGINEER_CODER,
        }

    @staticmethod
    def _submit_plan_succeeded(result: Any) -> bool:
        payload = result
        if isinstance(payload, str):
            with suppress(Exception):
                payload = json.loads(payload)
        return (
            isinstance(payload, dict)
            and payload.get("ok") is True
            and payload.get("status") == "submitted"
        )

    @staticmethod
    def _submit_plan_error_message(result: Any) -> str | None:
        payload = result
        if isinstance(payload, str):
            with suppress(Exception):
                payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None
        errors = payload.get("errors")
        if isinstance(errors, list):
            normalized = [str(err).strip() for err in errors if str(err).strip()]
            if normalized:
                return "; ".join(normalized)
        return None

    @staticmethod
    def _planner_autosubmit_prediction(
        *,
        signature_cls: type[dspy.Signature],
        finish_fields: list[str],
        node_type: AgentName,
    ) -> dspy.Prediction:
        summary = {
            AgentName.ENGINEER_PLANNER: "Mechanical planner artifacts submitted successfully.",
        }.get(node_type, "Planner artifacts submitted successfully.")
        return dspy.Prediction.from_completions(
            {
                field_name: [summary if field_name == "summary" else ""]
                for field_name in finish_fields
            },
            signature=signature_cls,
        )

    def _run_native_tool_loop(
        self,
        *,
        signature_cls: type[dspy.Signature],
        inputs: dict[str, Any],
        tool_fns: dict[str, Callable],
        node_type: AgentName,
        max_iters: int,
        visual_policy: VisualInspectionPolicy,
        render_media_paths: list[str],
        db_callback: DatabaseCallbackHandler | None = None,
    ) -> dspy.Prediction:
        instructions = signature_cls.instructions or ""
        requires_submit_plan = self._requires_submit_plan(node_type)
        submit_tool_names = (
            self._planner_submission_tool_names(node_type)
            if requires_submit_plan
            else ()
        )
        submit_tool_name = submit_tool_names[0] if submit_tool_names else "submit_plan"
        completion_tool_name = self._completion_tool_name(node_type)
        runtime_instructions = self._get_runtime_prompt(
            self._runtime_prompt_key(node_type, "native_tool_loop_contract"),
            completion_tool_name=completion_tool_name,
        )
        if requires_submit_plan:
            runtime_instructions += "\n" + self._get_runtime_prompt(
                self._runtime_prompt_key(node_type, "planner_submit_contract"),
                completion_tool_name=completion_tool_name,
            )
        system_prompt = (
            f"{instructions.strip()}\n\n{runtime_instructions}".strip()
            if instructions.strip()
            else runtime_instructions
        )
        user_prompt = "Node inputs:\n" + json.dumps(
            inputs, indent=2, ensure_ascii=True, default=str
        )
        finish_schema, finish_fields = self._build_finish_tool_schema(
            signature_cls, tool_name=completion_tool_name
        )
        tool_schemas = self._build_native_tool_schemas(
            tool_fns, extra_schemas=[finish_schema]
        )
        self._reset_tool_usage_tracking()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        current_render_media_paths = list(render_media_paths)

        def refresh_render_media_paths() -> list[str]:
            nonlocal current_render_media_paths
            if not visual_policy.required:
                return current_render_media_paths
            current_render_media_paths = self._list_render_media_paths_sync()
            return current_render_media_paths

        current_render_media_paths = refresh_render_media_paths()
        unmet_visual_requirement = self._get_visual_inspection_requirement_message(
            policy=visual_policy,
            media_paths=current_render_media_paths,
        )
        if unmet_visual_requirement:
            messages.append({"role": "system", "content": unmet_visual_requirement})
        prefer_multimodal = bool(visual_policy.required and current_render_media_paths)
        request_config = self._resolve_native_dspy_model(
            prefer_multimodal=prefer_multimodal
        )
        logger.info(
            "native_tool_loop_model_selected",
            node_type=node_type,
            session_id=self.ctx.session_id,
            prefer_multimodal=prefer_multimodal,
            render_media_count=len(current_render_media_paths),
            model=request_config.model,
            provider=request_config.provider,
        )
        submit_plan_succeeded = False
        terminal_submit_plan_rejection = False
        no_tool_call_streak = 0
        initial_script_sha256 = (
            str(inputs.get("initial_script_sha256") or "").strip() or None
        )
        authored_script_path = authored_script_path_for_agent(node_type)

        def workspace_file_exists_sync(path: str) -> bool:
            future = asyncio.run_coroutine_threadsafe(
                self.ctx.worker_client.exists(path),
                self.ctx.main_loop,
            )
            return bool(future.result(timeout=10.0))

        def workspace_file_sha256_sync(path: str) -> str | None:
            future = asyncio.run_coroutine_threadsafe(
                self.ctx.worker_client.read_file_optional(path),
                self.ctx.main_loop,
            )
            content = future.result(timeout=10.0)
            if content is None:
                return None
            return hashlib.sha256(content.encode("utf-8")).hexdigest()

        native_lm = (
            self.ctx.dspy_lm
            if not prefer_multimodal
            else build_dspy_lm(
                request_config.model,
                session_id=self.ctx.session_id,
                agent_role=node_type.value,
            )
        ).copy(
            timeout=settings.native_tool_completion_timeout_seconds,
            # Keep the tool-loop request below the current OpenRouter credit ceiling.
            max_tokens=min(settings.llm_max_tokens, _NATIVE_TOOL_COMPLETION_MAX_TOKENS),
        )
        for iteration in range(max_iters):
            native_mock_completion = getattr(native_lm, "native_tool_completion", None)
            if callable(native_mock_completion):
                message = native_mock_completion(
                    messages=messages,
                    node_type=node_type,
                    finish_fields=finish_fields,
                    completion_tool_name=completion_tool_name,
                )
            else:
                response = native_lm(
                    messages=messages,
                    tools=tool_schemas,
                    tool_choice="auto",
                )
                if isinstance(response, list):
                    first_response = response[0] if response else None
                    message = None
                    with suppress(Exception):
                        message = NativeProviderMessage.model_validate(first_response)
                else:
                    response_model = None
                    with suppress(Exception):
                        response_model = ProviderResponseEnvelope.model_validate(
                            response
                        )
                    message = None
                    if response_model and response_model.choices:
                        message = response_model.choices[0].message
                    if message is None:
                        with suppress(Exception):
                            message = NativeProviderMessage.model_validate(response)
                if message is None:
                    message = NativeProviderMessage()
            assistant_text, tool_calls = self._extract_native_tool_calls(
                message,
                model_name=request_config.model,
            )
            if assistant_text and db_callback:
                db_callback.record_reasoning_text_sync(
                    node_name=str(node_type),
                    reasoning_text=assistant_text,
                    step_index=iteration,
                    source="native_tool_loop",
                )

            if not tool_calls:
                no_tool_call_streak += 1
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_text
                        or "No tool call was emitted on the previous turn.",
                    }
                )
                if no_tool_call_streak > 5:
                    no_tool_call_reminder = str(
                        self.ctx.pm.get_prompt_value(
                            self._runtime_prompt_key(node_type, "no_tool_call_nudge")
                        )
                    ).strip()
                    if requires_submit_plan and not submit_plan_succeeded:
                        no_tool_call_reminder += "\n" + self._get_runtime_prompt(
                            self._runtime_prompt_key(
                                node_type, "submit_before_completion_nudge"
                            ),
                            completion_tool_name=completion_tool_name,
                        )
                else:
                    no_tool_call_reminder = self._get_runtime_prompt(
                        self._runtime_prompt_key(node_type, "continue_from_workspace")
                    )
                messages.append({"role": "system", "content": no_tool_call_reminder})
                continue

            no_tool_call_streak = 0
            messages.append(
                self._assistant_message_with_tool_calls(
                    message,
                    model_name=request_config.model,
                    assistant_text=assistant_text,
                    tool_calls_payload=tool_calls,
                )
            )

            for call in tool_calls:
                function = call.get("function", {})
                tool_name = str(function.get("name") or "").strip()
                if not tool_name:
                    raise ValueError("Native tool call is missing a function name.")

                raw_arguments = function.get("arguments", "{}") or "{}"
                payload, argument_error = self._parse_native_tool_arguments(
                    tool_name, raw_arguments
                )
                if argument_error:
                    logger.warning(
                        "native_tool_call_payload_invalid",
                        node_type=str(node_type),
                        session_id=self.ctx.session_id,
                        tool_name=tool_name,
                        error=argument_error,
                    )
                    messages.append(
                        self._tool_response_message(
                            tool_call_id=call.get("id", ""),
                            tool_name=tool_name,
                            content=argument_error,
                        )
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": self._get_runtime_prompt(
                                self._runtime_prompt_key(
                                    node_type, "invalid_tool_arguments_recover"
                                ),
                                tool_name=tool_name,
                            ),
                        }
                    )
                    continue

                if tool_name == completion_tool_name:
                    if requires_submit_plan and not submit_plan_succeeded:
                        submit_reminder = self._get_runtime_prompt(
                            self._runtime_prompt_key(node_type, "submit_before_finish")
                        )
                        messages.append(
                            self._tool_response_message(
                                tool_call_id=call.get("id", ""),
                                tool_name=completion_tool_name,
                                content=submit_reminder,
                            )
                        )
                        messages.append({"role": "system", "content": submit_reminder})
                        continue
                    if self._requires_script_artifact(node_type):
                        script_exists = workspace_file_exists_sync(authored_script_path)
                        refusal_exists = workspace_file_exists_sync("plan_refusal.md")
                        script_changed = True
                        if script_exists and initial_script_sha256:
                            current_script_sha256 = workspace_file_sha256_sync(
                                authored_script_path
                            )
                            script_changed = (
                                current_script_sha256 is not None
                                and current_script_sha256 != initial_script_sha256
                            )
                        if not script_exists and not refusal_exists:
                            finish_reminder = (
                                f"Write {authored_script_path} before finishing. "
                                "If the plan is genuinely infeasible, write "
                                "plan_refusal.md with evidence instead."
                            )
                            messages.append(
                                self._tool_response_message(
                                    tool_call_id=call.get("id", ""),
                                    tool_name=completion_tool_name,
                                    content=finish_reminder,
                                )
                            )
                            messages.append(
                                {"role": "system", "content": finish_reminder}
                            )
                            continue
                        if not script_changed and not refusal_exists:
                            finish_reminder = (
                                f"Modify {authored_script_path} before finishing. The current "
                                "file still matches the seeded starter. If the "
                                "plan is genuinely infeasible, write "
                                "plan_refusal.md with evidence instead."
                            )
                            messages.append(
                                self._tool_response_message(
                                    tool_call_id=call.get("id", ""),
                                    tool_name=completion_tool_name,
                                    content=finish_reminder,
                                )
                            )
                            messages.append(
                                {"role": "system", "content": finish_reminder}
                            )
                            continue
                    missing_fields = [
                        field_name
                        for field_name in finish_fields
                        if field_name not in payload
                    ]
                    if missing_fields:
                        msg = (
                            f"{completion_tool_name} tool call is missing required output fields: "
                            + ", ".join(missing_fields)
                        )
                        raise ValueError(msg)
                    unmet_visual_requirement = (
                        self._get_visual_inspection_requirement_message(
                            policy=visual_policy,
                            media_paths=refresh_render_media_paths(),
                        )
                    )
                    if unmet_visual_requirement and node_type not in {
                        AgentName.BENCHMARK_REVIEWER,
                        AgentName.ENGINEER_EXECUTION_REVIEWER,
                    }:
                        messages.append(
                            self._tool_response_message(
                                tool_call_id=call.get("id", ""),
                                tool_name=completion_tool_name,
                                content=unmet_visual_requirement,
                            )
                        )
                        messages.append(
                            {"role": "system", "content": unmet_visual_requirement}
                        )
                        continue
                    return dspy.Prediction.from_completions(
                        {
                            field_name: [payload.get(field_name)]
                            for field_name in finish_fields
                        },
                        signature=signature_cls,
                    )

                tool = tool_fns.get(tool_name)
                if tool is None:
                    raise ValueError(f"Unknown tool requested: {tool_name}")

                try:
                    observation = tool(**payload)
                except Exception as err:
                    error_text = str(err).strip() or f"{tool_name} failed"
                    if _SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in error_text:
                        raise RuntimeError(error_text) from err
                    logger.warning(
                        "native_tool_call_failed",
                        node_type=str(node_type),
                        session_id=self.ctx.session_id,
                        tool_name=tool_name,
                        error=error_text,
                    )
                    messages.append(
                        self._tool_response_message(
                            tool_call_id=call.get("id", ""),
                            tool_name=tool_name,
                            content=f"{tool_name} failed: {error_text}",
                        )
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": self._get_runtime_prompt(
                                self._runtime_prompt_key(
                                    node_type, "tool_call_failed_recover"
                                ),
                                tool_name=tool_name,
                            ),
                        }
                    )
                    continue
                self._record_tool_usage(tool_name, observation)
                messages.append(
                    self._tool_response_message(
                        tool_call_id=call.get("id", ""),
                        tool_name=tool_name,
                        content=self._serialize_tool_observation(observation),
                    )
                )
                if requires_submit_plan and tool_name in submit_tool_names:
                    if self._submit_plan_succeeded(observation):
                        submit_plan_succeeded = True
                        messages.append(
                            {
                                "role": "system",
                                "content": self._get_runtime_prompt(
                                    self._runtime_prompt_key(
                                        node_type, "submit_succeeded_finish_now"
                                    )
                                ),
                            }
                        )
                    else:
                        error_text = self._submit_plan_error_message(observation)
                        if error_text:
                            if "CONTRADICTORY_CONSTRAINTS" in error_text:
                                terminal_submit_plan_rejection = True
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": (
                                            f"{submit_tool_name}() rejected terminal "
                                            "contradictory benchmark motion: "
                                            f"{error_text}. Stop retrying {submit_tool_name}() "
                                            "and let handoff validation fail closed."
                                        ),
                                    }
                                )
                            else:
                                messages.append(
                                    {
                                        "role": "system",
                                        "content": self._get_runtime_prompt(
                                            self._runtime_prompt_key(
                                                node_type,
                                                "submit_rejected_fix_and_retry",
                                            ),
                                            error_text=error_text,
                                        ),
                                    }
                                )
                messages.extend(
                    self._build_media_attachment_messages(
                        node_type=node_type,
                        tool_name=tool_name,
                        result=observation,
                    )
                )
                current_render_media_paths = refresh_render_media_paths()
                if (
                    current_render_media_paths
                    and visual_policy.required
                    and self._inspected_unique_media_path_count()
                    < visual_policy.min_images
                    and (iteration + 1) % visual_policy.reminder_interval == 0
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": self._build_visual_inspection_reminder(
                                policy=visual_policy,
                                media_paths=current_render_media_paths,
                            ),
                        }
                    )

        if requires_submit_plan and not submit_plan_succeeded:
            if terminal_submit_plan_rejection:
                return self._planner_autosubmit_prediction(
                    signature_cls=signature_cls,
                    finish_fields=finish_fields,
                    node_type=node_type,
                )
            submit_tool = next(
                (tool_fns[name] for name in submit_tool_names if name in tool_fns),
                None,
            )
            if submit_tool is not None:
                submission = submit_tool()
                if self._submit_plan_succeeded(submission):
                    return self._planner_autosubmit_prediction(
                        signature_cls=signature_cls,
                        finish_fields=finish_fields,
                        node_type=node_type,
                    )

        msg = (
            f"Native tool loop for {node_type.value} exhausted {max_iters} iterations."
        )
        raise RuntimeError(msg)

    def _max_iters_for_node(self, node_type: AgentName) -> int:
        return self.ctx.fs.policy.get_execution_policy(
            node_type
        ).native_tool_loop_max_iters

    def _dspy_timeout_for_node(self, node_type: AgentName) -> float:
        return float(self.ctx.fs.policy.get_execution_policy(node_type).timeout_seconds)

    def _get_tool_functions(
        self,
        tool_factory: Callable,
        db_callback: DatabaseCallbackHandler | None = None,
        node_name: AgentName | None = None,
    ) -> dict[str, Callable]:
        """Collects tool functions for DSPy compatibility."""
        tools = tool_factory(self.ctx.fs, self.ctx.session_id)
        tool_fns = {}
        live_reasoning_step_idx = 0

        def extract_live_thought(*args: Any, **kwargs: Any) -> str | None:
            """Try to pull a current-thought string from ReAct tool call payload."""
            direct_keys = ("thought", "reasoning", "reasoning_content")
            for key in direct_keys:
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

            for arg in args:
                if isinstance(arg, dict):
                    for key in direct_keys:
                        value = arg.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()

            return None

        for t in tools:
            # Now tools are already raw functions or wrapped in search_cots_catalog
            name = getattr(t, "name", t.__name__ if hasattr(t, "__name__") else str(t))

            import functools

            def make_traced(func, tool_name):
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    nonlocal live_reasoning_step_idx
                    reasoning_keys = ("thought", "reasoning", "reasoning_content")
                    sanitized_kwargs = dict(kwargs)

                    if db_callback and node_name:
                        live_thought = extract_live_thought(*args, **kwargs)
                        if live_thought:
                            db_callback.record_reasoning_text_sync(
                                node_name=str(node_name),
                                reasoning_text=live_thought,
                                step_index=live_reasoning_step_idx,
                                source="live_tool_loop",
                            )
                            live_reasoning_step_idx += 1
                    for key in reasoning_keys:
                        sanitized_kwargs.pop(key, None)

                    # WP10: Explicitly record tool start
                    trace_id = 0
                    if db_callback:
                        try:
                            # ReAct often passes complex objects, try to
                            # serialize or stringify
                            input_dict = {}
                            if args:
                                input_dict["args"] = [str(a) for a in args]
                            if sanitized_kwargs:
                                input_dict["kwargs"] = {
                                    k: str(v) for k, v in sanitized_kwargs.items()
                                }
                            input_str = json.dumps(input_dict)
                        except Exception:
                            input_str = str(args) + " " + str(kwargs)

                        # WP10: Special handling for common tools to ensure success
                        # in mocks
                        if tool_name == "write_file":
                            if "overwrite" not in sanitized_kwargs:
                                sanitized_kwargs["overwrite"] = True
                        elif tool_name == "edit_file":
                            # Ensure we don't fail on missing files if we can help it
                            pass

                        try:
                            # WP10: Use synchronous wrapper which handles loop isolation
                            trace_id = db_callback.record_tool_start_sync(
                                tool_name,
                                input_str,
                                force_block=tool_name.startswith("submit_"),
                            )
                        except Exception as e:
                            logger.warning("tool_start_trace_failed", error=str(e))

                    tool_timeout_seconds = 60.0
                    if tool_name in {"simulate", "validate"}:
                        # Physics/validation calls can legitimately exceed 60s in integration runs.
                        tool_timeout_seconds = float(
                            settings.dspy_program_timeout_seconds
                        )

                    try:
                        if asyncio.iscoroutinefunction(func):
                            # WP10: Use run_coroutine_threadsafe on the main loop
                            future = asyncio.run_coroutine_threadsafe(
                                func(*args, **sanitized_kwargs), self.ctx.main_loop
                            )
                            result = future.result(timeout=tool_timeout_seconds)
                        else:
                            result = func(*args, **sanitized_kwargs)

                        self._record_tool_usage(tool_name, result)

                        # WP10: Explicitly record tool success
                        if db_callback and trace_id:
                            db_callback.record_tool_end_sync(
                                trace_id,
                                self._serialize_tool_observation(result),
                                force_block=tool_name.startswith("submit_"),
                            )

                        return result
                    except Exception as e:
                        # WP10: Explicitly record tool error
                        if db_callback and trace_id:
                            db_callback.record_tool_end_sync(
                                trace_id,
                                str(e),
                                is_error=True,
                                force_block=tool_name.startswith("submit_"),
                            )
                        raise e

                return sync_wrapper

            wrapped = make_traced(t, name)
            wrapped.__name__ = name
            tool_fns[name] = wrapped
        return tool_fns

    def _build_media_attachment_messages(
        self,
        *,
        node_type: AgentName,
        tool_name: str,
        result: Any,
    ) -> list[dict[str, Any]]:
        if tool_name != "inspect_media" or not isinstance(
            result, MediaInspectionResult
        ):
            return []
        if not result.attached_to_model:
            return []

        attachment_urls = list(result.data_urls or [])
        if not attachment_urls and result.data_url:
            attachment_urls = [result.data_url]
        if not attachment_urls:
            return []

        with suppress(Exception):
            future = asyncio.run_coroutine_threadsafe(
                record_worker_events(
                    episode_id=self.ctx.episode_id,
                    events=[
                        LlmMediaAttachedEvent(
                            path=result.path,
                            mime_type=result.mime_type,
                            media_kind=result.media_kind,
                            node_name=node_type,
                            attached_media_count=len(attachment_urls),
                        )
                    ],
                ),
                self.ctx.main_loop,
            )
            future.result(timeout=5.0)

        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Visual evidence from {tool_name}('{result.path}'). "
                            "Inspect the attached media directly before your "
                            "next decision."
                        ),
                    },
                    *[
                        {
                            "type": "image_url",
                            "image_url": {"url": media_url},
                        }
                        for media_url in attachment_urls
                    ],
                ],
            }
        ]

    @staticmethod
    def _serialize_tool_observation(result: Any) -> str:
        """Serialize tool outputs to a parseable string for downstream gating."""
        with suppress(Exception):
            if hasattr(result, "model_dump"):
                dumped = result.model_dump(mode="json")
                return json.dumps(dumped)
            if (
                isinstance(result, (dict, list, bool, int, float, str))
                or result is None
            ):
                return json.dumps(result)
        return str(result)

    @staticmethod
    def _serialize_llm_output(output: Any) -> str | dict[str, Any] | list[Any]:
        """Serialize LM output payloads into structlog-friendly primitives."""
        if isinstance(output, (str, int, float, bool)) or output is None:
            return str(output)
        if isinstance(output, (dict, list)):
            return output
        with suppress(Exception):
            if hasattr(output, "model_dump"):
                return output.model_dump(mode="json")
        return str(output)

    @staticmethod
    def _extract_completion_tokens(usage: Any) -> int | None:
        """Extract output/completion tokens from usage payloads."""
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            with suppress(Exception):
                usage = usage.model_dump(mode="json")
        if not isinstance(usage, dict):
            return None

        for key in ("completion_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)

        total_tokens = usage.get("total_tokens")
        prompt_tokens = usage.get("prompt_tokens")
        if isinstance(total_tokens, (int, float)) and isinstance(
            prompt_tokens, (int, float)
        ):
            diff = int(total_tokens - prompt_tokens)
            if diff >= 0:
                return diff
        return None

    @staticmethod
    def _extract_prompt_tokens(usage: Any) -> int | None:
        """Extract prompt/input tokens from usage payloads."""
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            with suppress(Exception):
                usage = usage.model_dump(mode="json")
        if not isinstance(usage, dict):
            return None

        for key in ("prompt_tokens", "input_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
        return None

    @staticmethod
    def _extract_total_tokens(usage: Any) -> int | None:
        """Extract total tokens from usage payloads."""
        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            with suppress(Exception):
                usage = usage.model_dump(mode="json")
        if not isinstance(usage, dict):
            return None

        total = usage.get("total_tokens")
        if isinstance(total, int):
            return total
        if isinstance(total, float):
            return int(total)

        prompt = BaseNode._extract_prompt_tokens(usage)
        completion = BaseNode._extract_completion_tokens(usage)
        if prompt is not None and completion is not None:
            return prompt + completion
        return None

    @staticmethod
    def _extract_cost_usd(usage: Any, direct_cost: Any) -> float | None:
        """Extract per-call USD cost from usage payloads or direct cost fields."""
        if isinstance(direct_cost, int | float):
            return float(direct_cost)

        if usage is None:
            return None
        if hasattr(usage, "model_dump"):
            with suppress(Exception):
                usage = usage.model_dump(mode="json")
        if not isinstance(usage, dict):
            return None

        usage_cost = usage.get("cost")
        if isinstance(usage_cost, int | float):
            return float(usage_cost)
        return None

    @staticmethod
    def _extract_latency_ms(response: Any) -> float | None:
        """Extract per-call latency in milliseconds from provider response."""
        if response is None:
            return None

        response_model = None
        with suppress(Exception):
            response_model = ProviderResponseEnvelope.model_validate(response)
        if response_model is None:
            return None

        response_ms = response_model.response_ms
        if isinstance(response_ms, (int, float)):
            return float(response_ms)

        hidden_params = response_model.hidden_params
        if isinstance(hidden_params, dict):
            hidden_response_ms = hidden_params.get("response_ms")
            if isinstance(hidden_response_ms, (int, float)):
                return float(hidden_response_ms)
        return None

    @classmethod
    def _compute_tpm(cls, *, usage: Any, response: Any) -> float | None:
        """Compute tokens-per-minute using completion/output tokens and latency."""
        completion_tokens = cls._extract_completion_tokens(usage)
        latency_ms = cls._extract_latency_ms(response)
        if completion_tokens is None or latency_ms is None or latency_ms <= 0:
            return None
        return round((completion_tokens * 60000.0) / latency_ms, 2)

    @staticmethod
    def _extract_reasoning_content(response: Any) -> list[str]:
        """Extract provider-native reasoning content (for example litellm message.reasoning_content)."""
        chunks: list[str] = []
        if response is None:
            return chunks

        response_model = None
        with suppress(Exception):
            response_model = ProviderResponseEnvelope.model_validate(response)
        if response_model and response_model.choices:
            for choice in response_model.choices:
                message_model = None
                with suppress(Exception):
                    message_model = NativeProviderMessage.model_validate(choice.message)
                if message_model is None:
                    continue
                value = message_model.reasoning_content
                if isinstance(value, str) and value.strip():
                    chunks.append(value.strip())
            return chunks

        message_model = None
        with suppress(Exception):
            message_model = NativeProviderMessage.model_validate(response)
        if message_model is not None:
            value = message_model.reasoning_content
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())

        return chunks

    def _log_lm_history_delta(
        self,
        *,
        node_type: AgentName,
        attempt: int,
        history_start_idx: int | None,
        db_callback: DatabaseCallbackHandler | None = None,
    ) -> None:
        """Emit one log event per newly completed LM generation."""
        if history_start_idx is None:
            return

        history = getattr(self.ctx.dspy_lm, "history", None)
        if not isinstance(history, list):
            return
        if history_start_idx >= len(history):
            return

        for absolute_idx, entry in enumerate(
            history[history_start_idx:], history_start_idx + 1
        ):
            if not isinstance(entry, dict):
                logger.info(
                    "llm_response_generated",
                    node_type=str(node_type),
                    session_id=self.ctx.session_id,
                    attempt=attempt,
                    lm_call_index=absolute_idx,
                    output=str(entry),
                )
                continue

            raw_outputs = entry.get("outputs")
            if isinstance(raw_outputs, list):
                outputs = [self._serialize_llm_output(item) for item in raw_outputs]
            elif raw_outputs is None:
                outputs = []
            else:
                outputs = [self._serialize_llm_output(raw_outputs)]

            logger.info(
                "llm_response_generated",
                node_type=str(node_type),
                session_id=self.ctx.session_id,
                attempt=attempt,
                lm_call_index=absolute_idx,
                model=entry.get("model"),
                response_model=entry.get("response_model"),
                usage=entry.get("usage"),
                cost=entry.get("cost"),
                latency_ms=self._extract_latency_ms(entry.get("response")),
                tpm=self._compute_tpm(
                    usage=entry.get("usage"),
                    response=entry.get("response"),
                ),
                outputs=outputs,
            )

            report_usage_to_current_observation(
                usage=entry.get("usage"),
                model=entry.get("response_model") or entry.get("model"),
                cost=entry.get("cost"),
            )

            prompt_tokens = self._extract_prompt_tokens(entry.get("usage"))
            if prompt_tokens is not None and self.ctx.episode_id:
                with suppress(Exception):
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        update_episode_context_usage(
                            episode_id=self.ctx.episode_id,
                            used_tokens=prompt_tokens,
                            max_tokens=settings.context_compaction_threshold_tokens,
                        )
                    )
            if self.ctx.episode_id:
                with suppress(Exception):
                    usage = entry.get("usage")
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        accumulate_episode_credit_usage(
                            episode_id=self.ctx.episode_id,
                            input_tokens=self._extract_prompt_tokens(usage),
                            output_tokens=self._extract_completion_tokens(usage),
                            total_tokens=self._extract_total_tokens(usage),
                            cost_usd=self._extract_cost_usd(
                                usage,
                                entry.get("cost"),
                            ),
                        )
                    )

            if not db_callback:
                continue

            # Emit live reasoning traces from LM outputs so UI can show
            # intermediate thinking even before node completion.
            for output in outputs:
                reasoning_chunks: list[str] = []
                if isinstance(output, str):
                    for key in ("Thought", "Reasoning"):
                        matches = re.findall(
                            rf"{key}\s*:\s*(.+?)(?=\n[A-Za-z_]+\s*:|\Z)",
                            output,
                            flags=re.IGNORECASE | re.DOTALL,
                        )
                        reasoning_chunks.extend(
                            [
                                m.strip()
                                for m in matches
                                if isinstance(m, str) and m.strip()
                            ]
                        )
                elif isinstance(output, dict):
                    for key in ("thought", "reasoning", "reasoning_content"):
                        value = output.get(key)
                        if isinstance(value, str) and value.strip():
                            reasoning_chunks.append(value.strip())

                for chunk in reasoning_chunks:
                    text = chunk.strip()
                    if not text:
                        continue
                    if len(text) > 2000:
                        text = text[:2000] + "..."
                    db_callback.record_reasoning_text_sync(
                        node_name=str(node_type),
                        reasoning_text=text,
                        source="lm_history",
                    )

            provider_reasoning = self._extract_reasoning_content(entry.get("response"))
            for chunk in provider_reasoning:
                text = chunk.strip()
                if not text:
                    continue
                if len(text) > 2000:
                    text = text[:2000] + "..."
                db_callback.record_reasoning_text_sync(
                    node_name=str(node_type),
                    reasoning_text=text,
                    source="lm_history",
                )

    def _get_database_recorder(self, session_id: str) -> DatabaseCallbackHandler:
        return self.ctx.get_database_recorder(session_id)

    async def _get_latest_trace_id(self, recorder: DatabaseCallbackHandler) -> int:
        """Return latest trace id for an episode (0 if none)."""
        async with recorder.session_factory() as db:
            result = await db.execute(
                select(func.max(Trace.id)).where(
                    Trace.episode_id == recorder.episode_id
                )
            )
            latest = result.scalar_one_or_none()
            return int(latest or 0)

    async def _count_reasoning_traces_since(
        self,
        recorder: DatabaseCallbackHandler,
        *,
        node_type: AgentName,
        min_trace_id: int,
    ) -> int:
        """Count persisted reasoning traces for a node after a trace-id watermark."""
        async with recorder.session_factory() as db:
            result = await db.execute(
                select(func.count(Trace.id)).where(
                    Trace.episode_id == recorder.episode_id,
                    Trace.trace_type == TraceType.LLM_END,
                    Trace.name == str(node_type),
                    Trace.id > min_trace_id,
                )
            )
            return int(result.scalar_one() or 0)

    async def _get_latest_submit_plan_result(
        self, expected_node_type: AgentName
    ) -> tuple[Any | None, str | None]:
        """
        Read the latest role-scoped planner submission result from persisted traces.

        Returns (PlannerSubmissionResult | None, error_message | None).
        """
        from sqlalchemy import select

        from shared.models.schemas import PlannerSubmissionResult

        episode_id = self.ctx.episode_id
        if not episode_id:
            return None, "missing episode_id for submission trace lookup"

        submission_tool_names = self._planner_submission_tool_names(expected_node_type)
        submission_tool_name = submission_tool_names[0]
        recorder = self.ctx.get_database_recorder(episode_id)
        async with recorder.session_factory() as db:
            query = (
                select(Trace)
                .where(
                    Trace.episode_id == recorder.episode_id,
                    Trace.trace_type == TraceType.TOOL_START,
                    Trace.name.in_(submission_tool_names),
                )
                .order_by(Trace.id.desc())
                .limit(1)
            )
            result = await db.execute(query)
            trace_row = result.scalars().first()

        if trace_row is None:
            return None, f"{submission_tool_name}() tool trace not found"

        metadata_vars = trace_row.metadata_vars or {}
        observation_raw = metadata_vars.get("observation")
        if not observation_raw:
            error_raw = metadata_vars.get("error")
            if isinstance(error_raw, str) and error_raw.strip():
                return None, (
                    f"{submission_tool_name}() execution failed: {error_raw.strip()}"
                )
            return None, f"{submission_tool_name}() observation is missing"

        payload: dict[str, Any] | None = None
        if isinstance(observation_raw, dict):
            payload = observation_raw
        elif isinstance(observation_raw, str):
            text = observation_raw.strip()
            with suppress(Exception):
                parsed_json = json.loads(text)
                if isinstance(parsed_json, dict):
                    payload = parsed_json
            with suppress(Exception):
                if payload is None:
                    parsed = ast.literal_eval(text)
                    if isinstance(parsed, dict):
                        payload = parsed

        if payload is None:
            return None, (
                f"{submission_tool_name}() observation is not a structured payload"
            )

        with suppress(Exception):
            submission = PlannerSubmissionResult.model_validate(payload)
            if submission.node_type != expected_node_type:
                return (
                    None,
                    f"{submission_tool_name}() node_type mismatch: "
                    f"expected {expected_node_type.value}, got {submission.node_type.value}",
                )
            return submission, None
        return None, (
            f"{submission_tool_name}() observation does not match "
            "PlannerSubmissionResult"
        )

    async def _get_latest_tool_trace_metadata(
        self, tool_name: str
    ) -> tuple[TraceMetadata | None, str | None]:
        """
        Read the latest TOOL_START trace metadata for a given tool name.

        Returns (TraceMetadata | None, error_message | None).
        """
        from sqlalchemy import select

        episode_id = self.ctx.episode_id
        if not episode_id:
            return None, "missing episode_id for tool trace lookup"

        recorder = self.ctx.get_database_recorder(episode_id)
        async with recorder.session_factory() as db:
            query = (
                select(Trace)
                .where(
                    Trace.episode_id == recorder.episode_id,
                    Trace.trace_type == TraceType.TOOL_START,
                    Trace.name == tool_name,
                )
                .order_by(Trace.id.desc())
                .limit(1)
            )
            result = await db.execute(query)
            trace_row = result.scalars().first()

        if trace_row is None:
            return None, f"{tool_name}() tool trace not found"

        metadata = TraceMetadata.model_validate(trace_row.metadata_vars or {})
        if metadata.error and metadata.error.strip():
            return None, f"{tool_name}() execution failed: {metadata.error.strip()}"
        if not metadata.observation or not metadata.observation.strip():
            return None, f"{tool_name}() observation is missing"
        return metadata, None

    def _get_skills_context(self) -> str:
        # Use the active skill tree first. If a session overlay is present, it
        # takes precedence over the canonical checked-in tree.
        from shared.skills import iter_skill_catalog_entries

        skills = [name for name, _ in iter_skill_catalog_entries()]
        if not skills:
            return ""
        return "\n".join(f"- {s}" for s in skills)

    async def _get_steer_context(self, messages: list[Any]) -> str:
        if not messages:
            return ""
        last_msg = messages[-1]
        steer_data = (
            last_msg.additional_kwargs.get("steerability")
            if hasattr(last_msg, "additional_kwargs")
            else None
        )

        lines = []

        # T015: Parse @file:line-line from message content if not
        # already in code_references
        content = last_msg.content if isinstance(last_msg.content, str) else ""
        # Matches @path/to/file.ext:start-end
        matches = re.finditer(r"@([\w\./\-]+\.\w+):(\d+)-(\d+)", content)
        parsed_refs = []
        for match in matches:
            parsed_refs.append(
                CodeReference(
                    file_path=match.group(1),
                    start_line=int(match.group(2)),
                    end_line=int(match.group(3)),
                )
            )

        if not steer_data and not parsed_refs:
            return ""

        steer_data = steer_data or {}
        raw_code_refs = steer_data.get("code_references", [])
        code_refs = [
            CodeReference.model_validate(r) if isinstance(r, dict) else r
            for r in raw_code_refs
        ] + parsed_refs

        if steer_data.get("selections"):
            lines.append("Geometric Selections:")
            for sel in steer_data["selections"]:
                center_str = ", ".join([f"{v:.2f}" for v in sel["center"]])
                normal_str = ""
                if sel.get("normal"):
                    normal_val = ", ".join([f"{v:.2f}" for v in sel["normal"]])
                    normal_str = f", Normal: ({normal_val})"
                lines.append(
                    f"  - Level: {sel['level']}, ID: {sel['target_id']}, "
                    f"Center: ({center_str}){normal_str}"
                )

        if code_refs:
            lines.append("Code References:")
            for ref in code_refs:
                file_path = ref.file_path
                start = ref.start_line
                end = ref.end_line
                try:
                    # Resolve snippet from worker
                    file_content = await self.ctx.fs.read_file(file_path)
                    file_lines = file_content.splitlines()
                    if start < 1 or end > len(file_lines) or start > end:
                        lines.append(
                            f"  - File: {file_path}, Lines: {start}-{end} "
                            f"[ERROR: Invalid line range. "
                            f"File has {len(file_lines)} lines]"
                        )
                    else:
                        snippet = "\n".join(file_lines[start - 1 : end])
                        lines.append(f"  - File: {file_path}, Lines: {start}-{end}:")
                        lines.append("```python")
                        lines.append(snippet)
                        lines.append("```")
                except Exception as e:
                    lines.append(
                        f"  - File: {file_path}, Lines: {start}-{end} [ERROR: {e}]"
                    )

        if steer_data.get("mentions"):
            lines.append(f"Mentions: {', '.join(steer_data['mentions'])}")

        return "\n".join(lines)

    async def _run_program(
        self,
        program_cls: type[dspy.Module],
        signature_cls: type[dspy.Signature],
        state: "AgentState",
        inputs: dict[str, Any],
        tool_factory: Callable,
        validate_files: list[str],
        node_type: AgentName,
        max_retries: int | None = None,
        record_node_lifecycle: bool = True,
    ) -> tuple[Any, dict[str, Any], str]:
        """
        Reusable execution loop for DSPy nodes with retries and validation.
        Returns (prediction, artifacts, journal_entry).
        """
        if max_retries is None:
            # Fail closed on repeated invalid/malformed outputs instead of
            # retrying until the hard timeout window is exhausted.
            max_retries = max(1, int(settings.dspy_program_max_retries))

        from controller.agent.dspy_utils import WorkerInterpreter
        from worker_heavy.utils.file_validation import validate_node_output

        # Prepare explicit DB logger for UI events
        db_callback = None
        episode_id = getattr(state, "episode_id", None)

        if not episode_id:
            # Try session.session_id (BenchmarkGeneratorState) or self.ctx.episode_id
            session = getattr(state, "session", None)
            if session:
                episode_id = getattr(session, "session_id", None)

            if not episode_id:
                episode_id = self.ctx.episode_id

        if episode_id and str(episode_id).strip():
            db_callback = DatabaseCallbackHandler(
                episode_id=str(episode_id), loop=self.ctx.main_loop
            )

        interpreter = WorkerInterpreter(
            worker_client=self.ctx.worker_client,
            session_id=self.ctx.session_id,
            episode_id=self.ctx.episode_id,
        )
        tool_fns = self._get_tool_functions(
            tool_factory,
            db_callback=db_callback,
            node_name=node_type,
        )

        # WP07: Inject system instructions from prompts.yaml into signature
        # Template names are now standardized to match node_type or explicit mappings
        instructions = self.ctx.pm.render(node_type, backend_family="api_based")
        if instructions:
            current_instr = signature_cls.instructions
            if current_instr:
                signature_cls = signature_cls.with_instructions(
                    f"{instructions}\n\n{current_instr}"
                )
            else:
                signature_cls = signature_cls.with_instructions(instructions)

        use_native_tool_loop = self._should_use_native_tool_loop(
            node_type=node_type,
            program_cls=program_cls,
        )

        program = None
        if program_cls is dspy.ReAct and not use_native_tool_loop:
            max_iters = self._max_iters_for_node(node_type)
            program = program_cls(
                signature_cls, tools=list(tool_fns.values()), max_iters=max_iters
            )
        elif not use_native_tool_loop:
            program = program_cls(signature_cls, tools=list(tool_fns.values()))

        # WP07: Try to load compiled prompt if available
        if not use_native_tool_loop:
            self.ctx.pm.load_compiled_program(node_type, program)

        # WP08: Set node_type on mock LM if available for explicit lookup
        if hasattr(self.ctx.dspy_lm, "node_type"):
            self.ctx.dspy_lm.node_type = node_type

        retry_count = 0
        journal_entry = ""
        prediction = None
        artifacts = {}

        dspy_timeout = self._dspy_timeout_for_node(node_type)

        try:
            if episode_id:
                await mark_episode_execution_window_start(episode_id)
            while retry_count < max_retries:
                try:
                    hard_fail = await evaluate_agent_hard_fail(
                        agent_name=node_type,
                        episode_id=episode_id,
                        turn_count=getattr(state, "turn_count", None),
                    )
                    if hard_fail.should_fail:
                        raise AgentHardFailError(
                            hard_fail.code or "hard_fail",
                            hard_fail.message or "Agent hard-fail limit reached.",
                        )

                    trace_watermark = (
                        await self._get_latest_trace_id(db_callback)
                        if db_callback
                        else 0
                    )
                    self._reset_tool_usage_tracking()
                    # WP10: Explicitly record node start for UI
                    if db_callback and record_node_lifecycle:
                        node_input = (
                            inputs.get("task")
                            or inputs.get("prompt")
                            or inputs.get("journal")
                            or ""
                        )
                        await db_callback.record_node_start(
                            node_type, input_data=str(node_input)
                        )

                    adapter = self._create_dspy_adapter(
                        use_native_function_calling=use_native_tool_loop
                    )
                    logger.info(
                        "dspy_adapter_selected",
                        session_id=self.ctx.session_id,
                        episode_id=episode_id,
                        node_type=str(node_type),
                        runtime_mode=(
                            "native_tool_loop" if use_native_tool_loop else "react"
                        ),
                        adapter=type(adapter).__name__,
                        use_json_adapter_fallback=getattr(
                            adapter, "use_json_adapter_fallback", None
                        ),
                        use_native_function_calling=getattr(
                            adapter, "use_native_function_calling", None
                        ),
                    )
                    with dspy.settings.context(lm=self.ctx.dspy_lm, adapter=adapter):
                        logger.info(
                            f"{node_type}_dspy_invoke_start",
                            session_id=self.ctx.session_id,
                        )
                        lm_history = getattr(self.ctx.dspy_lm, "history", None)
                        history_start_idx = (
                            len(lm_history) if isinstance(lm_history, list) else None
                        )
                        history_stream_stop = asyncio.Event()
                        history_stream_task: asyncio.Task | None = None

                        final_history_idx = history_start_idx

                        async def stream_lm_history_live(start_idx: int | None) -> None:
                            """Continuously flush newly generated LM history rows."""
                            nonlocal final_history_idx
                            if start_idx is None:
                                return
                            next_idx = start_idx
                            while not history_stream_stop.is_set():
                                self._log_lm_history_delta(
                                    node_type=node_type,
                                    attempt=retry_count + 1,
                                    history_start_idx=next_idx,
                                    db_callback=db_callback,
                                )
                                current_history = getattr(
                                    self.ctx.dspy_lm, "history", None
                                )
                                if isinstance(current_history, list):
                                    next_idx = len(current_history)
                                    final_history_idx = next_idx
                                await asyncio.sleep(0.2)

                        history_stream_task = asyncio.create_task(
                            stream_lm_history_live(history_start_idx)
                        )
                        # Add a timeout to prevent infinite hangs in DSPy ReAct
                        try:
                            if use_native_tool_loop:
                                max_iters = self._max_iters_for_node(node_type)
                                (
                                    visual_policy,
                                    render_media_paths,
                                ) = await self._get_visual_inspection_context(node_type)
                                prediction = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        self._run_native_tool_loop,
                                        signature_cls=signature_cls,
                                        inputs=inputs,
                                        tool_fns=tool_fns,
                                        node_type=node_type,
                                        max_iters=max_iters,
                                        visual_policy=visual_policy,
                                        render_media_paths=render_media_paths,
                                        db_callback=db_callback,
                                    ),
                                    timeout=dspy_timeout,
                                )
                            else:
                                prediction = await asyncio.wait_for(
                                    asyncio.to_thread(program, **inputs),
                                    timeout=dspy_timeout,
                                )
                            logger.info(
                                f"{node_type}_raw_prediction",
                                prediction=str(prediction),
                                prediction_type=str(type(prediction)),
                                session_id=self.ctx.session_id,
                            )
                        except TimeoutError as err:
                            logger.error(
                                f"{node_type}_dspy_timeout",
                                session_id=self.ctx.session_id,
                            )
                            msg = (
                                f"DSPy program {node_type} "
                                f"timed out after {dspy_timeout}s"
                            )
                            raise RuntimeError(msg) from err
                        finally:
                            history_stream_stop.set()
                            if history_stream_task:
                                with suppress(Exception):
                                    await history_stream_task
                            self._log_lm_history_delta(
                                node_type=node_type,
                                attempt=retry_count + 1,
                                history_start_idx=final_history_idx,
                                db_callback=db_callback,
                            )
                        logger.info(
                            f"{node_type}_dspy_invoke_complete",
                            session_id=self.ctx.session_id,
                        )

                    # WP10: Explicitly record node end for UI
                    if db_callback and record_node_lifecycle:
                        await db_callback.record_node_end(
                            node_type,
                            output_data=str(prediction),
                            output_obj=prediction,
                        )

                    async def _read_validation_artifact(path: str) -> str | None:
                        content = await self.ctx.fs.read_file_optional(
                            path, bypass_agent_permissions=True
                        )
                        if isinstance(content, str) and content.strip():
                            return content

                        try:
                            episode_uuid = resolve_episode_id(episode_id)
                        except Exception:
                            return None

                        session_factory = get_sessionmaker()
                        async with session_factory() as db:
                            result = await db.execute(
                                select(Asset.content).where(
                                    Asset.episode_id == episode_uuid,
                                    Asset.s3_path == path,
                                )
                            )
                            persisted_content = result.scalar_one_or_none()

                        if (
                            isinstance(persisted_content, str)
                            and persisted_content.strip()
                        ):
                            return persisted_content
                        return None

                    results = await asyncio.gather(
                        *[_read_validation_artifact(f) for f in validate_files]
                    )
                    artifacts = {
                        f: res
                        for f, res in zip(validate_files, results, strict=False)
                        if res
                    }

                    is_valid, validation_errors = validate_node_output(
                        node_type, artifacts
                    )

                    if not is_valid:
                        logger.warning(
                            f"{node_type}_validation_failed", errors=validation_errors
                        )
                        retry_count += 1
                        if retry_count >= max_retries:
                            # Record the last (invalid) attempt for UI before failing
                            if db_callback and prediction:
                                async with db_callback.session_factory() as db:
                                    trace_obj = Trace(
                                        episode_id=db_callback.episode_id,
                                        trace_type=TraceType.ERROR,
                                        name=f"{node_type}_validation_error",
                                        content=(
                                            f"Validation errors: {validation_errors}"
                                        ),
                                        metadata_vars={"prediction": str(prediction)},
                                    )
                                    db.add(trace_obj)
                                    await db.commit()

                            raise ValueError(
                                f"Node {node_type} failed to produce valid "
                                f"output after {max_retries} retries. "
                                f"Errors: {validation_errors}"
                            )
                        await asyncio.sleep(1)  # Backoff to prevent log explosion
                        continue

                    if settings.require_reasoning_traces and db_callback:
                        reasoning_count = await self._count_reasoning_traces_since(
                            db_callback,
                            node_type=node_type,
                            min_trace_id=trace_watermark,
                        )
                        if reasoning_count == 0:
                            logger.error(
                                "reasoning_telemetry_missing",
                                node_type=str(node_type),
                                episode_id=str(episode_id),
                                session_id=str(
                                    episode_id
                                ),  # session_id is episode_id here
                                attempt=retry_count + 1,
                            )
                            retry_count += 1
                            if retry_count >= max_retries:
                                raise ValueError(
                                    f"Node {node_type} produced no reasoning traces "
                                    "while REQUIRE_REASONING_TRACES is enabled."
                                )
                            await asyncio.sleep(1)
                            continue

                    return prediction, artifacts, journal_entry

                except AgentHardFailError:
                    raise
                except Exception as err:
                    if _is_transient_provider_rate_error(err):
                        logger.error(
                            f"{node_type}_dspy_rate_limited",
                            session_id=self.ctx.session_id,
                            error=str(err),
                            retry_count=retry_count + 1,
                            max_retries=max_retries,
                        )
                        raise RuntimeError(str(err)) from err
                    if _SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in str(err):
                        # Fail-fast for infra retry exhaustion; do not continue
                        # node-level retry loops.
                        raise RuntimeError(str(err)) from err
                    last_lm_preview = None
                    lm_history = getattr(self.ctx.dspy_lm, "history", None)
                    if isinstance(lm_history, list) and lm_history:
                        last_entry = lm_history[-1]
                        if isinstance(last_entry, dict):
                            last_lm_preview = str(last_entry.get("response"))[:600]
                    logger.error(
                        f"{node_type}_dspy_failed",
                        session_id=self.ctx.session_id,
                        error=str(err),
                        retry_count=retry_count + 1,
                        max_retries=max_retries,
                        last_lm_preview=last_lm_preview,
                    )
                    journal_entry += f"\n[System Error] {err}"
                    retry_count += 1
                    await asyncio.sleep(1)  # Backoff to prevent log explosion

            journal_entry += "\nMax retries reached."
            return None, artifacts, journal_entry

        finally:
            interpreter.shutdown()
