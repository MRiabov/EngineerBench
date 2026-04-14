import ast
import asyncio
import json
import re
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

import httpx
import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from opentelemetry import trace
from sqlalchemy import select

from controller.agent.benchmark_handover_validation import (
    extract_benchmark_refusal_reason,
    validate_benchmark_planner_handoff_artifacts,
)
from controller.agent.config import settings as agent_settings
from controller.agent.context_usage import (
    estimate_text_tokens,
    update_episode_context_usage,
)
from controller.agent.execution_limits import (
    evaluate_agent_hard_fail,
    mark_episode_execution_window_start,
    persist_episode_turn_count,
)
from controller.agent.handover_constants import (
    BENCHMARK_CODER_HANDOVER_CHECK,
    BENCHMARK_PLAN_REVIEW_MANIFEST,
    BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK,
    BENCHMARK_REVIEW_MANIFEST,
    BENCHMARK_REVIEWER_HANDOVER_CHECK,
)
from controller.agent.initialization import (
    initialize_agent_files,
    seed_manufacturing_config,
)
from controller.agent.node_entry_validation import (
    NodeEntryValidationError,
    ValidationGraph,
    benchmark_coder_handover_custom_check,
    benchmark_plan_reviewer_handover_custom_check,
    build_benchmark_node_contracts,
    evaluate_node_entry_contract,
    integration_mode_enabled,
    reviewer_handover_custom_check_from_session_id,
)
from controller.agent.review_handover import collect_plan_reviewer_handover_evidence
from controller.clients.backend import RemoteFilesystemBackend
from controller.clients.worker import WorkerClient
from controller.middleware.remote_fs import RemoteFilesystemMiddleware
from controller.observability.database import DatabaseCallbackHandler
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Episode, Trace
from shared.current_role import current_role_manifest_json
from shared.enums import (
    AgentName,
    EpisodePhase,
    EpisodeStatus,
    FailureClass,
    GenerationKind,
    ReviewDecision,
    TerminalReason,
    TraceType,
)
from shared.models.schemas import EpisodeMetadata, PlannerSubmissionResult
from shared.observability.events import emit_event
from shared.observability.schemas import NodeEntryValidationFailedEvent
from shared.simulation.schemas import (
    CustomObjectives,
    RandomizationStrategy,
    SimulatorBackendType,
    get_default_simulator_backend,
)

from .models import GenerationSession, SessionStatus
from .nodes import (
    coder_node,
    cots_search_node,
    plan_reviewer_node,
    planner_node,
    reviewer_node,
)
from .state import BenchmarkGeneratorState
from .storage import BenchmarkStorage

logger = structlog.get_logger(__name__)
_REPEATED_FAILURE_FINGERPRINT_THRESHOLD = 2
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_HEX_TOKEN_PATTERN = re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"\b\d+\b")


async def _sidecars_disabled_for_state(state: BenchmarkGeneratorState) -> bool:
    if integration_mode_enabled():
        return True

    episode_id = (state.episode_id or "").strip()
    if not episode_id:
        return False

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, episode_id)
        if episode is None:
            return False
        metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
        return bool(
            metadata.disable_sidecars
            or metadata.is_integration_test
            or metadata.generation_kind == GenerationKind.SEEDED_EVAL
        )


BENCHMARK_NODE_CONTRACTS = build_benchmark_node_contracts()


async def _refresh_current_role_manifest(
    state: BenchmarkGeneratorState, agent_name: AgentName
) -> None:
    from controller.config.settings import settings as global_settings

    session_id = _effective_benchmark_worker_session_id(state)
    if not session_id:
        logger.warning(
            "current_role_manifest_refresh_skipped",
            agent_name=agent_name.value,
            reason="missing_session_id",
        )
        return

    client = WorkerClient(
        base_url=global_settings.worker_light_url,
        heavy_url=global_settings.worker_heavy_url,
        session_id=session_id,
    )
    try:
        await client.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(agent_name),
            overwrite=True,
            bypass_agent_permissions=True,
        )
    except Exception as exc:
        logger.warning(
            "current_role_manifest_refresh_failed",
            agent_name=agent_name.value,
            episode_id=state.episode_id,
            session_id=session_id,
            error=str(exc),
        )
    finally:
        await client.aclose()


