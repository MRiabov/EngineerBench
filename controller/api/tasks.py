import asyncio
import datetime
import hashlib
import os
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

import boto3
import structlog
from langchain_core.messages import HumanMessage

from controller.agent.initialization import (
    initialize_agent_files,
    seed_manufacturing_config,
)
from controller.agent.review_handover import validate_approved_benchmark_bundle
from controller.agent.state import AgentStatus
from controller.api.manager import task_tracker
from controller.clients.backend import RemoteFilesystemBackend
from controller.clients.worker import WorkerClient
from controller.config.settings import settings
from controller.graph.agent import create_agent_graph
from controller.middleware.remote_fs import RemoteFilesystemMiddleware
from controller.observability.database import DatabaseCallbackHandler
from controller.observability.langfuse import (
    attach_session_to_current_trace,
    start_root_span,
)
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Episode, Trace
from shared.enums import (
    AgentName,
    AssetType,
    EntryFailureDisposition,
    EpisodeStatus,
    FailureClass,
    TerminalReason,
    TraceType,
)
from shared.logging import get_logger
from shared.models.schemas import (
    EntryValidationContext,
    EntryValidationError,
    EpisodeMetadata,
)
from shared.script_contracts import authored_script_path_for_agent
from shared.workers.schema import ReviewManifest

logger = get_logger(__name__)
WORKER_LIGHT_URL = settings.worker_light_url
SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER = "SYSTEM_TOOL_RETRY_EXHAUSTED"


def _is_planner_agent(agent_name: AgentName) -> bool:
    return agent_name in {
        AgentName.ENGINEER_PLANNER,
        AgentName.BENCHMARK_PLANNER,
    }


def _is_solution_workflow_agent(agent_name: AgentName) -> bool:
    return agent_name in {
        AgentName.ENGINEER_PLANNER,
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_PLAN_REVIEWER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }


def _extract_result_field(result: Any, key: str) -> Any | None:
    if isinstance(result, dict):
        return result.get(key)
    return getattr(result, key, None)


def _result_status_lower(result: Any) -> str:
    raw_status = _extract_result_field(result, "status")
    if raw_status is None:
        return ""
    if hasattr(raw_status, "value"):
        raw_status = raw_status.value
    return str(raw_status).strip().lower()


def _result_feedback(result: Any) -> str:
    raw_feedback = _extract_result_field(result, "feedback")
    if raw_feedback is None:
        raw_feedback = _extract_result_field(result, "review_feedback")
    return str(raw_feedback or "").strip()


def _is_failed_result(result: Any) -> bool:
    status = _result_status_lower(result)
    if status in {
        AgentStatus.FAILED.value,
        AgentStatus.PLAN_REJECTED.value,
        AgentStatus.CODE_REJECTED.value,
    }:
        return True
    return bool(_extract_result_field(result, "entry_validation_terminal"))


def _extract_session_validation_logs(result: Any) -> list[str]:
    session = _extract_result_field(result, "session")
    raw_logs = None
    if isinstance(session, dict):
        raw_logs = session.get("validation_logs")
    elif session is not None:
        raw_logs = getattr(session, "validation_logs", None)

    if not isinstance(raw_logs, list):
        return []
    return [str(log) for log in raw_logs if str(log).strip()]


def _derive_solution_terminal_metadata(
    *,
    result: Any,
    result_feedback: str,
    terminal_status: EpisodeStatus,
    system_retry_exhausted: bool = False,
) -> tuple[TerminalReason | None, FailureClass | None, str | None]:
    if system_retry_exhausted:
        return (
            TerminalReason.SYSTEM_TOOL_RETRY_EXHAUSTED,
            FailureClass.INFRA_DEVOPS_FAILURE,
            SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER,
        )

    if terminal_status == EpisodeStatus.COMPLETED:
        return TerminalReason.APPROVED, None, None

    feedback = (result_feedback or "").strip()
    normalized = feedback.lower()

    if (
        feedback.startswith("ENTRY_VALIDATION_FAILED[")
        or "handoff blocked" in normalized
    ):
        return (
            TerminalReason.HANDOFF_INVARIANT_VIOLATION,
            FailureClass.AGENT_SEMANTIC_FAILURE,
            feedback or "Solution handoff blocked.",
        )

    if "rejected" in normalized and "review" in normalized:
        return (
            TerminalReason.REJECTED_BY_REVIEW,
            FailureClass.AGENT_QUALITY_FAILURE,
            feedback or "Solution rejected by review.",
        )

    if "timeout" in normalized:
        return (
            TerminalReason.TIMEOUT,
            FailureClass.INFRA_DEVOPS_FAILURE,
            feedback or "Solution run timed out.",
        )

    if any(term in normalized for term in ("connection", "worker", "http", "network")):
        return (
            TerminalReason.INFRA_ERROR,
            FailureClass.INFRA_DEVOPS_FAILURE,
            feedback or "Solution run hit an infrastructure error.",
        )

    return (
        TerminalReason.INTERNAL_ERROR,
        FailureClass.APPLICATION_LOGIC_FAILURE,
        feedback or "Solution run failed.",
    )


_BENCHMARK_COPY_TEXT_EXTENSIONS = (
    ".json",
    ".md",
    ".mjcf",
    ".py",
    ".step",
    ".stp",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
)


def _is_text_benchmark_artifact(path: str) -> bool:
    lower_path = path.lower()
    return lower_path.endswith(_BENCHMARK_COPY_TEXT_EXTENSIONS)


def _benchmark_artifact_paths(review_manifest: ReviewManifest) -> list[str]:
    paths: list[str] = []
    has_static_render_images = any(
        Path(path).suffix.lower() in {".png", ".jpg", ".jpeg"}
        for path in review_manifest.renders
    )
    for path in (
        review_manifest.script_path,
        "benchmark_definition.yaml",
        "benchmark_assembly_definition.yaml",
        ".manifests/benchmark_plan_review_manifest.json",
        ".manifests/benchmark_review_manifest.json",
        "validation_results.json",
        "simulation_result.json",
        review_manifest.mjcf_path,
        review_manifest.cad_path,
        *review_manifest.renders,
        review_manifest.objectives_path,
        review_manifest.assembly_definition_path,
    ):
        if path and path not in paths:
            paths.append(path)
    if has_static_render_images:
        for manifest_path in sorted(
            {
                str(Path(path).parent / "render_manifest.json")
                for path in review_manifest.renders
                if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg"}
            }
        ):
            if manifest_path not in paths:
                paths.append(manifest_path)
    return paths