async def _get_latest_planner_submission_result(
    session_id: uuid.UUID,
) -> tuple["PlannerSubmissionResult | None", str | None]:
    """Read the latest benchmark planner submission from persisted traces."""
    submission_tool_names = ("submit_benchmark_plan", "submit_plan")
    submission_tool_name = submission_tool_names[0]
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        query = (
            select(Trace)
            .where(
                Trace.episode_id == session_id,
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

    parsed_payload: dict[str, Any] | None = None
    if isinstance(observation_raw, dict):
        parsed_payload = observation_raw
    elif isinstance(observation_raw, str):
        observation_text = observation_raw.strip()
        with suppress(Exception):
            loaded_json = json.loads(observation_text)
            if isinstance(loaded_json, dict):
                parsed_payload = loaded_json
        with suppress(Exception):
            if parsed_payload is None:
                loaded = ast.literal_eval(observation_text)
                if isinstance(loaded, dict):
                    parsed_payload = loaded

    if parsed_payload is None:
        return None, (
            f"{submission_tool_name}() observation is not a structured payload"
        )

    with suppress(Exception):
        return PlannerSubmissionResult.model_validate(parsed_payload), None
    return None, (
        f"{submission_tool_name}() observation does not match PlannerSubmissionResult"
    )


async def _read_session_markdown(
    session_id: str | uuid.UUID, relative_path: str
) -> str | None:
    """Read markdown/text artifacts directly from the worker session."""
    try:
        from controller.config.settings import settings as global_settings

        client = WorkerClient(
            base_url=global_settings.worker_light_url,
            heavy_url=global_settings.worker_heavy_url,
            session_id=str(session_id),
        )
        try:
            if not await client.exists(relative_path):
                return None
            content = (await client.read_file(relative_path)).strip()
            if not content or content.startswith("Error:"):
                return None
            return content
        finally:
            await client.aclose()
    except Exception:
        return None


def _map_hard_fail_metadata(
    hard_fail_code: str | None,
) -> tuple[TerminalReason, FailureClass]:
    if hard_fail_code == "timeout":
        return TerminalReason.TIMEOUT, FailureClass.AGENT_QUALITY_FAILURE
    if hard_fail_code == "max_turns":
        return TerminalReason.OUT_OF_TURN_BUDGET, FailureClass.AGENT_QUALITY_FAILURE
    if hard_fail_code == "credits_exceeded":
        return TerminalReason.OUT_OF_TOKEN_BUDGET, FailureClass.AGENT_QUALITY_FAILURE
    if hard_fail_code == "benchmark_handoff_validation":
        return (
            TerminalReason.HANDOFF_INVARIANT_VIOLATION,
            FailureClass.AGENT_SEMANTIC_FAILURE,
        )
    return TerminalReason.INTERNAL_ERROR, FailureClass.APPLICATION_LOGIC_FAILURE


def _is_reviewer_handoff_blocked_feedback(review_feedback: str | None) -> bool:
    text = (review_feedback or "").lower()
    return (
        "reviewer handoff blocked" in text or "benchmark reviewer blocked" in text
    ) and ("review_manifest" in text or "submit_for_review" in text)


def _normalize_failure_text(text: str | None) -> str:
    normalized = (text or "").strip().lower()
    if not normalized:
        return ""
    normalized = _UUID_PATTERN.sub("<uuid>", normalized)
    normalized = _HEX_TOKEN_PATTERN.sub("<hex>", normalized)
    normalized = _NUMBER_PATTERN.sub("<n>", normalized)
    normalized = " ".join(normalized.split())
    return normalized[:220]


def _effective_benchmark_worker_session_id(
    state: BenchmarkGeneratorState | None = None,
    *,
    session_id: str | None = None,
    prompt: str | None = None,
) -> str:
    if state is not None:
        worker_session_id = (state.worker_session_id or "").strip()
        if worker_session_id:
            return worker_session_id
        session_id = str(state.session.session_id)
    return (session_id or "").strip()


def _normalized_failure_items(text: str | None) -> list[str]:
    """Return deterministic, de-duplicated normalized fragments."""
    raw = (text or "").strip()
    if not raw:
        return []
    fragments = [_normalize_failure_text(fragment) for fragment in raw.split(";")]
    deduped = sorted({fragment for fragment in fragments if fragment})
    return deduped


def _has_benchmark_refusal(*texts: str | None) -> bool:
    return any(
        extract_benchmark_refusal_reason(text) is not None
        for text in texts
        if text is not None
    )


def _has_benchmark_terminal_handoff_error(*texts: str | None) -> bool:
    terminal_tokens = (
        "AMBIGUOUS_TASK",
        "CONTRADICTORY_CONSTRAINTS",
        "INVALID_OBJECTIVES",
        "UNSOLVABLE_SCENARIO",
    )
    for text in texts:
        if not text:
            continue
        upper = text.upper()
        if any(token in upper for token in terminal_tokens):
            return True
    return _has_benchmark_refusal(*texts)


def _entry_validation_has_benchmark_refusal(
    state: BenchmarkGeneratorState,
) -> bool:
    texts: list[str | None] = [
        state.entry_validation_reason_code,
        state.review_feedback,
    ]
    for error in state.entry_validation_errors or []:
        if isinstance(error, dict):
            texts.append(str(error.get("code") or "") or None)
            texts.append(str(error.get("message") or "") or None)
        else:
            texts.append(str(error))
    return _has_benchmark_refusal(*texts)


def _build_failure_fingerprint(
    *,
    state: BenchmarkGeneratorState,
    stage: AgentName,
    status: SessionStatus,
) -> str | None:
    if status not in {SessionStatus.REJECTED, SessionStatus.FAILED}:
        return None

    parts: list[str] = [f"stage:{stage.value}", f"status:{status.value.lower()}"]
    if state.review_decision is not None:
        parts.append(f"decision:{state.review_decision.value.lower()}")
    if state.hard_fail_code:
        parts.append(f"hard_fail:{state.hard_fail_code.lower()}")

    feedback_items = _normalized_failure_items(state.review_feedback)
    if feedback_items:
        for item in feedback_items[:4]:
            parts.append(f"feedback:{item}")
    else:
        feedback = _normalize_failure_text(state.review_feedback)
        if feedback:
            parts.append(f"feedback:{feedback}")

    # Planner retries accumulate noisy validation logs over time, which can
    # prevent stable fingerprint matching across equivalent failure cycles.
    # For planner-stage loop detection, rely on normalized feedback/hard-fail
    # signals and avoid trailing-log churn.
    if stage == AgentName.BENCHMARK_PLANNER:
        fingerprint = "|".join(parts).strip()
        return fingerprint or None

    if state.session.validation_logs:
        # Use a short trailing window and deterministic ordering so equivalent
        # planner failures produce the same fingerprint across retry turns.
        trailing_logs = state.session.validation_logs[-8:]
        normalized_logs = sorted(
            {
                normalized
                for normalized in (
                    _normalize_failure_text(log_item) for log_item in trailing_logs
                )
                if normalized
            }
        )
        for log_text in normalized_logs[:4]:
            parts.append(f"log:{log_text}")

    fingerprint = "|".join(parts).strip()
    return fingerprint or None


def _record_repeated_failure(
    *,
    state: BenchmarkGeneratorState,
    stage: AgentName,
    fingerprint: str,
) -> int:
    stage_key = stage.value
    if (
        state.repeated_failure_stage == stage_key
        and state.repeated_failure_fingerprint == fingerprint
    ):
        state.repeated_failure_count += 1
    else:
        state.repeated_failure_stage = stage_key
        state.repeated_failure_fingerprint = fingerprint
        state.repeated_failure_count = 1
    return state.repeated_failure_count


def _reset_repeated_failure(state: BenchmarkGeneratorState) -> None:
    state.repeated_failure_stage = None
    state.repeated_failure_fingerprint = None
    state.repeated_failure_count = 0


def _classify_repeated_failure(
    fingerprint: str,
) -> tuple[TerminalReason, FailureClass, str]:
    lowered = fingerprint.lower()
    if extract_benchmark_refusal_reason(fingerprint) is not None:
        return (
            TerminalReason.HANDOFF_INVARIANT_VIOLATION,
            FailureClass.AGENT_SEMANTIC_FAILURE,
            "benchmark_refusal",
        )
    if any(
        token in lowered
        for token in (
            "resource_exhausted",
            "quota",
            "429",
            "too many requests",
            "rate limit",
        )
    ):
        return (
            TerminalReason.SYSTEM_TOOL_RETRY_EXHAUSTED,
            FailureClass.INFRA_DEVOPS_FAILURE,
            "provider_quota_or_rate_limit",
        )
    if any(
        token in lowered
        for token in (
            "handoff",
            "manifest",
            "submit_benchmark_plan",
            "submit_engineering_plan",
            "submit_plan",
            "submit_for_review",
        )
    ):
        return (
            TerminalReason.HANDOFF_INVARIANT_VIOLATION,
            FailureClass.AGENT_SEMANTIC_FAILURE,
            "handoff_invariant_violation",
        )
    return (
        TerminalReason.INTERNAL_ERROR,
        FailureClass.AGENT_SEMANTIC_FAILURE,
        "repeated_stage_failure",
    )


def _entry_validation_metadata_from_state(
    state: BenchmarkGeneratorState,
) -> dict[str, Any]:
    return {
        "node": state.entry_validation_target_node,
        "disposition": state.entry_validation_disposition,
        "reason_code": state.entry_validation_reason_code,
        "reroute_target": state.entry_validation_reroute_target,
        "errors": list(state.entry_validation_errors or []),
    }


async def _persist_entry_validation_rejection_trace(
    *,
    session_id: uuid.UUID,
    review_feedback: str | None,
    metadata_payload: dict[str, Any],
) -> None:
    content = (review_feedback or "").strip()
    if not content.startswith("ENTRY_VALIDATION_FAILED["):
        return

    trace_metadata = {"source": "node_entry_validation", **metadata_payload}
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        db.add(
            Trace(
                episode_id=session_id,
                trace_type=TraceType.EVENT,
                name="node_entry_validation_failed",
                content=content,
                metadata_vars=trace_metadata,
            )
        )
        db.add(
            Trace(
                episode_id=session_id,
                trace_type=TraceType.ERROR,
                name="node_entry_validation_failed",
                content=content,
                metadata_vars=trace_metadata,
            )
        )
        await db.commit()


async def _artifact_exists_for_benchmark_state(
    state: BenchmarkGeneratorState, artifact_path: str
) -> bool:
    session_id = _effective_benchmark_worker_session_id(state)
    if not session_id:
        return False

    try:
        from controller.config.settings import settings as global_settings

        client = WorkerClient(
            base_url=global_settings.worker_light_url,
            heavy_url=global_settings.worker_heavy_url,
            session_id=session_id,
        )
        try:
            return await client.exists(artifact_path)
        finally:
            await client.aclose()
    except Exception as exc:
        logger.error(
            "benchmark_node_entry_artifact_lookup_failed",
            session_id=str(session_id),
            artifact_path=artifact_path,
            error=str(exc),
        )
        return False


async def _custom_benchmark_reviewer_handover_check(
    *, state: BenchmarkGeneratorState
) -> list[NodeEntryValidationError]:
    return await reviewer_handover_custom_check_from_session_id(
        session_id=_effective_benchmark_worker_session_id(state),
        reviewer_label="Benchmark",
        manifest_path=BENCHMARK_REVIEW_MANIFEST,
        expected_stage=AgentName.BENCHMARK_REVIEWER,
        agent_role=AgentName.BENCHMARK_REVIEWER,
    )


async def _custom_benchmark_plan_reviewer_handover_check(
    *, state: BenchmarkGeneratorState
) -> list[NodeEntryValidationError]:
    return await benchmark_plan_reviewer_handover_custom_check(
        contract=BENCHMARK_NODE_CONTRACTS[AgentName.BENCHMARK_PLAN_REVIEWER],
        state=state,
    )


def _format_entry_errors(errors: list[NodeEntryValidationError]) -> str:
    return "; ".join(f"{error.code}: {error.message}" for error in errors)


def _build_entry_rejection_feedback(
    *,
    target_node: AgentName,
    reason_code: str,
    disposition: str,
    reroute_target: AgentName | None,
    errors: list[NodeEntryValidationError],
) -> tuple[str, str]:
    action = (
        f"reroute={reroute_target.value}"
        if reroute_target is not None
        else f"disposition={disposition}"
    )
    detail = _format_entry_errors(errors)
    feedback = (
        f"ENTRY_VALIDATION_FAILED[{reason_code}] target={target_node.value} "
        f"{action} | {detail}"
    )
    journal_line = (
        f"[Entry Validation] target={target_node.value} disposition={disposition} "
        f"reason={reason_code} errors={detail}"
    )
    return feedback, journal_line


async def _evaluate_benchmark_node_entry(
    target_node: AgentName,
    state: BenchmarkGeneratorState,
):
    custom_checks = {
        BENCHMARK_PLAN_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: _custom_benchmark_plan_reviewer_handover_check(  # noqa: ARG005
                state=state
            )
        ),
        BENCHMARK_CODER_HANDOVER_CHECK: benchmark_coder_handover_custom_check,
        BENCHMARK_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: _custom_benchmark_reviewer_handover_check(  # noqa: ARG005
                state=state
            )
        ),
    }
    contract = BENCHMARK_NODE_CONTRACTS[target_node]
    return await evaluate_node_entry_contract(
        contract=contract,
        state=state,
        artifact_exists=lambda path: _artifact_exists_for_benchmark_state(state, path),
        graph=ValidationGraph.BENCHMARK,
        custom_checks=custom_checks,
    )


def _guarded_node(target_node: AgentName, node_callable):
    async def _run(state: BenchmarkGeneratorState):
        # Only first-class graph transitions are entry-guarded here.
        # Tool-invoked helper subagents remain explicitly out of scope.
        await _refresh_current_role_manifest(state, target_node)
        validation = await _evaluate_benchmark_node_entry(target_node, state)
        if validation.ok:
            state.entry_validation_rejected = False
            state.entry_validation_terminal = False
            state.entry_validation_reason_code = None
            state.entry_validation_target_node = None
            state.entry_validation_disposition = None
            state.entry_validation_reroute_target = None
            state.entry_validation_errors = []
            state.entry_validation_trace_emitted = False
            result = await node_callable(state)
            if target_node == AgentName.BENCHMARK_PLANNER and isinstance(
                result, BenchmarkGeneratorState
            ):
                planner_errors = await _validate_planner_handoff(
                    episode_id=uuid.UUID(str(result.episode_id)),
                    plan=result.plan,
                    custom_objectives=result.session.custom_objectives,
                    worker_session_id=result.worker_session_id,
                )
                if planner_errors:
                    logger.error(
                        "planner_handoff_validation_failed",
                        session_id=str(result.session.session_id),
                        errors=planner_errors,
                    )
                    result.session.validation_logs.extend(planner_errors)
                    result.review_feedback = "Planner handoff blocked: " + "; ".join(
                        planner_errors
                    )
                    result.session.status = SessionStatus.FAILED
                    result.hard_fail_code = "benchmark_handoff_validation"
            return result

        feedback, journal_line = _build_entry_rejection_feedback(
            target_node=target_node,
            reason_code=validation.reason_code,
            disposition=validation.disposition.value,
            reroute_target=validation.reroute_target,
            errors=validation.errors,
        )
        serialized_errors = [
            error.model_dump(mode="json") for error in validation.errors
        ]
        state.review_feedback = feedback
        state.journal = (state.journal + "\n" + journal_line).strip()
        state.entry_validation_rejected = True
        state.entry_validation_reason_code = validation.reason_code
        state.entry_validation_target_node = target_node.value
        state.entry_validation_disposition = validation.disposition.value
        state.entry_validation_reroute_target = (
            validation.reroute_target.value if validation.reroute_target else None
        )
        state.entry_validation_errors = serialized_errors
        state.session.validation_logs.append(feedback)

        emit_event(
            NodeEntryValidationFailedEvent(
                episode_id=state.episode_id,
                user_session_id=str(state.session.session_id),
                node=target_node.value,
                disposition=validation.disposition.value,
                reason_code=validation.reason_code,
                errors=serialized_errors,
                reroute_target=state.entry_validation_reroute_target,
            )
        )
        logger.error(
            "benchmark_node_entry_validation_rejected",
            episode_id=state.episode_id,
            session_id=str(state.session.session_id),
            target_node=target_node.value,
            disposition=validation.disposition.value,
            reason_code=validation.reason_code,
            reroute_target=(
                validation.reroute_target.value if validation.reroute_target else None
            ),
            integration_mode=integration_mode_enabled(),
            errors=serialized_errors,
        )

        if (
            validation.disposition.value == "reroute_previous"
            and validation.reroute_target is not None
        ):
            state.entry_validation_terminal = False
            state.session.status = SessionStatus.REJECTED
            return Command(
                goto=validation.reroute_target,
                update={
                    "session": state.session,
                    "review_feedback": state.review_feedback,
                    "journal": state.journal,
                    "entry_validation_rejected": True,
                    "entry_validation_terminal": False,
                    "entry_validation_reason_code": state.entry_validation_reason_code,
                    "entry_validation_target_node": state.entry_validation_target_node,
                    "entry_validation_disposition": state.entry_validation_disposition,
                    "entry_validation_reroute_target": (
                        state.entry_validation_reroute_target
                    ),
                    "entry_validation_errors": state.entry_validation_errors,
                    "entry_validation_trace_emitted": False,
                },
            )

        state.entry_validation_terminal = True
        state.session.status = SessionStatus.FAILED
        return Command(
            goto=END,
            update={
                "session": state.session,
                "review_feedback": state.review_feedback,
                "journal": state.journal,
                "entry_validation_rejected": True,
                "entry_validation_terminal": True,
                "entry_validation_reason_code": state.entry_validation_reason_code,
                "entry_validation_target_node": state.entry_validation_target_node,
                "entry_validation_disposition": state.entry_validation_disposition,
                "entry_validation_reroute_target": (
                    state.entry_validation_reroute_target
                ),
                "entry_validation_errors": state.entry_validation_errors,
                "entry_validation_trace_emitted": False,
            },
        )

    return _run


async def _validate_planner_handoff(
    episode_id: uuid.UUID,
    plan: Any | None,
    custom_objectives: CustomObjectives | None = None,
    *,
    worker_session_id: str | None = None,
) -> list[str]:
    """
    Validate benchmark planner output before allowing PLANNED state.

    Enforces:
    - Required planner files are present and structurally valid.
    - Explicit planner submission (`submit_benchmark_plan`) succeeded.
    - Structured planner output (`plan`) is present and schema-valid.
    - User-provided objective overrides are reflected in objectives constraints.
    """
    submission, submission_error = await _get_latest_planner_submission_result(
        episode_id
    )
    from controller.config.settings import settings as global_settings

    effective_worker_session_id = (
        worker_session_id
        or _effective_benchmark_worker_session_id(session_id=str(episode_id))
    )
    client = WorkerClient(
        base_url=global_settings.worker_light_url,
        heavy_url=global_settings.worker_heavy_url,
        session_id=effective_worker_session_id,
    )
    try:
        return await validate_benchmark_planner_handoff_artifacts(
            client,
            custom_objectives=custom_objectives,
            submission=submission,
            submission_error=submission_error,
            plan_output=plan,
            require_submission=True,
            require_structured_plan=True,
        )
    finally:
        await client.aclose()


async def _auto_continue_planned_session(
    session_id: uuid.UUID, delay_seconds: int = 20
):
    """Auto-continue benchmark sessions that remain in PLANNED state."""
    await asyncio.sleep(delay_seconds)

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, session_id)
        if not episode or episode.status != EpisodeStatus.PLANNED:
            return

    await continue_generation_session(session_id)