async def _copy_approved_benchmark_artifact(
    *,
    source_client: WorkerClient,
    destination_client: WorkerClient,
    path: str,
) -> None:
    if _is_text_benchmark_artifact(path):
        content = await source_client.read_file(path, bypass_agent_permissions=True)
        if not await destination_client.write_file(
            path,
            content,
            overwrite=True,
            bypass_agent_permissions=True,
        ):
            raise RuntimeError(f"failed to write benchmark artifact: {path}")
        return

    content = await source_client.read_file_binary(
        path,
        bypass_agent_permissions=True,
    )
    if not await destination_client.upload_file(
        path,
        content,
        bypass_agent_permissions=True,
    ):
        raise RuntimeError(f"failed to upload benchmark artifact: {path}")


async def _copy_approved_benchmark_bundle(
    *,
    source_client: WorkerClient,
    destination_client: WorkerClient,
    review_manifest: ReviewManifest,
) -> None:
    artifact_paths = _benchmark_artifact_paths(review_manifest)
    if artifact_paths:
        artifact_blobs = await source_client.read_files_binary(
            artifact_paths, bypass_agent_permissions=True
        )
        missing_paths = [path for path in artifact_paths if path not in artifact_blobs]
        if missing_paths:
            raise RuntimeError(
                "benchmark artifact missing from source workspace: "
                + ", ".join(sorted(missing_paths))
            )

        batch_uploads = [
            (path, artifact_blobs[path])
            for path in artifact_paths
            if path in artifact_blobs
        ]
        if not await destination_client.upload_files(
            batch_uploads,
            bypass_agent_permissions=True,
        ):
            raise RuntimeError("failed to upload approved benchmark bundle")

        for path in artifact_paths:
            logger.info(
                "copied_approved_benchmark_artifact",
                source_session_id=source_client.session_id,
                destination_session_id=destination_client.session_id,
                path=path,
            )

    root_manifest_path = "renders/render_manifest.json"
    alias_paths = (
        "renders/engineer_plan_renders/render_manifest.json",
        "renders/benchmark_renders/render_manifest.json",
    )
    root_manifest = await source_client.read_file_optional(
        root_manifest_path, bypass_agent_permissions=True
    )
    if root_manifest is not None:
        if not await destination_client.upload_files(
            [(alias_path, root_manifest.encode("utf-8")) for alias_path in alias_paths],
            bypass_agent_permissions=True,
        ):
            raise RuntimeError("failed to copy approved benchmark render manifest")
        for alias_path in alias_paths:
            logger.info(
                "copied_approved_benchmark_artifact",
                source_session_id=source_client.session_id,
                destination_session_id=destination_client.session_id,
                path=alias_path,
                copied_from=root_manifest_path,
            )


async def _fail_episode_before_graph_start(
    *,
    db,
    episode: Episode,
    episode_id: uuid.UUID,
    session_id: str,
    reason: str,
    benchmark_id: str | None,
) -> None:
    metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
    if benchmark_id:
        metadata.benchmark_id = benchmark_id
    metadata.detailed_status = EpisodeStatus.FAILED.value
    metadata.terminal_reason = TerminalReason.HANDOFF_INVARIANT_VIOLATION
    metadata.failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
    metadata.error = reason
    metadata.validation_logs = list(
        dict.fromkeys(
            [
                *metadata.validation_logs,
                f"Benchmark handoff blocked: {reason}",
            ]
        )
    )
    episode.status = EpisodeStatus.FAILED
    episode.metadata_vars = metadata.model_dump(mode="json")
    db.add(
        Trace(
            episode_id=episode_id,
            trace_type=TraceType.ERROR,
            name="benchmark_handoff_validation_failed",
            content=reason,
            metadata_vars={
                "reason": reason,
                "benchmark_id": benchmark_id,
                "session_id": session_id,
            },
        )
    )
    await db.commit()

    from controller.api.manager import manager

    await manager.broadcast(
        episode_id,
        {
            "type": "status_update",
            "status": EpisodeStatus.FAILED,
            "metadata_vars": episode.metadata_vars,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        },
    )


def _extract_entry_validation_context(result: Any) -> EntryValidationContext:
    raw_errors = _extract_result_field(result, "entry_validation_errors")
    errors: list[EntryValidationError] = []
    if isinstance(raw_errors, list):
        for item in raw_errors:
            if isinstance(item, dict):
                errors.append(
                    EntryValidationError.model_construct(
                        code=str(item.get("code") or "state_invalid"),
                        message=str(item.get("message") or ""),
                        source=str(item.get("source") or "policy"),
                        artifact_path=(
                            str(item["artifact_path"])
                            if item.get("artifact_path") is not None
                            else None
                        ),
                    )
                )
            else:
                errors.append(
                    EntryValidationError.model_construct(
                        code="state_invalid",
                        message=str(item),
                        source="policy",
                        artifact_path=None,
                    )
                )

    node = _extract_result_field(result, "entry_validation_target_node")
    disposition = _extract_result_field(result, "entry_validation_disposition")
    reason_code = _extract_result_field(result, "entry_validation_reason_code")
    reroute_target = _extract_result_field(result, "entry_validation_reroute_target")

    # Keep entry-validation metadata stable even if later nodes clear transient state.
    if node is None or disposition is None or reason_code is None:
        import re

        feedback = _result_feedback(result)
        match = re.search(
            r"ENTRY_VALIDATION_FAILED\[(?P<reason>[^\]]+)\]\s+"
            r"target=(?P<node>[^\s]+)\s+"
            r"(?:(?:reroute=(?P<reroute>[^\s]+))|(?:disposition=(?P<disposition>[^\s]+)))"
            r"\s+\|\s*(?P<detail>.*)$",
            feedback,
        )
        if match:
            reason_code = reason_code or match.group("reason")
            node = node or match.group("node")
            disposition = disposition or match.group("disposition")
            reroute_target = reroute_target or match.group("reroute")

            if not errors:
                detail = (match.group("detail") or "").strip()
                if detail:
                    errors.append(
                        EntryValidationError.model_construct(
                            code=str(reason_code or "state_invalid"),
                            message=detail,
                            source="policy",
                            artifact_path=None,
                        )
                    )

        if disposition is None:
            journal = str(_extract_result_field(result, "journal") or "")
            journal_match = re.search(
                r"\[Entry Validation\].*disposition=(?P<disposition>[^\s]+)",
                journal,
            )
            if journal_match:
                disposition = journal_match.group("disposition")

    try:
        return EntryValidationContext.model_validate(
            {
                "node": node,
                "disposition": disposition,
                "reason_code": reason_code,
                "reroute_target": reroute_target,
                "errors": errors,
            }
        )
    except Exception:
        return EntryValidationContext.model_construct(
            node=node,
            disposition=disposition,
            reason_code=reason_code,
            reroute_target=reroute_target,
            errors=errors,
        )