def define_graph():
    """
    Constructs the LangGraph for benchmark scenario generation.
    """
    workflow = StateGraph(BenchmarkGeneratorState)

    # Add nodes
    workflow.add_node(
        AgentName.BENCHMARK_PLANNER,
        _guarded_node(AgentName.BENCHMARK_PLANNER, planner_node),
    )
    workflow.add_node(
        AgentName.BENCHMARK_PLAN_REVIEWER,
        _guarded_node(AgentName.BENCHMARK_PLAN_REVIEWER, plan_reviewer_node),
    )
    workflow.add_node(
        AgentName.BENCHMARK_CODER,
        _guarded_node(AgentName.BENCHMARK_CODER, coder_node),
    )
    workflow.add_node(
        AgentName.BENCHMARK_REVIEWER,
        _guarded_node(AgentName.BENCHMARK_REVIEWER, reviewer_node),
    )
    workflow.add_node(
        AgentName.COTS_SEARCH,
        _guarded_node(AgentName.COTS_SEARCH, cots_search_node),
    )

    # Define transitions
    def route_start(
        state: BenchmarkGeneratorState,
    ) -> Literal[
        AgentName.BENCHMARK_PLANNER,
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_REVIEWER,
    ]:
        if state.start_node == AgentName.BENCHMARK_PLAN_REVIEWER.value:
            return AgentName.BENCHMARK_PLAN_REVIEWER
        if state.start_node == AgentName.BENCHMARK_CODER.value:
            return AgentName.BENCHMARK_CODER
        if state.start_node == AgentName.BENCHMARK_REVIEWER.value:
            return AgentName.BENCHMARK_REVIEWER
        if state.session.status == SessionStatus.VALIDATING:
            return AgentName.BENCHMARK_REVIEWER
        if state.session.status in [SessionStatus.EXECUTING, SessionStatus.PLANNED]:
            return AgentName.BENCHMARK_CODER
        return AgentName.BENCHMARK_PLANNER

    workflow.add_conditional_edges(START, route_start)

    async def planner_router(
        state: BenchmarkGeneratorState,
    ) -> Literal[
        AgentName.BENCHMARK_PLANNER,
        AgentName.BENCHMARK_PLAN_REVIEWER,
        END,
    ]:
        if state.session.status == SessionStatus.FAILED:
            return END
        planner_errors = await _validate_planner_handoff(
            episode_id=uuid.UUID(str(state.episode_id)),
            plan=state.plan,
            custom_objectives=state.session.custom_objectives,
            worker_session_id=state.worker_session_id,
        )
        if planner_errors:
            logger.error(
                "planner_handoff_validation_failed",
                session_id=str(state.session.session_id),
                errors=planner_errors,
            )
            state.session.status = SessionStatus.REJECTED
            state.review_feedback = "Planner handoff blocked: " + "; ".join(
                planner_errors
            )
            state.session.validation_logs.extend(planner_errors)
            return AgentName.BENCHMARK_PLANNER

        try:
            from controller.config.settings import settings as global_settings

            client = WorkerClient(
                base_url=global_settings.worker_light_url,
                heavy_url=global_settings.worker_heavy_url,
                session_id=_effective_benchmark_worker_session_id(state),
                agent_role=AgentName.BENCHMARK_PLAN_REVIEWER,
            )
            try:
                (
                    evidence,
                    evidence_error,
                ) = await collect_plan_reviewer_handover_evidence(
                    client,
                    manifest_path=BENCHMARK_PLAN_REVIEW_MANIFEST,
                    expected_stage=AgentName.BENCHMARK_PLAN_REVIEWER,
                    episode_id=state.episode_id,
                )
            finally:
                await client.aclose()
        except Exception as exc:
            evidence = None
            evidence_error = str(exc)

        if evidence is not None:
            state.session.validation_logs.append(
                "benchmark_plan_reviewer evidence: "
                f"revision={evidence.review_manifest_revision or 'unknown'} "
                f"renders={evidence.render_count} "
                f"refusal_reason="
                f"{evidence.refusal_reason.value if evidence.refusal_reason else 'none'}"
            )
        elif evidence_error:
            state.session.validation_logs.append(
                f"benchmark_plan_reviewer evidence unavailable: {evidence_error}"
            )

        state.review_decision = None
        state.review_feedback = None
        return AgentName.BENCHMARK_PLAN_REVIEWER

    workflow.add_conditional_edges(
        AgentName.BENCHMARK_PLANNER,
        planner_router,
        {
            AgentName.BENCHMARK_PLANNER: AgentName.BENCHMARK_PLANNER,
            AgentName.BENCHMARK_PLAN_REVIEWER: AgentName.BENCHMARK_PLAN_REVIEWER,
            END: END,
        },
    )

    async def plan_reviewer_router(
        state: BenchmarkGeneratorState,
    ) -> Literal[
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.BENCHMARK_PLANNER,
        END,
    ]:
        decision = state.review_decision
        if decision == ReviewDecision.APPROVED:
            state.session.status = SessionStatus.PLANNED
            return END
        if decision == ReviewDecision.REJECT_PLAN:
            state.session.status = SessionStatus.REJECTED
            # Explicit solvability rejections terminate the benchmark planning
            # attempt; the planner loop only retries malformed reviewer output.
            return END
        if decision == ReviewDecision.REJECTED:
            state.session.status = SessionStatus.REJECTED
            return AgentName.BENCHMARK_PLANNER

        state.session.status = SessionStatus.REJECTED
        if state.review_feedback:
            state.review_feedback = (
                "Plan reviewer output invalid: unsupported structured decision. "
                + state.review_feedback
            )
        else:
            state.review_feedback = (
                "Plan reviewer output invalid: missing structured review_decision."
            )
        # Retry reviewer output formatting failures in-place instead of bouncing
        # into planner retries that mutate planner artifacts without a decision.
        return AgentName.BENCHMARK_PLAN_REVIEWER

    workflow.add_conditional_edges(
        AgentName.BENCHMARK_PLAN_REVIEWER,
        plan_reviewer_router,
        {
            AgentName.BENCHMARK_PLAN_REVIEWER: AgentName.BENCHMARK_PLAN_REVIEWER,
            AgentName.BENCHMARK_PLANNER: AgentName.BENCHMARK_PLANNER,
            END: END,
        },
    )

    # In benchmark coder also does validation (it was coder -> validator -> reviewer)
    async def coder_router(
        state: BenchmarkGeneratorState,
    ) -> Literal[
        AgentName.BENCHMARK_REVIEWER,
        AgentName.BENCHMARK_CODER,
        END,
    ]:
        if state.session.status == SessionStatus.REJECTED:
            return AgentName.BENCHMARK_CODER

        if state.session.status == SessionStatus.FAILED:
            return END

        return AgentName.BENCHMARK_REVIEWER

    workflow.add_conditional_edges(
        AgentName.BENCHMARK_CODER,
        coder_router,
        {
            AgentName.BENCHMARK_REVIEWER: AgentName.BENCHMARK_REVIEWER,
            AgentName.BENCHMARK_CODER: AgentName.BENCHMARK_CODER,
            END: END,
        },
    )

    # Conditional edges for reviewer
    async def reviewer_router(
        state: BenchmarkGeneratorState,
    ) -> Literal[
        AgentName.BENCHMARK_REVIEWER,
        AgentName.BENCHMARK_CODER,
        AgentName.BENCHMARK_PLANNER,
        END,
    ]:
        if state.episode_id:
            try:
                threshold = agent_settings.context_compaction_threshold_tokens
                journal_tokens = estimate_text_tokens(state.journal or "")
                await update_episode_context_usage(
                    episode_id=state.episode_id,
                    used_tokens=journal_tokens,
                    max_tokens=threshold,
                )
            except Exception as exc:
                logger.warning(
                    "context_usage_event_emit_failed",
                    error=str(exc),
                    episode_id=state.episode_id,
                )

        hard_fail = await evaluate_agent_hard_fail(
            agent_name=AgentName.BENCHMARK_CODER,
            episode_id=state.episode_id,
            turn_count=state.turn_count,
        )
        if hard_fail.should_fail:
            state.session.status = SessionStatus.FAILED
            state.hard_fail_code = hard_fail.code
            state.session.validation_logs.append(
                hard_fail.message or "Agent hard-fail limit reached."
            )
            return END

        feedback = (state.review_feedback or "").upper()
        if feedback.startswith("REVIEWER OUTPUT INVALID:"):
            return AgentName.BENCHMARK_REVIEWER

        # Use structured decision if available
        if state.review_decision:
            if state.review_decision == ReviewDecision.APPROVED:
                return END
            if state.review_decision == ReviewDecision.CONFIRM_PLAN_REFUSAL:
                return END
            if state.review_decision == ReviewDecision.REJECT_PLAN:
                return AgentName.BENCHMARK_PLANNER
            if state.review_decision == ReviewDecision.REJECT_PLAN_REFUSAL:
                return AgentName.BENCHMARK_CODER
            return AgentName.BENCHMARK_CODER

        return AgentName.BENCHMARK_CODER

    workflow.add_conditional_edges(
        AgentName.BENCHMARK_REVIEWER,
        reviewer_router,
        {
            AgentName.BENCHMARK_REVIEWER: AgentName.BENCHMARK_REVIEWER,
            AgentName.BENCHMARK_CODER: AgentName.BENCHMARK_CODER,
            AgentName.BENCHMARK_PLANNER: AgentName.BENCHMARK_PLANNER,
            END: END,
        },
    )

    # cots_search can be reached from planner or coder if we add those edges
    workflow.add_edge(AgentName.COTS_SEARCH, AgentName.BENCHMARK_PLANNER)

    return workflow.compile()


async def _execute_graph_streaming(
    app: Any,
    initial_state: BenchmarkGeneratorState,
    session_id: uuid.UUID,
    prompt: str,
) -> BenchmarkGeneratorState:
    """Helper to run the graph with streaming and persistence."""
    final_state = initial_state
    runtime_tracker_fields = {
        "repeated_failure_stage",
        "repeated_failure_fingerprint",
        "repeated_failure_count",
        "reviewer_handoff_block_count",
        "turn_count",
    }

    # Database tracing
    db_callback = DatabaseCallbackHandler(
        episode_id=str(session_id), loop=asyncio.get_running_loop()
    )
    callbacks = [db_callback]
    config: Any = {"callbacks": callbacks}

    async for output in app.astream(initial_state, config=config):
        for node_name, state_update in output.items():
            normalized_node_name: AgentName | None = None
            if isinstance(node_name, AgentName):
                normalized_node_name = node_name
            elif isinstance(node_name, str):
                with suppress(ValueError):
                    normalized_node_name = AgentName(node_name)
                if normalized_node_name is None:
                    legacy_node_aliases = {
                        "planner": AgentName.BENCHMARK_PLANNER,
                        "plan_reviewer": AgentName.BENCHMARK_PLAN_REVIEWER,
                        "coder": AgentName.BENCHMARK_CODER,
                        "reviewer": AgentName.BENCHMARK_REVIEWER,
                    }
                    normalized_node_name = legacy_node_aliases.get(node_name)

            if state_update is None:
                logger.warning("node_returned_none", node_name=node_name)
                continue
            logger.info(
                "node_output_received",
                node_name=node_name,
                keys=list(state_update.keys()) if hasattr(state_update, "keys") else [],
            )

            # Update final_state (Pydantic model)
            if isinstance(state_update, dict):
                # Update field by field to avoid losing objects not in state_update
                for key, value in state_update.items():
                    if key in runtime_tracker_fields:
                        continue
                    if hasattr(final_state, key):
                        # Special handling for plan which is a
                        # RandomizationStrategy model
                        if key == "plan" and isinstance(value, dict):
                            import contextlib

                            from shared.simulation.schemas import RandomizationStrategy

                            with contextlib.suppress(Exception):
                                value = RandomizationStrategy.model_validate(value)
                        # Special handling for session which is a
                        # GenerationSession model
                        if key == "session" and isinstance(value, dict):
                            import contextlib

                            from .models import GenerationSession

                            with contextlib.suppress(Exception):
                                value = GenerationSession.model_validate(value)
                        setattr(final_state, key, value)
            elif isinstance(state_update, BenchmarkGeneratorState):
                for key in state_update.__class__.model_fields:
                    if key in runtime_tracker_fields:
                        continue
                    if hasattr(final_state, key):
                        setattr(final_state, key, getattr(state_update, key))

            # Determine new status
            new_status = final_state.session.status
            should_stop = False
            episode_phase: EpisodePhase | None = None
            terminal_reason: TerminalReason | None = None
            failure_class: FailureClass | None = None

            if normalized_node_name == AgentName.BENCHMARK_PLANNER:
                episode_phase = EpisodePhase.BENCHMARK_PLANNING
            elif normalized_node_name == AgentName.BENCHMARK_PLAN_REVIEWER:
                episode_phase = EpisodePhase.BENCHMARK_PLAN_REVIEWING
            elif normalized_node_name == AgentName.BENCHMARK_CODER:
                episode_phase = EpisodePhase.BENCHMARK_CODING
            elif normalized_node_name == AgentName.BENCHMARK_REVIEWER:
                episode_phase = EpisodePhase.BENCHMARK_REVIEWING

            if normalized_node_name is not None:
                final_state.turn_count = int(final_state.turn_count) + 1
                with suppress(Exception):
                    await persist_episode_turn_count(
                        episode_id=session_id,
                        turn_count=final_state.turn_count,
                    )

            if final_state.entry_validation_rejected:
                entry_validation_metadata = _entry_validation_metadata_from_state(
                    final_state
                )
                await _persist_entry_validation_rejection_trace(
                    session_id=session_id,
                    review_feedback=final_state.review_feedback,
                    metadata_payload=entry_validation_metadata,
                )
                final_state.entry_validation_trace_emitted = True
                if final_state.entry_validation_terminal:
                    new_status = SessionStatus.FAILED
                    terminal_reason = TerminalReason.HANDOFF_INVARIANT_VIOLATION
                    failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
                    final_state.session.validation_logs.append(
                        "entry_validation_fail_fast: benchmark node entry validation rejected "
                        f"target={final_state.entry_validation_target_node} "
                        f"reason={final_state.entry_validation_reason_code}"
                    )
                else:
                    new_status = SessionStatus.REJECTED
                    failure_class = (
                        FailureClass.AGENT_SEMANTIC_FAILURE
                        if _entry_validation_has_benchmark_refusal(final_state)
                        else FailureClass.AGENT_QUALITY_FAILURE
                    )
            elif normalized_node_name == AgentName.BENCHMARK_PLANNER:
                # Handle both object and dict types for the plan
                logger.info(
                    "checking_planner_output",
                    node=node_name,
                    plan=str(final_state.plan),
                )
                planner_errors = await _validate_planner_handoff(
                    episode_id=session_id,
                    plan=final_state.plan,
                    custom_objectives=final_state.session.custom_objectives,
                    worker_session_id=final_state.worker_session_id,
                )
                if planner_errors:
                    logger.error(
                        "planner_handoff_validation_failed",
                        session_id=str(session_id),
                        errors=planner_errors,
                    )
                    final_state.session.validation_logs.extend(planner_errors)
                    final_state.review_feedback = (
                        "Planner handoff blocked: " + "; ".join(planner_errors)
                    )
                    new_status = SessionStatus.REJECTED
                else:
                    new_status = SessionStatus.PLANNING
            elif normalized_node_name == AgentName.BENCHMARK_PLAN_REVIEWER:
                if final_state.review_decision == ReviewDecision.APPROVED:
                    new_status = SessionStatus.PLANNED
                    should_stop = True
                elif final_state.review_decision in {
                    ReviewDecision.REJECTED,
                    ReviewDecision.REJECT_PLAN,
                }:
                    new_status = SessionStatus.REJECTED
                    failure_class = FailureClass.AGENT_QUALITY_FAILURE
                else:
                    logger.error(
                        "benchmark_plan_reviewer_missing_structured_decision",
                        session_id=str(session_id),
                        feedback=final_state.review_feedback,
                    )
                    error_msg = (
                        "plan_reviewer_execution: missing or unsupported "
                        "structured review_decision"
                    )
                    final_state.session.validation_logs.append(error_msg)
                    final_state.review_feedback = (
                        "Plan reviewer output invalid: missing or unsupported "
                        "structured review_decision."
                    )
                    new_status = SessionStatus.REJECTED
                    failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
            elif normalized_node_name == AgentName.BENCHMARK_CODER:
                if final_state.session.status == SessionStatus.FAILED:
                    new_status = SessionStatus.FAILED
                    final_state.reviewer_handoff_block_count = 0
                elif final_state.session.status == SessionStatus.REJECTED:
                    new_status = SessionStatus.REJECTED
                    if _is_reviewer_handoff_blocked_feedback(
                        final_state.review_feedback
                    ):
                        final_state.reviewer_handoff_block_count += 1
                    else:
                        final_state.reviewer_handoff_block_count = 0
                else:
                    new_status = SessionStatus.VALIDATING
                    final_state.reviewer_handoff_block_count = 0
            elif normalized_node_name == AgentName.BENCHMARK_REVIEWER:
                if final_state.review_decision == ReviewDecision.APPROVED:
                    new_status = SessionStatus.ACCEPTED
                    final_state.reviewer_handoff_block_count = 0
                elif final_state.review_decision:
                    new_status = SessionStatus.REJECTED
                    failure_class = FailureClass.AGENT_QUALITY_FAILURE
                    if _is_reviewer_handoff_blocked_feedback(
                        final_state.review_feedback
                    ):
                        final_state.reviewer_handoff_block_count += 1
                    else:
                        final_state.reviewer_handoff_block_count = 0
                else:
                    logger.error(
                        "benchmark_reviewer_missing_structured_decision",
                        session_id=str(session_id),
                        feedback=final_state.review_feedback,
                    )
                    error_msg = "reviewer_execution: missing structured review_decision"
                    final_state.session.validation_logs.append(error_msg)
                    final_state.review_feedback = (
                        "Reviewer output invalid: missing structured review_decision."
                    )
                    new_status = SessionStatus.REJECTED
                    failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
                    final_state.reviewer_handoff_block_count = 0

                # Integration fail-fast: avoid long reject->coder->reviewer loops
                # when reviewer handoff invariants are repeatedly violated.
                if (
                    agent_settings.is_integration_test
                    and new_status == SessionStatus.REJECTED
                    and final_state.reviewer_handoff_block_count >= 2
                ):
                    new_status = SessionStatus.FAILED
                    terminal_reason = TerminalReason.HANDOFF_INVARIANT_VIOLATION
                    failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
                    final_state.session.validation_logs.append(
                        "integration_fail_fast: repeated reviewer handoff block"
                    )
                    logger.error(
                        "integration_fail_fast_reviewer_handoff_loop",
                        session_id=str(session_id),
                        handoff_block_count=final_state.reviewer_handoff_block_count,
                        review_feedback=final_state.review_feedback,
                    )

            repeated_failure_stages = {
                AgentName.BENCHMARK_PLANNER,
                AgentName.BENCHMARK_PLAN_REVIEWER,
                AgentName.BENCHMARK_CODER,
                AgentName.BENCHMARK_REVIEWER,
            }
            if normalized_node_name in repeated_failure_stages and new_status in {
                SessionStatus.REJECTED,
                SessionStatus.FAILED,
            }:
                fingerprint = _build_failure_fingerprint(
                    state=final_state,
                    stage=normalized_node_name,
                    status=new_status,
                )
                if fingerprint:
                    repeated_count = _record_repeated_failure(
                        state=final_state,
                        stage=normalized_node_name,
                        fingerprint=fingerprint,
                    )
                    logger.info(
                        "benchmark_failure_fingerprint_observed",
                        session_id=str(session_id),
                        stage=normalized_node_name.value,
                        repeated_count=repeated_count,
                    )
                    if (
                        new_status == SessionStatus.REJECTED
                        and repeated_count >= _REPEATED_FAILURE_FINGERPRINT_THRESHOLD
                    ):
                        (
                            terminal_reason,
                            failure_class,
                            failure_category,
                        ) = _classify_repeated_failure(fingerprint)
                        new_status = SessionStatus.FAILED
                        should_stop = True
                        final_state.session.validation_logs.append(
                            "fail_fast_repeated_failure_fingerprint: "
                            f"stage={normalized_node_name.value} "
                            f"count={repeated_count} "
                            f"category={failure_category}"
                        )
                        logger.error(
                            "benchmark_fail_fast_repeated_failure_fingerprint",
                            session_id=str(session_id),
                            stage=normalized_node_name.value,
                            repeated_count=repeated_count,
                            category=failure_category,
                        )
            else:
                _reset_repeated_failure(final_state)

            # Final terminal state logic
            if new_status == SessionStatus.ACCEPTED:
                terminal_reason = TerminalReason.APPROVED
            elif new_status == SessionStatus.FAILED:
                # Prefer structured hard-fail mapping when available.
                if final_state.hard_fail_code:
                    terminal_reason, failure_class = _map_hard_fail_metadata(
                        final_state.hard_fail_code
                    )
                else:
                    if not terminal_reason:
                        terminal_reason = TerminalReason.INTERNAL_ERROR
                    if not failure_class:
                        failure_class = FailureClass.APPLICATION_LOGIC_FAILURE

            # Update internal session status
            final_state.session.status = new_status

            # Update Persistence
            try:
                await _update_episode_persistence(
                    session_id=session_id,
                    new_status=new_status,
                    validation_logs=final_state.session.validation_logs,
                    prompt=prompt,
                    plan=final_state.plan,
                    journal=final_state.journal,
                    turn_count=final_state.turn_count,
                    episode_phase=episode_phase,
                    terminal_reason=terminal_reason,
                    failure_class=failure_class,
                    entry_validation_metadata=(
                        _entry_validation_metadata_from_state(final_state)
                        if final_state.entry_validation_rejected
                        else None
                    ),
                    worker_session_id=final_state.worker_session_id,
                )
            except Exception as e:
                logger.error(
                    "failed_to_update_episode_persistence",
                    error=str(e),
                    session_id=str(session_id),
                )

            if should_stop:
                logger.info("pausing_for_user_confirmation", session_id=session_id)
                # Persist assets so they are visible in UI during pause
                await _persist_session_assets(
                    final_state,
                    session_id,
                    final_state.worker_session_id,
                )
                return final_state

    # Report automated score to Langfuse
    try:
        # Get trace_id from OpenTelemetry context
        trace_id = None
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            trace_id = f"{span.get_span_context().trace_id:032x}"

        if trace_id:
            # WP10: Skip reporting score for the whole benchmark generation graph
            # as it doesn't map to a single agent reward config yet.
            pass
    except Exception as e:
        logger.error(
            "failed_to_report_benchmark_automated_score",
            error=str(e),
            session_id=str(session_id),
        )

    return final_state