def _update_episode_entry_validation_metadata(
    *, episode: Episode, result: Any, result_feedback: str
) -> EntryValidationContext | None:
    if not result_feedback.startswith("ENTRY_VALIDATION_FAILED["):
        return None

    metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
    if result_feedback not in metadata.validation_logs:
        metadata.validation_logs.append(result_feedback)

    entry_context = _extract_entry_validation_context(result)
    additional = dict(metadata.additional_info or {})
    additional["entry_validation"] = entry_context.model_dump(mode="json")
    additional["entry_validation_terminal"] = (
        bool(_extract_result_field(result, "entry_validation_terminal"))
        or entry_context.disposition == EntryFailureDisposition.FAIL_FAST
        or str(entry_context.disposition) == EntryFailureDisposition.FAIL_FAST.value
    )
    metadata.additional_info = additional
    episode.metadata_vars = metadata.model_dump()
    return entry_context


async def _episode_has_system_tool_retry_exhausted(
    *, db, episode_id: uuid.UUID
) -> bool:
    """Detect infra retry exhaustion marker from any persisted trace payload."""
    from sqlalchemy import select

    rows = await db.execute(select(Trace).where(Trace.episode_id == episode_id))
    for trace_row in rows.scalars():
        metadata = trace_row.metadata_vars or {}
        error = str(metadata.get("error") or "")
        # Retry-exhaustion marker may appear in different trace families depending
        # on where the failure is surfaced (tool start/end, error log, etc.).
        if (
            SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in error
            or SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in str(trace_row.content or "")
            or SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in str(metadata)
        ):
            return True
    return False


def get_worker_client(session_id: str):
    from controller.clients.worker import WorkerClient

    return WorkerClient(
        base_url=WORKER_LIGHT_URL,
        session_id=session_id,
        heavy_url=settings.worker_heavy_url,
    )