async def run_generation_session(
    prompt: str,
    session_id: uuid.UUID | None = None,
    custom_objectives: CustomObjectives | None = None,
    seed_id: str | None = None,
    seed_dataset: str | None = None,
    generation_kind: GenerationKind | None = None,
    backend: SimulatorBackendType | None = None,
    start_node: str | AgentName | None = None,
) -> BenchmarkGeneratorState:
    """
    Entry point to run the full generation pipeline with persistence.
    """
    session_id = session_id or uuid4()
    logger.info(
        "running_generation_session",
        session_id=session_id,
        prompt=prompt,
        start_node=(
            start_node.value if isinstance(start_node, AgentName) else start_node
        ),
        backend=(backend or get_default_simulator_backend()),
    )
    backend = backend or get_default_simulator_backend()

    normalized_start_node: AgentName
    if start_node is None:
        normalized_start_node = AgentName.BENCHMARK_PLANNER
    elif isinstance(start_node, AgentName):
        normalized_start_node = start_node
    else:
        normalized_start_node = AgentName(start_node)

    if normalized_start_node == AgentName.BENCHMARK_CODER:
        initial_session_status = SessionStatus.EXECUTING
        initial_episode_phase = EpisodePhase.BENCHMARK_CODING
    elif normalized_start_node == AgentName.BENCHMARK_REVIEWER:
        initial_session_status = SessionStatus.VALIDATING
        initial_episode_phase = EpisodePhase.BENCHMARK_REVIEWING
    elif normalized_start_node == AgentName.BENCHMARK_PLAN_REVIEWER:
        initial_session_status = SessionStatus.PLANNING
        initial_episode_phase = EpisodePhase.BENCHMARK_PLAN_REVIEWING
    else:
        initial_session_status = SessionStatus.PLANNING
        initial_episode_phase = EpisodePhase.BENCHMARK_PLANNING

    # 1. Create DB entry (Episode)
    from controller.config.settings import settings
    from controller.utils.integration import apply_integration_test_metadata
    from shared.enums import EpisodeType, SeedMatchMethod
    from shared.models.schemas import EpisodeMetadata

    worker_session_id = str(session_id)

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        metadata = EpisodeMetadata(
            detailed_status=initial_session_status,
            episode_phase=initial_episode_phase,
            validation_logs=[],
            prompt=prompt,
            custom_objectives=custom_objectives,
            episode_type=EpisodeType.BENCHMARK,
            seed_id=seed_id,
            seed_dataset=seed_dataset,
            seed_match_method=SeedMatchMethod.RUNTIME_EXPLICIT if seed_id else None,
            generation_kind=generation_kind,
            parent_seed_id=seed_id,
        )
        metadata = apply_integration_test_metadata(
            metadata,
            is_integration_test=settings.is_integration_test,
            task=prompt,
            session_id=str(session_id),
        )
        metadata.worker_session_id = worker_session_id
        episode = Episode(
            id=session_id,
            task=prompt,
            status=EpisodeStatus.RUNNING,
            metadata_vars=metadata.model_dump(),
        )
        db.add(episode)
        await db.commit()

    # 2. Setup State
    session = GenerationSession(
        session_id=session_id,
        prompt=prompt,
        status=initial_session_status,
        custom_objectives=custom_objectives or {},
        backend=backend,
    )

    initial_state = BenchmarkGeneratorState(
        session=session,
        worker_session_id=worker_session_id,
        episode_id=str(session_id),
        current_script="",
        simulation_result=None,
        review_feedback=None,
        review_round=0,
        turn_count=0,
        plan=None,
        start_node=normalized_start_node.value,
        messages=[],
    )

    # 2.5. Initialize benchmark workspace templates before planner validation.
    # This guarantees required baseline files like benchmark_definition.yaml exist.
    try:
        from controller.config.settings import settings as global_settings

        worker_client = WorkerClient(
            base_url=global_settings.worker_light_url,
            session_id=worker_session_id,
            heavy_url=global_settings.worker_heavy_url,
        )
        try:
            middleware = RemoteFilesystemMiddleware(
                worker_client,
                agent_role=AgentName.BENCHMARK_PLANNER,
                episode_id=str(session_id),
            )
            backend = RemoteFilesystemBackend(middleware)
            await initialize_agent_files(
                backend,
                agent_name=AgentName.BENCHMARK_PLANNER,
                overwrite=True,
            )
            await seed_manufacturing_config(backend, overwrite=True)

        finally:
            await worker_client.aclose()
    except Exception as e:
        logger.warning(
            "benchmark_workspace_initialization_failed",
            session_id=session_id,
            error=str(e),
        )

    app = define_graph()
    await mark_episode_execution_window_start(session_id)

    try:
        # 3. Stream execution and checkpoint
        final_state = await _execute_graph_streaming(
            app, initial_state, session_id, prompt
        )
    except Exception as e:
        logger.warning("generation_session_failed", session_id=session_id, error=str(e))
        initial_state.session.status = SessionStatus.FAILED
        # Update DB (Episode) to failed
        async with session_factory() as db:
            episode = await db.get(Episode, session_id)
            if episode:
                from shared.models.schemas import EpisodeMetadata

                episode.status = EpisodeStatus.FAILED
                metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
                metadata.detailed_status = SessionStatus.FAILED
                metadata.error = str(e)

                # Set terminal reason and failure class
                metadata.terminal_reason = TerminalReason.INTERNAL_ERROR
                # Distinguish infra vs application if possible
                if any(
                    x in str(e).lower()
                    for x in ["worker", "network", "timeout", "http", "connection"]
                ):
                    metadata.failure_class = FailureClass.INFRA_DEVOPS_FAILURE
                    if "timeout" in str(e).lower():
                        metadata.terminal_reason = TerminalReason.TIMEOUT
                else:
                    metadata.failure_class = FailureClass.APPLICATION_LOGIC_FAILURE

                episode.metadata_vars = metadata.model_dump()
                await db.commit()
        return initial_state

    if final_state.session.status == SessionStatus.PLANNED:
        from controller.config.settings import settings

        if not settings.is_integration_test:
            asyncio.create_task(_auto_continue_planned_session(session_id))

    # 4. Final Asset Persistence
    await _persist_session_assets(
        final_state, session_id, final_state.worker_session_id
    )

    # 5. Final status update only after assets are synced.
    await _finalize_episode_terminal_status(session_id, final_state.session.status)

    logger.info(
        "generation_session_complete",
        session_id=session_id,
        status=final_state.session.status,
    )
    return final_state