async def execute_agent_task(
    episode_id: uuid.UUID,
    task: str,
    session_id: str,
    agent_name: AgentName = AgentName.ENGINEER_CODER,
    start_node: AgentName | None = None,
):
    session_factory = get_sessionmaker()
    context_tokens = structlog.contextvars.bind_contextvars(
        session_id=session_id,
        episode_id=str(episode_id),
        agent_role=agent_name.value,
        stage=agent_name.value,
    )

    try:
        async with session_factory() as db:
            episode = await db.get(Episode, episode_id)
            if not episode:
                logger.error(
                    "episode_not_found_for_background_task",
                    episode_id=episode_id,
                    session_id=session_id,
                )
                return

            try:
                # Use a 32-char hex trace_id for OTEL/Langfuse v3 compatibility
                trace_id = uuid.uuid4().hex

                workspace_session_id = session_id

                client = get_worker_client(workspace_session_id)
                middleware = RemoteFilesystemMiddleware(
                    client,
                    agent_role=agent_name,
                    episode_id=str(episode_id),
                )
                backend = RemoteFilesystemBackend(middleware)
                from controller.agent.execution_limits import (
                    mark_episode_execution_window_start,
                )

                await mark_episode_execution_window_start(episode_id)

                # Initialize agent files (templates, directories)
                await initialize_agent_files(backend, agent_name=agent_name)
                if agent_name in {
                    AgentName.ENGINEER_CODER,
                    AgentName.ENGINEER_PLANNER,
                    AgentName.BENCHMARK_PLANNER,
                }:
                    await seed_manufacturing_config(backend)

                initial_script_path = authored_script_path_for_agent(agent_name)
                initial_script_content = await client.read_file_optional(
                    initial_script_path
                )
                initial_script_sha256 = (
                    hashlib.sha256(initial_script_content.encode("utf-8")).hexdigest()
                    if initial_script_content is not None
                    else None
                )

                metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
                benchmark_id_str = (metadata.benchmark_id or "").strip()
                if benchmark_id_str:
                    benchmark_worker_session_id = benchmark_id_str
                    source_client: WorkerClient | None = None
                    try:
                        benchmark_uuid = uuid.UUID(benchmark_id_str)
                        async with session_factory() as db_inner:
                            benchmark_episode = await db_inner.get(
                                Episode, benchmark_uuid
                            )
                            if benchmark_episode is None:
                                raise RuntimeError(
                                    f"benchmark episode {benchmark_id_str} not found"
                                )
                            benchmark_metadata = EpisodeMetadata.model_validate(
                                benchmark_episode.metadata_vars or {}
                            )
                            benchmark_worker_session_id = (
                                benchmark_metadata.worker_session_id or ""
                            ).strip() or benchmark_id_str

                        source_client = get_worker_client(benchmark_worker_session_id)
                        (
                            approved_bundle,
                            bundle_error,
                        ) = await validate_approved_benchmark_bundle(
                            source_client,
                            benchmark_episode_id=benchmark_id_str,
                        )
                        if bundle_error is not None or approved_bundle is None:
                            reason = (
                                "approved benchmark bundle validation failed: "
                                f"{bundle_error or 'unknown error'}"
                            )
                            logger.error(
                                "approved_benchmark_bundle_validation_failed",
                                episode_id=episode_id,
                                session_id=session_id,
                                benchmark_id=benchmark_id_str,
                                error=reason,
                            )
                            await _fail_episode_before_graph_start(
                                db=db,
                                episode=episode,
                                episode_id=episode_id,
                                session_id=session_id,
                                reason=reason,
                                benchmark_id=benchmark_id_str,
                            )
                            return

                        await _copy_approved_benchmark_bundle(
                            source_client=source_client,
                            destination_client=client,
                            review_manifest=approved_bundle.review_manifest,
                        )

                        (
                            destination_bundle,
                            destination_error,
                        ) = await validate_approved_benchmark_bundle(
                            client,
                            benchmark_episode_id=benchmark_id_str,
                        )
                        if destination_error is not None or destination_bundle is None:
                            reason = (
                                "copied approved benchmark bundle failed validation: "
                                f"{destination_error or 'unknown error'}"
                            )
                            logger.error(
                                "copied_approved_benchmark_bundle_validation_failed",
                                episode_id=episode_id,
                                session_id=session_id,
                                benchmark_id=benchmark_id_str,
                                error=reason,
                            )
                            await _fail_episode_before_graph_start(
                                db=db,
                                episode=episode,
                                episode_id=episode_id,
                                session_id=session_id,
                                reason=reason,
                                benchmark_id=benchmark_id_str,
                            )
                            return
                    except Exception as e:
                        reason = f"benchmark handoff failed: {e}"
                        logger.error(
                            "failed_to_copy_benchmark_bundle",
                            episode_id=episode_id,
                            session_id=session_id,
                            benchmark_id=benchmark_id_str,
                            error=str(e),
                        )
                        await _fail_episode_before_graph_start(
                            db=db,
                            episode=episode,
                            episode_id=episode_id,
                            session_id=session_id,
                            reason=reason,
                            benchmark_id=benchmark_id_str,
                        )
                        return
                    finally:
                        if source_client is not None:
                            await source_client.aclose()

                agent, langfuse_callback = create_agent_graph(
                    agent_name=agent_name,
                    # For now hardcoded in original code too.
                    trace_id=trace_id,
                    session_id=session_id,
                    start_node=start_node,
                )

                # Add initial trace
                initial_trace = Trace(
                    episode_id=episode_id,
                    trace_type=TraceType.LOG,
                    content=f"Agent starting execution for task: {task}",
                    langfuse_trace_id=trace_id,
                    metadata_vars={"task": task},
                )
                db.add(initial_trace)
                await db.commit()
                await db.refresh(initial_trace)

                # Setup real-time tracing to DB
                db_callback = DatabaseCallbackHandler(
                    episode_id=str(episode_id), loop=asyncio.get_running_loop()
                )

                # Broadcast initial trace (refresh to get ID)
                await db.refresh(initial_trace)
                await db_callback._broadcast_trace(initial_trace)

                # Prepare callbacks list and add Langfuse callback if present.
                callbacks = [db_callback]
                if langfuse_callback:
                    callbacks.append(langfuse_callback)

                # Prepare initial state based on agent type
                if agent_name in [
                    AgentName.ENGINEER_PLANNER,
                    AgentName.ENGINEER_CODER,
                    AgentName.ENGINEER_PLAN_REVIEWER,
                    AgentName.ENGINEER_EXECUTION_REVIEWER,
                    AgentName.SKILL_AGENT,
                ]:
                    initial_input = {
                        "task": task,
                        "session_id": workspace_session_id,
                        "worker_session_id": workspace_session_id,
                        "episode_id": str(episode_id),
                        "start_node": start_node.value if start_node else None,
                        "messages": [HumanMessage(content=task)],
                    }
                elif agent_name in [
                    AgentName.BENCHMARK_PLANNER,
                    AgentName.BENCHMARK_PLAN_REVIEWER,
                    AgentName.BENCHMARK_CODER,
                    AgentName.BENCHMARK_REVIEWER,
                ]:
                    from controller.agent.benchmark.models import (
                        GenerationSession,
                        SessionStatus,
                    )

                    # Try to parse session_id as UUID, fallback to new one
                    try:
                        u_session_id = uuid.UUID(session_id)
                    except ValueError:
                        u_session_id = uuid.uuid4()

                    worker_session_id = workspace_session_id

                    session = GenerationSession(
                        session_id=u_session_id,
                        prompt=task,
                        status=(
                            SessionStatus.EXECUTING
                            if agent_name == AgentName.BENCHMARK_CODER
                            else (
                                SessionStatus.VALIDATING
                                if agent_name == AgentName.BENCHMARK_REVIEWER
                                else SessionStatus.PLANNING
                            )
                        ),
                    )
                    initial_input = {
                        "session": session,
                        "messages": [HumanMessage(content=task)],
                        "current_script": "",
                        "review_round": 0,
                        "start_node": agent_name.value,
                        "episode_id": str(episode_id),
                        "worker_session_id": worker_session_id,
                    }
                else:
                    initial_input = {
                        "messages": [HumanMessage(content=task)],
                        "session_id": session_id,
                        "episode_id": str(episode_id),
                        "initial_script_sha256": initial_script_sha256,
                    }

                # Run the agent with tracing
                # Determine thread_id for persistence.
                # Use episode_id as thread_id to allow resuming.
                # But LangGraph might expect string.
                thread_id = str(episode_id)
                langfuse_session_id = (
                    str(episode.user_session_id)
                    if episode.user_session_id
                    else session_id
                )
                langfuse_metadata = {
                    "episode_id": str(episode_id),
                    "worker_session_id": session_id,
                    "agent_name": agent_name,
                    "start_node": start_node.value if start_node else None,
                }

                with start_root_span(
                    name=agent_name,
                    trace_id=trace_id,
                    input_payload={"task": task, "session_id": session_id},
                    metadata=langfuse_metadata,
                ):
                    attach_session_to_current_trace(
                        langfuse_session_id,
                        trace_name=agent_name,
                        metadata=langfuse_metadata,
                    )
                    config: Any = {
                        "callbacks": callbacks,
                        "metadata": {
                            "episode_id": str(episode_id),
                            "langfuse_trace_id": trace_id,
                            "langfuse_session_id": langfuse_session_id,
                        },
                        "run_name": agent_name,
                        "configurable": {"thread_id": thread_id},
                    }
                    result = await agent.ainvoke(initial_input, config=config)  # type: ignore
                if isinstance(result, dict):
                    msgs = result.get("messages", [])
                    logger.info(
                        "agent_run_completed_messages_info",
                        count=len(msgs),
                        last_msg=str(msgs[-1]) if msgs else "None",
                    )
                    logger.info("agent_run_completed_keys", keys=list(result.keys()))
                else:
                    logger.info(
                        "agent_run_completed_raw_result",
                        result_type=type(result).__name__,
                    )

                # Final trace
                if isinstance(result, dict):
                    final_messages = result.get("messages", [])
                else:
                    final_messages = getattr(result, "messages", [])

                if final_messages:
                    final_output = final_messages[-1].content
                else:
                    final_output = _result_feedback(result) or (
                        "No output produced by agent."
                    )
                final_trace = Trace(
                    episode_id=episode_id,
                    trace_type=TraceType.LOG,
                    content=f"Agent finished execution: {final_output[:200]}...",
                    langfuse_trace_id=trace_id,
                    metadata_vars={"output": final_output},
                )
                db.add(final_trace)

                # Also add a dedicated LLM_END trace for the full final response
                # to ensure it shows in chat
                final_llm_trace = Trace(
                    episode_id=episode_id,
                    trace_type=TraceType.LLM_END,
                    content=final_output,
                    langfuse_trace_id=trace_id,
                )
                db.add(final_llm_trace)

                result_feedback = _result_feedback(result)
                if result_feedback.startswith("ENTRY_VALIDATION_FAILED[") and not bool(
                    _extract_result_field(result, "entry_validation_trace_emitted")
                ):
                    entry_context = _extract_entry_validation_context(result)
                    entry_context_data = entry_context.model_dump(mode="json")
                    trace_metadata = {
                        "source": "node_entry_validation",
                        "status": _result_status_lower(result),
                        **entry_context_data,
                    }
                    db.add(
                        Trace(
                            episode_id=episode_id,
                            trace_type=TraceType.EVENT,
                            name="node_entry_validation_failed",
                            content=result_feedback,
                            langfuse_trace_id=trace_id,
                            metadata_vars=trace_metadata,
                        )
                    )
                    db.add(
                        Trace(
                            episode_id=episode_id,
                            trace_type=TraceType.ERROR,
                            name="node_entry_validation_failed",
                            content=result_feedback,
                            langfuse_trace_id=trace_id,
                            metadata_vars=trace_metadata,
                        )
                    )

                await db.commit()
                await db.refresh(final_llm_trace)

                # Broadcast final message
                await db_callback._broadcast_trace(final_llm_trace)

                # Report automated score to Langfuse
                if langfuse_callback:
                    from controller.observability.langfuse import (
                        calculate_and_report_automated_score,
                    )

                    await calculate_and_report_automated_score(
                        episode_id=episode_id,
                        trace_id=trace_id,
                        agent_name=agent_name,
                        db=db,
                        worker_client=client,
                    )

                # Sync assets from worker (now in background after status update)
                logger.info("starting_asset_sync", episode_id=episode_id)
                try:
                    # Initialize S3 client for this task
                    s3_endpoint = os.getenv("S3_ENDPOINT")
                    s3_access_key = os.getenv("S3_ACCESS_KEY")
                    s3_secret_key = os.getenv("S3_SECRET_KEY")
                    asset_bucket = os.getenv("ASSET_S3_BUCKET", "problemologist")

                    s3_client = None
                    if s3_endpoint and s3_access_key and s3_secret_key:
                        try:
                            s3_client = boto3.client(
                                "s3",
                                endpoint_url=s3_endpoint,
                                aws_access_key_id=s3_access_key,
                                aws_secret_access_key=s3_secret_key,
                            )
                        except Exception as e:
                            logger.error(
                                "failed_to_init_s3_client",
                                error=str(e),
                                session_id=session_id,
                            )

                    async def sync_dir(dir_path: str):
                        try:
                            # Use new session for sync to avoid sharing with main loop
                            files = await client.list_files(dir_path)
                        except Exception as e:
                            logger.error(
                                "failed_to_list_dir_during_sync",
                                dir=dir_path,
                                error=str(e),
                                session_id=session_id,
                            )
                            return
                        for file_info in files:
                            path = file_info.path
                            if file_info.is_dir:
                                # Recursively sync directories
                                if not any(
                                    path.lower().endswith(s)
                                    for s in ["__pycache__", ".git", ".venv"]
                                ):
                                    await sync_dir(path)
                                continue

                            # Skip obviously huge or irrelevant files
                            if path.endswith((".log", ".lock", ".tmp", ".pyc")):
                                continue

                            asset_type = None
                            if path.endswith(".py"):
                                asset_type = AssetType.PYTHON
                            elif path.endswith((".xml", ".mjcf")):
                                asset_type = AssetType.MJCF
                            elif path.endswith(".glb"):
                                asset_type = AssetType.GLB
                            elif path.endswith(".stl"):
                                asset_type = AssetType.STL
                            elif path.endswith((".png", ".jpg", ".jpeg", ".webp")):
                                asset_type = AssetType.IMAGE
                            else:
                                asset_type = AssetType.OTHER

                            # Read content for text assets
                            content = None
                            blob_content = None

                            if asset_type in [
                                AssetType.PYTHON,
                                AssetType.MJCF,
                                AssetType.OTHER,
                            ]:
                                try:
                                    raw_content = await client.read_file(path)
                                    content = raw_content
                                except Exception:
                                    pass

                            from controller.observability.middleware_helper import (
                                broadcast_file_update,
                            )

                            await broadcast_file_update(
                                str(episode_id), path, content or ""
                            )

                            # Upload to S3 if client available
                            if s3_client:
                                try:
                                    if content is not None:
                                        # Upload text content
                                        await asyncio.to_thread(
                                            s3_client.put_object,
                                            Bucket=asset_bucket,
                                            Key=path,
                                            Body=content.encode("utf-8"),
                                        )
                                    else:
                                        # Binary file, read as blob
                                        try:
                                            blob_content = (
                                                await client.read_file_binary(path)
                                            )
                                            await asyncio.to_thread(
                                                s3_client.put_object,
                                                Bucket=asset_bucket,
                                                Key=path,
                                                Body=blob_content,
                                            )
                                        except Exception as e:
                                            logger.error(
                                                "failed_to_read_blob_for_upload",
                                                path=path,
                                                error=str(e),
                                                session_id=session_id,
                                            )
                                except Exception as e:
                                    logger.error(
                                        "failed_to_upload_asset_to_s3",
                                        path=path,
                                        error=str(e),
                                        session_id=session_id,
                                    )

                    async def sync_workspace_review_dir():
                        """Sync reviewer outputs from the session workspace, not the /reviews mount."""
                        try:
                            review_files = await client.list_files(
                                "reviews", bypass_agent_permissions=True
                            )
                        except Exception as e:
                            logger.error(
                                "failed_to_list_workspace_reviews_during_sync",
                                error=str(e),
                                session_id=session_id,
                            )
                            return

                        from controller.observability.middleware_helper import (
                            broadcast_file_update,
                        )

                        for file_info in review_files:
                            if file_info.is_dir:
                                continue

                            path = f"reviews/{file_info.name}"
                            content = None
                            try:
                                content = await client.read_file(
                                    path, bypass_agent_permissions=True
                                )
                            except Exception:
                                content = None

                            await broadcast_file_update(
                                str(episode_id), path, content or ""
                            )

                            if s3_client and content is not None:
                                try:
                                    await asyncio.to_thread(
                                        s3_client.put_object,
                                        Bucket=asset_bucket,
                                        Key=path,
                                        Body=content.encode("utf-8"),
                                    )
                                except Exception as e:
                                    logger.error(
                                        "failed_to_upload_workspace_review_to_s3",
                                        path=path,
                                        error=str(e),
                                        session_id=session_id,
                                    )

                    simulation_success_text: str | None = None
                    # Sync the session workspace only. The worker root view also
                    # exposes read-only mounts like /utils, /skills, and /config.
                    # Recursing from /workspace avoids sweeping those mounts.
                    await sync_dir("/workspace")
                    await sync_workspace_review_dir()
                    # .manifests is system-owned metadata and may be denied via role
                    # policy through routed backend calls. Read directly with
                    # permission bypass so reviewer manifests still appear in assets.
                    try:
                        from controller.observability.middleware_helper import (
                            broadcast_file_update,
                        )

                        manifest_paths = (
                            ".manifests/benchmark_plan_review_manifest.json",
                            ".manifests/benchmark_review_manifest.json",
                            ".manifests/engineering_plan_review_manifest.json",
                            ".manifests/engineering_execution_handoff_manifest.json",
                        )
                        for manifest_path in manifest_paths:
                            if await client.exists(
                                manifest_path, bypass_agent_permissions=True
                            ):
                                manifest_content = await client.read_file(
                                    manifest_path, bypass_agent_permissions=True
                                )
                                await broadcast_file_update(
                                    str(episode_id), manifest_path, manifest_content
                                )
                    except Exception:
                        pass
                    try:
                        raw_results = await client.read_file("validation_results.json")
                        if raw_results:
                            import json

                            data = json.loads(raw_results)
                            summary = str(data.get("summary", "")).strip()
                            status = str(data.get("status", "")).strip().lower()
                            if status in {"ok", "success"} and summary:
                                simulation_success_text = summary
                    except Exception:
                        pass
                    if not simulation_success_text:
                        try:
                            raw_sim = await client.read_file("simulation_result.json")
                            if raw_sim:
                                import json

                                sim_data = json.loads(raw_sim)
                                summary = str(sim_data.get("summary", "")).strip()
                                if summary:
                                    simulation_success_text = summary
                        except Exception:
                            pass

                    if simulation_success_text:
                        db.add(
                            Trace(
                                episode_id=episode_id,
                                trace_type=TraceType.LOG,
                                content=simulation_success_text,
                                langfuse_trace_id=trace_id,
                            )
                        )
                    await db.commit()
                    logger.info("asset_sync_completed", episode_id=episode_id)
                except Exception as e:
                    logger.error(
                        "failed_to_sync_assets",
                        error=str(e),
                        session_id=str(episode_id),
                    )

                # Mark completion after traces/assets are persisted.
                await db.refresh(episode)
                if episode.status != EpisodeStatus.CANCELLED:
                    result_feedback = _result_feedback(result)
                    _update_episode_entry_validation_metadata(
                        episode=episode,
                        result=result,
                        result_feedback=result_feedback,
                    )
                    metadata = EpisodeMetadata.model_validate(
                        episode.metadata_vars or {}
                    )
                    result_logs = _extract_session_validation_logs(result)
                    if result_logs:
                        merged_logs = list(dict.fromkeys(metadata.validation_logs))
                        for log in result_logs:
                            if log not in merged_logs:
                                merged_logs.append(log)
                        metadata.validation_logs = merged_logs
                        episode.metadata_vars = metadata.model_dump(mode="json")
                    planner_handoff_failed = _is_planner_agent(agent_name) and (
                        result_feedback.startswith("Planner handoff blocked:")
                        or any(
                            "planner_fail_fast" in log
                            for log in (
                                _extract_session_validation_logs(result)
                                or metadata.validation_logs
                            )
                        )
                    )
                    if planner_handoff_failed:
                        planner_block_message = (
                            result_feedback
                            if result_feedback.startswith("Planner handoff blocked:")
                            else (
                                "Planner handoff blocked: "
                                + (
                                    result_feedback
                                    or "benchmark terminal handoff error"
                                )
                            )
                        )
                        if planner_block_message not in metadata.validation_logs:
                            metadata.validation_logs.append(planner_block_message)
                        metadata.terminal_reason = (
                            TerminalReason.HANDOFF_INVARIANT_VIOLATION
                        )
                        metadata.failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
                        episode.metadata_vars = metadata.model_dump(mode="json")
                    system_retry_exhausted = (
                        await _episode_has_system_tool_retry_exhausted(
                            db=db, episode_id=episode_id
                        )
                    )
                    target_status = EpisodeStatus.FAILED
                    if not _is_failed_result(result):
                        target_status = (
                            EpisodeStatus.PLANNED
                            if _is_planner_agent(agent_name)
                            else EpisodeStatus.COMPLETED
                        )
                    if system_retry_exhausted:
                        target_status = EpisodeStatus.FAILED
                    if _is_solution_workflow_agent(agent_name):
                        metadata = EpisodeMetadata.model_validate(
                            episode.metadata_vars or {}
                        )
                        terminal_reason, failure_class, error_message = (
                            _derive_solution_terminal_metadata(
                                result=result,
                                result_feedback=result_feedback,
                                terminal_status=target_status,
                                system_retry_exhausted=system_retry_exhausted,
                            )
                        )
                        metadata.detailed_status = target_status.value
                        metadata.terminal_reason = terminal_reason
                        metadata.failure_class = failure_class
                        metadata.error = error_message
                        episode.metadata_vars = metadata.model_dump(mode="json")
                    episode.status = target_status
                    if episode.todo_list is None:
                        episode.todo_list = {"completed": True}
                    if not episode.plan:
                        episode.plan = (
                            "# Solution Overview\n"
                            f"Agent completed task: {task}\n\n"
                            "## Parts List\n"
                            f"- Result summary: {final_output[:500]}...\n"
                            "\n## 3. Assembly Strategy\n"
                            "1. Review the completed task output and preserve the validated handoff shape.\n"
                            "\n## 4. Assumption Register\n"
                            "- Assumption: The fallback plan reflects a completed task summary only.\n"
                            "\n## 5. Detailed Calculations\n"
                            "| ID | Problem / Decision | Result | Impact |\n"
                            "| -- | -- | -- | -- |\n"
                            "| CALC-001 | No engineering derivation is available in this fallback artifact. | `N/A` | Replace the fallback artifact with a real planner handoff. |\n"
                            "\n### CALC-001: No engineering derivation is available in this fallback artifact.\n"
                            "\n#### Problem Statement\n"
                            "\nThis fallback artifact does not contain a real engineering derivation.\n"
                            "\n#### Assumptions\n"
                            "\n- `ASSUMP-001`: The fallback artifact is only a placeholder.\n"
                            "\n#### Derivation\n"
                            "\n- No derivation is available.\n"
                            "\n#### Worst-Case Check\n"
                            "\n- Not applicable to a placeholder plan.\n"
                            "\n#### Result\n"
                            "\n- The fallback output is not a valid engineering derivation.\n"
                            "\n#### Design Impact\n"
                            "\n- Replace the fallback artifact with a real planner handoff.\n"
                            "\n#### Cross-References\n"
                            "\n- `engineering_plan.md#4-assumption-register`\n"
                            "\n## 6. Critical Constraints / Operating Envelope\n"
                            "- Constraint: Keep the generated summary inside the current task scope.\n"
                            "\n## 7. Cost & Weight Budget\n"
                            "- Cost: Not applicable in fallback output.\n"
                            "- Weight: Not applicable in fallback output.\n"
                            "\n## 8. Risk Assessment\n"
                            "- Risk: Fallback plans are only placeholders and should be replaced by a real planner handoff.\n"
                        )
                    await db.commit()

                    from controller.api.manager import manager

                    await manager.broadcast(
                        episode_id,
                        {
                            "type": "status_update",
                            "status": target_status,
                            "metadata_vars": episode.metadata_vars,
                            "timestamp": datetime.datetime.now(
                                datetime.UTC
                            ).isoformat(),
                        },
                    )

                logger.info("agent_task_logic_completed", episode_id=episode_id)

            except asyncio.CancelledError:
                logger.info("agent_run_cancelled", episode_id=episode_id)
                # Re-fetch to ensure session is valid
                episode = await db.get(Episode, episode_id)
                if episode:
                    episode.status = EpisodeStatus.CANCELLED
                    final_trace = Trace(
                        episode_id=episode_id,
                        trace_type=TraceType.LOG,
                        content="Episode cancelled by user",
                    )
                    db.add(final_trace)
                    await db.commit()
                raise  # Re-raise to ensure proper task cancellation
            except Exception as e:
                # We reuse the existing session if possible, or handle generic error
                import traceback

                logger.error(
                    "agent_run_failed",
                    error=str(e),
                    traceback=traceback.format_exc(),
                    episode_id=episode_id,
                    session_id=session_id,
                )
                episode = await db.get(Episode, episode_id)
                if episode:
                    episode.status = EpisodeStatus.FAILED
                    metadata = EpisodeMetadata.model_validate(
                        episode.metadata_vars or {}
                    )
                    if SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in str(e):
                        metadata.terminal_reason = (
                            TerminalReason.SYSTEM_TOOL_RETRY_EXHAUSTED
                        )
                        metadata.failure_class = FailureClass.INFRA_DEVOPS_FAILURE
                        metadata.error = SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER
                        episode.metadata_vars = metadata.model_dump(mode="json")
                    await db.commit()

                    # Broadcast status update
                    from controller.api.manager import manager

                    await manager.broadcast(
                        episode_id,
                        {
                            "type": "status_update",
                            "status": EpisodeStatus.FAILED,
                            "metadata_vars": episode.metadata_vars,
                            "timestamp": datetime.datetime.now(
                                datetime.UTC
                            ).isoformat(),
                        },
                    )

    finally:
        structlog.contextvars.reset_contextvars(**context_tokens)
        # Always remove task from tracker
        task_tracker.remove_task(episode_id)