async def _persist_session_assets(
    final_state: BenchmarkGeneratorState,
    session_id: uuid.UUID,
    worker_session_id: str | None = None,
):
    """
    Helper to persist assets.
    - Final artifacts (BenchmarkAsset) are only saved if status is ACCEPTED.
    - Real-time assets (Asset table + Broadcast) are synced if status is
      PLANNED or ACCEPTED.
    """
    from shared.enums import SessionStatus

    # 1. Final artifact persistence (BenchmarkAsset table)
    if final_state.session.status == SessionStatus.ACCEPTED:
        session_factory = get_sessionmaker()
        try:
            async with session_factory() as db:
                storage = BenchmarkStorage()

                sim_result = final_state.simulation_result
                render_data = sim_result.render_data if sim_result else []

                mjcf_content = (
                    final_state.mjcf_content or "<!-- MJCF content missing in state -->"
                )

                await storage.save_asset(
                    benchmark_id=session_id,
                    script=final_state.current_script,
                    mjcf=mjcf_content,
                    images=render_data,
                    metadata=final_state.plan.model_dump() if final_state.plan else {},
                    db=db,
                )
                logger.info("asset_persisted", session_id=session_id)
        except Exception as e:
            logger.warning("final_asset_persistence_failed", error=str(e))

    # 2. Real-time file sync (Asset table + Broadcast)
    # Allow this during PLANNED (pause), REJECTED (review decision persisted),
    # or ACCEPTED (completion). Rejected benchmark plan reviews still need the
    # latest revision render bundle and stage-specific review YAML surfaced as
    # episode assets for later inspection.
    if final_state.session.status not in (
        SessionStatus.ACCEPTED,
        SessionStatus.PLANNED,
        SessionStatus.REJECTED,
        SessionStatus.FAILED,
    ):
        return

    # Sync assets to the Asset table
    try:
        import base64
        from pathlib import Path

        from controller.config.settings import settings as global_settings

        worker_light_url = global_settings.worker_light_url
        effective_worker_session_id = (
            worker_session_id or final_state.worker_session_id or str(session_id)
        )
        async with httpx.AsyncClient() as http_client:
            client = WorkerClient(
                base_url=worker_light_url,
                session_id=effective_worker_session_id,
                http_client=http_client,
                heavy_url=global_settings.worker_heavy_url,
            )

            from controller.observability.middleware_helper import (
                broadcast_file_update,
            )

            # Some simulation backends return absolute temp paths from the heavy worker.
            # Register render assets explicitly so the episode handoff package remains
            # discoverable even when those files are not present in light-worker FS.
            sim_result = final_state.simulation_result
            if sim_result and sim_result.render_paths:
                for raw_path in sim_result.render_paths:
                    normalized = str(raw_path).strip()
                    if not normalized:
                        continue
                    if "renders/" in normalized:
                        normalized = "renders/" + normalized.split("renders/", 1)[1]
                    else:
                        normalized = f"renders/{Path(normalized).name}"
                    try:
                        await asyncio.wait_for(
                            broadcast_file_update(str(session_id), normalized, ""),
                            timeout=2.0,
                        )
                    except Exception:
                        continue

            # Ensure at least one discoverable render artifact exists for handoff.
            # Some simulation paths can complete without writing /renders in the
            # light-worker session (e.g., isolated heavy-worker temp outputs).
            try:
                render_entries = await asyncio.wait_for(
                    client.list_files("/renders/"), timeout=5.0
                )
                has_render_image = any(
                    (not e.is_dir)
                    and str(e.path).lower().endswith((".png", ".jpg", ".jpeg"))
                    for e in render_entries
                )
            except Exception:
                has_render_image = False

            if not has_render_image:
                tiny_png = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO5W8FcAAAAASUVORK5CYII="
                )
                try:
                    await asyncio.wait_for(
                        client.upload_file("renders/preview.png", tiny_png), timeout=5.0
                    )
                    await asyncio.wait_for(
                        broadcast_file_update(
                            str(session_id), "renders/preview.png", ""
                        ),
                        timeout=2.0,
                    )
                except Exception:
                    pass

            async def sync_workspace_review_dir() -> None:
                """Sync reviewer outputs from the session workspace, not the /reviews mount."""
                try:
                    review_files = await asyncio.wait_for(
                        client.list_files("reviews", bypass_agent_permissions=True),
                        timeout=5.0,
                    )
                except Exception:
                    return

                for file_info in review_files:
                    if file_info.is_dir:
                        continue
                    path = f"reviews/{file_info.name}"
                    content = ""
                    try:
                        content = await asyncio.wait_for(
                            client.read_file(path, bypass_agent_permissions=True),
                            timeout=2.0,
                        )
                    except Exception:
                        pass
                    await asyncio.wait_for(
                        broadcast_file_update(str(session_id), path, content),
                        timeout=2.0,
                    )

            # Only sync the session workspace root and critical directories to
            # avoid sweeping read-only mounts such as /utils or /skills.
            for dir_to_sync in ["/workspace", "/assets/", "/renders/"]:
                try:
                    files = await asyncio.wait_for(
                        client.list_files(dir_to_sync), timeout=5.0
                    )
                    for file_info in files:
                        if file_info.is_dir:
                            continue

                        path = file_info.path
                        # Skip obviously irrelevant files
                        if path.endswith((".log", ".lock", ".tmp", ".pyc")):
                            continue

                        # Text files: read content for preview
                        is_text = path.endswith(
                            (
                                ".py",
                                ".yaml",
                                ".yml",
                                ".md",
                                ".json",
                                ".txt",
                                ".mjcf",
                                ".xml",
                            )
                        )
                        content = ""
                        if is_text:
                            try:
                                content = await asyncio.wait_for(
                                    client.read_file(path), timeout=2.0
                                )
                            except Exception:
                                pass  # Proceed with empty content if read fails

                        # Broadcast to frontend. This will trigger sync_asset in
                        # middleware_helper which determines AssetType from extension.
                        await asyncio.wait_for(
                            broadcast_file_update(str(session_id), path, content),
                            timeout=2.0,
                        )
                except Exception:
                    continue

            await sync_workspace_review_dir()

            # Validation and simulation results can live under workspace/ in
            # benchmark-reviewer rejection paths. Surface them explicitly so the
            # episode asset list remains complete even when they are not copied to
            # the session root.
            for workspace_rel_path in (
                "workspace/validation_results.json",
                "workspace/simulation_result.json",
            ):
                try:
                    if not await asyncio.wait_for(
                        client.exists(
                            workspace_rel_path, bypass_agent_permissions=True
                        ),
                        timeout=5.0,
                    ):
                        continue
                    workspace_content = await asyncio.wait_for(
                        client.read_file(
                            workspace_rel_path, bypass_agent_permissions=True
                        ),
                        timeout=2.0,
                    )
                    await asyncio.wait_for(
                        broadcast_file_update(
                            str(session_id), workspace_rel_path, workspace_content
                        ),
                        timeout=2.0,
                    )
                except Exception:
                    continue

            # .manifests is system-owned metadata and may be denied via role policy
            # through the routed backend. Read it directly through WorkerClient so
            # reviewer manifests are still surfaced as episode assets.
            try:
                for manifest_path in (
                    ".manifests/benchmark_plan_review_manifest.json",
                    ".manifests/benchmark_review_manifest.json",
                    ".manifests/engineering_plan_review_manifest.json",
                    ".manifests/engineering_execution_handoff_manifest.json",
                    ".manifests/current_role.json",
                ):
                    if await asyncio.wait_for(
                        client.exists(manifest_path, bypass_agent_permissions=True),
                        timeout=5.0,
                    ):
                        manifest_content = await asyncio.wait_for(
                            client.read_file(
                                manifest_path, bypass_agent_permissions=True
                            ),
                            timeout=5.0,
                        )
                        await asyncio.wait_for(
                            broadcast_file_update(
                                str(session_id), manifest_path, manifest_content
                            ),
                            timeout=2.0,
                        )
            except Exception:
                pass
    except Exception as e:
        logger.error(
            "failed_to_sync_assets_to_db", error=str(e), session_id=str(session_id)
        )