async def continue_agent_task(
    episode_id: uuid.UUID,
    message: str,
    additional_turns: int = 0,
    metadata: dict | None = None,
):
    """
    Continue an existing agent task with a new user message.
    """
    session_factory = get_sessionmaker()
    context_tokens: dict[str, Any] = {}

    try:
        async with session_factory() as db:
            episode = await db.get(Episode, episode_id)
            if not episode:
                logger.error(
                    "episode_not_found_for_continuation",
                    episode_id=episode_id,
                    session_id=str(episode_id),
                )
                return

            # Update status to RUNNING
            if episode.status != EpisodeStatus.RUNNING:
                episode.status = EpisodeStatus.RUNNING
                await db.commit()

            if additional_turns > 0:
                from controller.agent.execution_limits import (
                    grant_episode_additional_turns,
                )

                await grant_episode_additional_turns(
                    episode_id=episode_id,
                    additional_turns=additional_turns,
                )
            from controller.agent.execution_limits import (
                mark_episode_execution_window_start,
            )

            await mark_episode_execution_window_start(episode_id)

            try:
                # Setup context
                trace_id = uuid.uuid4().hex
                session_id = None
                if episode.metadata_vars:
                    from shared.models.schemas import EpisodeMetadata

                    metadata_typed = EpisodeMetadata.model_validate(
                        episode.metadata_vars
                    )
                    session_id = metadata_typed.worker_session_id

                if not session_id:
                    # Fallback
                    session_id = str(episode_id)

                context_tokens = structlog.contextvars.bind_contextvars(
                    session_id=session_id,
                    episode_id=str(episode_id),
                    agent_role=AgentName.ENGINEER_CODER.value,
                    stage=AgentName.ENGINEER_CODER.value,
                )

                client = get_worker_client(session_id)

                # Try to retrieve agent_name from metadata if available
                agent_name = AgentName.ENGINEER_CODER
                if episode.metadata_vars:
                    from shared.models.schemas import EpisodeMetadata

                    with suppress(Exception):
                        # Validate metadata shape if present.
                        EpisodeMetadata.model_validate(episode.metadata_vars)

                agent, langfuse_callback = create_agent_graph(
                    agent_name=agent_name,
                    trace_id=trace_id,
                    session_id=session_id,
                )

                # Add trace for user message
                user_trace = Trace(
                    episode_id=episode_id,
                    trace_type=TraceType.LOG,
                    content=f"User message: {message}",
                    langfuse_trace_id=trace_id,
                    metadata_vars={
                        "role": "user",
                        "message": message,
                        "metadata": metadata,
                    },
                )
                db.add(user_trace)
                await db.commit()
                await db.refresh(user_trace)

                # Setup callbacks
                db_callback = DatabaseCallbackHandler(
                    episode_id=str(episode_id), loop=asyncio.get_running_loop()
                )
                await db_callback._broadcast_trace(user_trace)

                callbacks = [db_callback]
                if langfuse_callback:
                    callbacks.append(langfuse_callback)

                # Invoke agent with new message
                thread_id = str(episode_id)
                langfuse_session_id = (
                    str(episode.user_session_id)
                    if episode.user_session_id
                    else session_id
                )
                langfuse_metadata = {
                    "episode_id": str(episode_id),
                    "worker_session_id": session_id,
                    "agent_name": agent_name,
                }

                human_message = HumanMessage(
                    content=message,
                )
                input_update = {
                    "messages": [human_message],
                    "episode_id": str(episode_id),
                    "session_id": session_id,
                }

                with start_root_span(
                    name=agent_name,
                    trace_id=trace_id,
                    input_payload={"message": message, "session_id": session_id},
                    metadata=langfuse_metadata,
                ):
                    attach_session_to_current_trace(
                        langfuse_session_id,
                        trace_name=agent_name,
                        metadata=langfuse_metadata,
                    )
                    result = await agent.ainvoke(
                        input_update,
                        config={
                            "callbacks": callbacks,
                            "metadata": {
                                "episode_id": str(episode_id),
                                "langfuse_trace_id": trace_id,
                                "langfuse_session_id": langfuse_session_id,
                            },
                            "run_name": agent_name,
                            "configurable": {"thread_id": thread_id},
                        },
                    )

                # Final trace
                if isinstance(result, dict):
                    final_messages = result.get("messages", [])
                else:
                    final_messages = getattr(result, "messages", [])

                if final_messages:
                    final_output = final_messages[-1].content
                else:
                    final_output = _result_feedback(result) or (
                        "No output produced by agent."
                    )

                final_trace = Trace(
                    episode_id=episode_id,
                    trace_type=TraceType.LLM_END,
                    content=final_output,
                    langfuse_trace_id=trace_id,
                )
                db.add(final_trace)

                result_feedback = _result_feedback(result)
                if result_feedback.startswith("ENTRY_VALIDATION_FAILED[") and not bool(
                    _extract_result_field(result, "entry_validation_trace_emitted")
                ):
                    entry_context = _extract_entry_validation_context(result)
                    entry_context_data = entry_context.model_dump(mode="json")
                    trace_metadata = {
                        "source": "node_entry_validation",
                        "status": _result_status_lower(result),
                        **entry_context_data,
                    }
                    db.add(
                        Trace(
                            episode_id=episode_id,
                            trace_type=TraceType.EVENT,
                            name="node_entry_validation_failed",
                            content=result_feedback,
                            langfuse_trace_id=trace_id,
                            metadata_vars=trace_metadata,
                        )
                    )
                    db.add(
                        Trace(
                            episode_id=episode_id,
                            trace_type=TraceType.ERROR,
                            name="node_entry_validation_failed",
                            content=result_feedback,
                            langfuse_trace_id=trace_id,
                            metadata_vars=trace_metadata,
                        )
                    )

                # Update status
                await db.refresh(episode)
                if episode.status != EpisodeStatus.CANCELLED:
                    result_feedback = _result_feedback(result)
                    _update_episode_entry_validation_metadata(
                        episode=episode,
                        result=result,
                        result_feedback=result_feedback,
                    )
                    system_retry_exhausted = (
                        await _episode_has_system_tool_retry_exhausted(
                            db=db, episode_id=episode_id
                        )
                    )
                    episode.status = (
                        EpisodeStatus.FAILED
                        if (_is_failed_result(result) or system_retry_exhausted)
                        else EpisodeStatus.COMPLETED
                    )
                    if _is_solution_workflow_agent(agent_name):
                        metadata = EpisodeMetadata.model_validate(
                            episode.metadata_vars or {}
                        )
                        terminal_reason, failure_class, error_message = (
                            _derive_solution_terminal_metadata(
                                result=result,
                                result_feedback=result_feedback,
                                terminal_status=episode.status,
                                system_retry_exhausted=system_retry_exhausted,
                            )
                        )
                        metadata.detailed_status = episode.status.value
                        metadata.terminal_reason = terminal_reason
                        metadata.failure_class = failure_class
                        metadata.error = error_message
                        episode.metadata_vars = metadata.model_dump(mode="json")
                    if episode.todo_list is None:
                        episode.todo_list = {"completed": True}
                if not episode.plan:
                    episode.plan = (
                        "# Solution Overview\n"
                        "Continuation completed successfully.\n\n"
                        "## Parts List\n"
                        f"- Result summary: {final_output[:500]}...\n"
                        "\n## 3. Assembly Strategy\n"
                        "1. Preserve the completed solution summary for downstream review.\n"
                        "\n## 4. Assumption Register\n"
                        "- Assumption: This is a continuation fallback artifact.\n"
                        "\n## 5. Detailed Calculations\n"
                        "| ID | Problem / Decision | Result | Impact |\n"
                        "| -- | -- | -- | -- |\n"
                        "| CALC-001 | No additional derivation is recorded in this fallback artifact. | `N/A` | Replace the fallback artifact with a real planner handoff. |\n"
                        "\n### CALC-001: No additional derivation is recorded in this fallback artifact.\n"
                        "\n#### Problem Statement\n"
                        "\nThis fallback artifact does not contain a real engineering derivation.\n"
                        "\n#### Assumptions\n"
                        "\n- `ASSUMP-001`: The fallback artifact is only a placeholder.\n"
                        "\n#### Derivation\n"
                        "\n- No derivation is available.\n"
                        "\n#### Worst-Case Check\n"
                        "\n- Not applicable to a placeholder plan.\n"
                        "\n#### Result\n"
                        "\n- The fallback output is not a valid engineering derivation.\n"
                        "\n#### Design Impact\n"
                        "\n- Replace the fallback artifact with a real planner handoff.\n"
                        "\n#### Cross-References\n"
                        "\n- `engineering_plan.md#4-assumption-register`\n"
                        "\n## 6. Critical Constraints / Operating Envelope\n"
                        "- Constraint: Keep the fallback summary within the current episode.\n"
                        "\n## 7. Cost & Weight Budget\n"
                        "- Cost: Not applicable in fallback output.\n"
                        "- Weight: Not applicable in fallback output.\n"
                        "\n## 8. Risk Assessment\n"
                        "- Risk: Fallback plans are only placeholders and should be replaced by a real planner handoff.\n"
                    )

                await db.commit()

                # Broadcast status update
                from controller.api.manager import manager

                await manager.broadcast(
                    episode_id,
                    {
                        "type": "status_update",
                        "status": episode.status,
                        "metadata_vars": episode.metadata_vars,
                        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                    },
                )

                await db_callback._broadcast_trace(final_trace)

                # Report automated score to Langfuse
                if langfuse_callback:
                    from controller.observability.langfuse import (
                        calculate_and_report_automated_score,
                    )

                    await calculate_and_report_automated_score(
                        episode_id=episode_id,
                        trace_id=trace_id,
                        agent_name=agent_name,
                        db=db,
                        worker_client=client,
                    )

                logger.info("agent_continuation_completed", episode_id=episode_id)

            except Exception as e:
                import traceback

                logger.error(
                    "agent_continuation_failed",
                    error=str(e),
                    traceback=traceback.format_exc(),
                    episode_id=episode_id,
                    session_id=session_id,
                )
                episode = await db.get(Episode, episode_id)
                if episode:
                    episode.status = EpisodeStatus.FAILED
                    metadata = EpisodeMetadata.model_validate(
                        episode.metadata_vars or {}
                    )
                    if SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER in str(e):
                        metadata.terminal_reason = (
                            TerminalReason.SYSTEM_TOOL_RETRY_EXHAUSTED
                        )
                        metadata.failure_class = FailureClass.INFRA_DEVOPS_FAILURE
                        metadata.error = SYSTEM_TOOL_RETRY_EXHAUSTED_MARKER
                        episode.metadata_vars = metadata.model_dump(mode="json")
                    await db.commit()

                    # Broadcast status update
                    from controller.api.manager import manager

                    await manager.broadcast(
                        episode_id,
                        {
                            "type": "status_update",
                            "status": EpisodeStatus.FAILED,
                            "metadata_vars": episode.metadata_vars,
                            "timestamp": datetime.datetime.now(
                                datetime.UTC
                            ).isoformat(),
                        },
                    )
    finally:
        if context_tokens:
            structlog.contextvars.reset_contextvars(**context_tokens)
        pass