async def _finalize_episode_terminal_status(
    session_id: uuid.UUID,
    session_status: SessionStatus,
) -> None:
    """Publish terminal Episode status after artifact sync has completed."""
    from shared.models.schemas import EpisodeMetadata

    if session_status not in (
        SessionStatus.ACCEPTED,
        SessionStatus.FAILED,
        SessionStatus.REJECTED,
    ):
        return

    target_status = (
        EpisodeStatus.COMPLETED
        if session_status == SessionStatus.ACCEPTED
        else EpisodeStatus.FAILED
    )
    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, session_id)
        if not episode:
            return
        if episode.status == target_status:
            return

        metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
        if target_status == EpisodeStatus.COMPLETED:
            metadata.detailed_status = EpisodeStatus.COMPLETED.value
        else:
            metadata.detailed_status = EpisodeStatus.FAILED.value
        episode.metadata_vars = metadata.model_dump()
        episode.status = target_status
        await db.commit()

        from controller.api.manager import manager

        await manager.broadcast(
            session_id,
            {
                "type": "status_update",
                "status": target_status,
                "metadata_vars": episode.metadata_vars,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )


async def _update_episode_persistence(
    session_id: uuid.UUID,
    new_status: str,
    validation_logs: list[str],
    prompt: str,
    plan: Any = None,
    journal: str | None = None,
    turn_count: int | None = None,
    episode_phase: EpisodePhase | None = None,
    terminal_reason: TerminalReason | None = None,
    failure_class: FailureClass | None = None,
    entry_validation_metadata: dict[str, Any] | None = None,
    worker_session_id: str | None = None,
):
    """Updates the Episode in DB for real-time monitoring."""
    from controller.persistence.models import Episode
    from shared.enums import EpisodeStatus

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, session_id)
        if episode:
            from shared.models.schemas import EpisodeMetadata

            # Map SessionStatus to EpisodeStatus for UI/Test polling
            if new_status == SessionStatus.PLANNED:
                episode.status = EpisodeStatus.PLANNED
            elif new_status == SessionStatus.FAILED:
                episode.status = EpisodeStatus.FAILED
            elif new_status == SessionStatus.ACCEPTED:
                # Completion is published only after _persist_session_assets finishes.
                episode.status = EpisodeStatus.RUNNING
            else:
                episode.status = EpisodeStatus.RUNNING

            metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
            if turn_count is not None:
                additional = dict(metadata.additional_info or {})
                additional["turn_count"] = int(turn_count)
                metadata.additional_info = additional
            if entry_validation_metadata is not None:
                additional = dict(metadata.additional_info or {})
                additional["entry_validation"] = entry_validation_metadata
                additional["entry_validation_terminal"] = bool(
                    entry_validation_metadata.get("disposition") == "fail_fast"
                    or new_status == SessionStatus.FAILED
                )
                metadata.additional_info = additional
            # Keep detailed_status aligned with terminal EpisodeStatus values so
            # UI polling that prefers detailed_status can detect completion.
            metadata.detailed_status = new_status

            if episode_phase:
                metadata.episode_phase = episode_phase

            # Terminal metadata must be cleared on non-terminal states to avoid
            # stale terminal labels leaking across retry loops.
            is_terminal_state = new_status in (
                SessionStatus.ACCEPTED,
                SessionStatus.FAILED,
            )
            if is_terminal_state:
                metadata.terminal_reason = terminal_reason
                metadata.failure_class = failure_class
            else:
                metadata.terminal_reason = None
                metadata.failure_class = None

            metadata.validation_logs = validation_logs
            metadata.prompt = prompt
            metadata.plan = plan.model_dump() if hasattr(plan, "model_dump") else plan
            episode.metadata_vars = metadata.model_dump()
            # Prefer real persisted session files when available.
            effective_worker_session_id = (
                worker_session_id
                or str(metadata.additional_info.get("worker_session_id") or "")
                or str(session_id)
            )
            plan_md = await _read_session_markdown(
                effective_worker_session_id, "benchmark_plan.md"
            )
            journal_md = await _read_session_markdown(
                effective_worker_session_id, "journal.md"
            )

            if plan_md:
                episode.plan = plan_md
            elif plan and not episode.plan:
                p = str(plan).strip()
                if p.startswith("#") and ("\n" in p):
                    episode.plan = p

            if journal_md:
                episode.journal = journal_md
            elif journal:
                j = journal.strip()
                if j:
                    episode.journal = j

            # Use episode.status which was just updated above
            status_to_broadcast = episode.status
            await db.commit()

            # Broadcast status update
            from controller.api.manager import manager

            await manager.broadcast(
                session_id,
                {
                    "type": "status_update",
                    "status": status_to_broadcast,
                    "metadata_vars": episode.metadata_vars,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )


async def continue_generation_session(
    session_id: uuid.UUID,
) -> BenchmarkGeneratorState | None:
    """
    Resumes a paused generation session from the 'coder' node.
    """
    logger.info("continuing_generation_session", session_id=session_id)

    session_factory = get_sessionmaker()
    async with session_factory() as db:
        episode = await db.get(Episode, session_id)
        if not episode:
            logger.error("episode_not_found_for_resume", session_id=session_id)
            return None

        from shared.models.schemas import EpisodeMetadata

        prompt = episode.task
        metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
        custom_objectives = (
            metadata.custom_objectives.model_dump()
            if metadata.custom_objectives
            else {}
        )
        saved_turn_count = int((metadata.additional_info or {}).get("turn_count") or 0)

        if episode.status != EpisodeStatus.PLANNED:
            observed_status = episode.status
            rejection_reason = (
                "ENTRY_VALIDATION_FAILED[state_invalid] target=benchmark_coder "
                "disposition=fail_fast | state_invalid: continue_generation_session "
                f"requires PLANNED episode status, got {observed_status}"
            )
            metadata.validation_logs.append(rejection_reason)
            additional = dict(metadata.additional_info or {})
            additional["entry_validation"] = {
                "node": AgentName.BENCHMARK_CODER.value,
                "disposition": "fail_fast",
                "reason_code": "state_invalid",
                "reroute_target": None,
                "errors": [
                    {
                        "code": "state_invalid",
                        "message": (
                            "continue_generation_session requires PLANNED "
                            f"episode status, got {observed_status}"
                        ),
                        "source": "state",
                        "artifact_path": None,
                    }
                ],
            }
            additional["entry_validation_terminal"] = True
            metadata.additional_info = additional
            metadata.detailed_status = SessionStatus.FAILED
            metadata.terminal_reason = TerminalReason.HANDOFF_INVARIANT_VIOLATION
            metadata.failure_class = FailureClass.AGENT_SEMANTIC_FAILURE
            episode.status = EpisodeStatus.FAILED
            episode.metadata_vars = metadata.model_dump()
            await db.commit()
            from controller.api.manager import manager

            await manager.broadcast(
                session_id,
                {
                    "type": "status_update",
                    "status": EpisodeStatus.FAILED,
                    "metadata_vars": episode.metadata_vars,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            logger.error(
                "continue_generation_invalid_episode_status",
                session_id=str(session_id),
                episode_status=observed_status,
            )
            return None

        restored_plan = None
        if metadata.plan:
            with suppress(Exception):
                restored_plan = RandomizationStrategy.model_validate(metadata.plan)

        # Reconstruct session with status 'EXECUTING' so define_graph routes to 'coder'
        worker_session_id = (
            metadata.worker_session_id
            or str((metadata.additional_info or {}).get("worker_session_id") or "")
            or str(session_id)
        )
        session = GenerationSession(
            session_id=session_id,
            prompt=prompt,
            status=SessionStatus.EXECUTING,
            custom_objectives=custom_objectives,
            validation_logs=metadata.validation_logs,
        )

        # Update episode status
        episode.status = EpisodeStatus.RUNNING
        metadata.detailed_status = SessionStatus.EXECUTING
        episode.metadata_vars = metadata.model_dump()
        await db.commit()

    initial_state = BenchmarkGeneratorState(
        session=session,
        worker_session_id=worker_session_id,
        episode_id=str(session_id),
        current_script="",
        simulation_result=None,
        review_feedback=None,
        review_round=0,
        turn_count=saved_turn_count,
        plan=restored_plan,
        start_node=AgentName.BENCHMARK_CODER.value,
        messages=[],
    )

    app = define_graph()
    await mark_episode_execution_window_start(session_id)

    try:
        final_state = await _execute_graph_streaming(
            app, initial_state, session_id, prompt
        )

        await _persist_session_assets(
            final_state, session_id, final_state.worker_session_id
        )
        await _finalize_episode_terminal_status(session_id, final_state.session.status)

        return final_state
    except Exception as e:
        logger.warning("resume_failed", error=str(e))

    return None
