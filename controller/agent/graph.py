from typing import Literal

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from controller.agent.config import settings as agent_settings
from controller.agent.context_usage import (
    estimate_text_tokens,
    update_episode_context_usage,
)
from controller.agent.execution_limits import evaluate_agent_hard_fail
from controller.agent.handover_constants import (
    ENGINEER_BENCHMARK_HANDOVER_CHECK,
    ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK,
    ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK,
    ENGINEERING_EXECUTION_HANDOFF_MANIFEST,
)
from controller.agent.node_entry_validation import (
    NodeEntryValidationError,
    ValidationGraph,
    _materialize_reviewer_handover,
    build_engineer_node_contracts,
    engineer_benchmark_handover_custom_check,
    engineer_planner_evidence_layout_custom_check,
    evaluate_node_entry_contract,
    integration_mode_enabled,
    plan_reviewer_handover_custom_check_from_session_id,
    reviewer_handover_custom_check_from_session_id,
)
from controller.clients.worker import WorkerClient
from controller.config.settings import settings as controller_settings
from controller.persistence.db import get_sessionmaker
from controller.persistence.models import Episode
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, GenerationKind
from shared.models.schemas import EpisodeMetadata
from shared.observability.events import emit_event
from shared.observability.schemas import NodeEntryValidationFailedEvent

from .nodes.coder import coder_node
from .nodes.execution_reviewer import engineer_execution_reviewer_node
from .nodes.plan_reviewer import engineer_plan_reviewer_node
from .nodes.planner import planner_node
from .state import AgentState, AgentStatus

logger = structlog.get_logger(__name__)

ENGINEER_NODE_CONTRACTS = build_engineer_node_contracts()


async def _refresh_current_role_manifest(
    state: AgentState, agent_name: AgentName
) -> None:
    worker_client = state.worker_client
    created_worker_client = False
    if worker_client is None:
        session_id = (state.session_id or "").strip()
        if not session_id:
            logger.warning(
                "current_role_manifest_refresh_skipped",
                agent_name=agent_name.value,
                reason="missing_session_id",
            )
            return
        worker_client = WorkerClient(
            base_url=controller_settings.worker_light_url,
            heavy_url=controller_settings.worker_heavy_url,
            session_id=session_id,
        )
        created_worker_client = True

    try:
        await worker_client.write_file(
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
            session_id=str(state.session_id),
            error=str(exc),
        )
    finally:
        if created_worker_client:
            await worker_client.aclose()


async def _engineer_plan_reviewer_handover_with_layout(*, contract, state):  # noqa: ANN001
    handover_errors = await plan_reviewer_handover_custom_check_from_session_id(
        session_id=(
            getattr(state, "worker_session_id", None)
            or getattr(state, "session_id", None)
        ),
    )
    if handover_errors:
        return handover_errors
    return await engineer_planner_evidence_layout_custom_check(
        contract=contract,
        state=state,
    )


async def _engineer_execution_reviewer_handover_with_layout(*, contract, state):  # noqa: ANN001
    handover_errors = await reviewer_handover_custom_check_from_session_id(
        session_id=(
            getattr(state, "worker_session_id", None)
            or getattr(state, "session_id", None)
        ),
        reviewer_label="Execution",
        manifest_path=ENGINEERING_EXECUTION_HANDOFF_MANIFEST,
        expected_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        agent_role=AgentName.ENGINEER_EXECUTION_REVIEWER,
    )
    if handover_errors:
        return handover_errors
    return await engineer_planner_evidence_layout_custom_check(
        contract=contract,
        state=state,
    )


async def _sidecars_disabled_for_state(state: AgentState) -> bool:
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


def _requested_start_node(state: AgentState) -> AgentName | None:
    start_node = (state.start_node or "").strip()
    if not start_node:
        return None
    try:
        return AgentName(start_node)
    except ValueError:
        return None


async def _should_end_scoped_run_after_node(
    state: AgentState, completed_node: AgentName
) -> bool:
    return (
        await _sidecars_disabled_for_state(state)
        and _requested_start_node(state) == completed_node
    )


async def _artifact_exists_for_state(state: AgentState, artifact_path: str) -> bool:
    session_id = (state.session_id or "").strip()
    if not session_id:
        logger.error(
            "node_entry_validation_session_missing",
            artifact_path=artifact_path,
            target_node=getattr(state, "current_step", ""),
            session_id=None,
        )
        return False

    client = WorkerClient(
        base_url=controller_settings.worker_light_url,
        heavy_url=controller_settings.worker_heavy_url,
        session_id=session_id,
    )
    try:
        return await client.exists(artifact_path)
    except Exception as exc:
        logger.error(
            "node_entry_validation_artifact_lookup_failed",
            artifact_path=artifact_path,
            session_id=session_id,
            error=str(exc),
        )
        return False
    finally:
        await client.aclose()


def _format_entry_errors(errors: list[NodeEntryValidationError]) -> str:
    return "; ".join(f"{error.code}: {error.message}" for error in errors)


def _build_entry_rejection_feedback(
    *,
    target_node: AgentName,
    result,
) -> tuple[str, str]:
    action = (
        f"reroute={result.reroute_target.value}"
        if result.reroute_target
        else f"disposition={result.disposition.value}"
    )
    detail = _format_entry_errors(result.errors)
    feedback = (
        f"ENTRY_VALIDATION_FAILED[{result.reason_code}] "
        f"target={target_node.value} {action} | {detail}"
    )
    journal_entry = (
        f"[Entry Validation] target={target_node.value} "
        f"disposition={result.disposition.value} reason={result.reason_code} "
        f"errors={detail}"
    )
    return feedback, journal_entry


async def _normalize_engineer_reroute_target(
    target_node: AgentName, state: AgentState, validation
):
    return validation


async def _evaluate_engineer_node_entry(target_node: AgentName, state: AgentState):
    custom_checks = {
        ENGINEER_BENCHMARK_HANDOVER_CHECK: (
            lambda *, contract, state: engineer_benchmark_handover_custom_check(
                contract=contract,
                state=state,
            )
        ),
        ENGINEER_PLAN_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: _engineer_plan_reviewer_handover_with_layout(
                contract=contract,
                state=state,
            )
        ),
        ENGINEER_EXECUTION_REVIEWER_HANDOVER_CHECK: (
            lambda *, contract, state: (
                _engineer_execution_reviewer_handover_with_layout(
                    contract=contract,
                    state=state,
                )
            )
        ),
        ENGINEER_PLANNER_EVIDENCE_LAYOUT_CHECK: (
            lambda *, contract, state: engineer_planner_evidence_layout_custom_check(
                contract=contract,
                state=state,
            )
        ),
    }
    contract = ENGINEER_NODE_CONTRACTS[target_node]
    return await evaluate_node_entry_contract(
        contract=contract,
        state=state,
        artifact_exists=lambda path: _artifact_exists_for_state(state, path),
        graph=ValidationGraph.ENGINEER,
        custom_checks=custom_checks,
    )


def _guarded_node(target_node: AgentName, node_callable):
    async def _run(state: AgentState):
        # Entry validation is intentionally scoped to first-class graph transitions.
        # Tool-invoked helper subagents are out of scope for this contract.
        await _refresh_current_role_manifest(state, target_node)
        validation = await _evaluate_engineer_node_entry(target_node, state)
        validation = await _normalize_engineer_reroute_target(
            target_node, state, validation
        )
        if validation.ok:
            state.entry_validation_rejected = False
            state.entry_validation_terminal = False
            state.entry_validation_reason_code = None
            state.entry_validation_target_node = None
            state.entry_validation_disposition = None
            state.entry_validation_reroute_target = None
            state.entry_validation_errors = []
            state.entry_validation_trace_emitted = False
            return await node_callable(state)

        feedback, journal_line = _build_entry_rejection_feedback(
            target_node=target_node,
            result=validation,
        )
        serialized_errors = [
            error.model_dump(mode="json") for error in validation.errors
        ]
        current_journal = state.journal or ""
        update = {
            "feedback": feedback,
            "journal": (current_journal + "\n" + journal_line).strip(),
            "entry_validation_rejected": True,
            "entry_validation_reason_code": validation.reason_code,
            "entry_validation_target_node": target_node.value,
            "entry_validation_disposition": validation.disposition.value,
            "entry_validation_reroute_target": (
                validation.reroute_target.value if validation.reroute_target else None
            ),
            "entry_validation_errors": serialized_errors,
            "entry_validation_trace_emitted": False,
        }

        emit_event(
            NodeEntryValidationFailedEvent(
                episode_id=state.episode_id or None,
                user_session_id=state.session_id or None,
                node=target_node.value,
                disposition=validation.disposition.value,
                reason_code=validation.reason_code,
                errors=serialized_errors,
                reroute_target=(
                    validation.reroute_target.value
                    if validation.reroute_target
                    else None
                ),
            )
        )
        logger.error(
            "node_entry_validation_rejected",
            episode_id=state.episode_id,
            session_id=str(state.session_id),
            target_node=target_node.value,
            disposition=validation.disposition.value,
            reason_code=validation.reason_code,
            reroute_target=(
                validation.reroute_target.value if validation.reroute_target else None
            ),
            integration_mode=await _sidecars_disabled_for_state(state),
            errors=serialized_errors,
        )

        if (
            validation.disposition.value == "reroute_previous"
            and validation.reroute_target is not None
        ):
            update["entry_validation_terminal"] = False
            return Command(goto=validation.reroute_target, update=update)

        update["status"] = AgentStatus.FAILED
        update["entry_validation_terminal"] = True
        return Command(goto=END, update=update)

    return _run


async def should_continue(state: AgentState) -> str:
    """Route after reviewer based on approval status."""
    if state.episode_id:
        try:
            threshold = agent_settings.context_compaction_threshold_tokens
            journal_tokens = estimate_text_tokens(state.journal)
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
        agent_name=AgentName.ENGINEER_CODER,
        episode_id=state.episode_id,
        turn_count=state.turn_count,
    )
    if hard_fail.should_fail:
        state.status = AgentStatus.FAILED
        state.feedback = hard_fail.message or "Agent hard-fail limit reached."
        state.journal = (
            state.journal + "\n[Hard Fail] " + (hard_fail.message or "quota reached")
        ).strip()
        return END

    if state.status == AgentStatus.APPROVED or state.status == AgentStatus.FAILED:
        if await _should_end_scoped_run_after_node(
            state, AgentName.ENGINEER_EXECUTION_REVIEWER
        ):
            return END
        # T010: Check if there are more steps in TODO before finishing
        if state.status == AgentStatus.APPROVED and "- [ ]" in state.todo:
            logger.info("step_approved_continuing_to_next", todo=state.todo)
            return AgentName.ENGINEER_CODER
        return END

    if await _should_end_scoped_run_after_node(
        state, AgentName.ENGINEER_EXECUTION_REVIEWER
    ):
        return END

    # If rejected and we haven't looped too many times
    if state.iteration < 5:
        if state.status == AgentStatus.PLAN_REJECTED:
            return AgentName.ENGINEER_PLANNER
        return AgentName.ENGINEER_CODER

    return END


async def should_continue_after_plan_review(state: AgentState) -> str:
    """Route after plan reviewer. Approved plans must proceed to implementation."""
    if state.episode_id:
        try:
            threshold = agent_settings.context_compaction_threshold_tokens
            journal_tokens = estimate_text_tokens(state.journal)
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

    if state.status == AgentStatus.APPROVED:
        if await _should_end_scoped_run_after_node(
            state, AgentName.ENGINEER_PLAN_REVIEWER
        ):
            return END
        return AgentName.ENGINEER_CODER

    hard_fail = await evaluate_agent_hard_fail(
        agent_name=AgentName.ENGINEER_CODER,
        episode_id=state.episode_id,
        turn_count=state.turn_count,
    )
    if hard_fail.should_fail:
        state.status = AgentStatus.FAILED
        state.feedback = hard_fail.message or "Agent hard-fail limit reached."
        state.journal = (
            state.journal + "\n[Hard Fail] " + (hard_fail.message or "quota reached")
        ).strip()
        return END

    if state.status == AgentStatus.FAILED:
        return END

    if await _should_end_scoped_run_after_node(state, AgentName.ENGINEER_PLAN_REVIEWER):
        return END

    if state.iteration < 5:
        if state.status == AgentStatus.PLAN_REJECTED:
            return AgentName.ENGINEER_PLANNER
        return AgentName.ENGINEER_CODER

    return END


async def route_after_engineer_planner(
    state: AgentState,
) -> Literal[
    AgentName.ENGINEER_PLAN_REVIEWER,
    END,
]:
    if await _should_end_scoped_run_after_node(state, AgentName.ENGINEER_PLANNER):
        return END
    return AgentName.ENGINEER_PLAN_REVIEWER


async def route_after_engineer_coder(
    state: AgentState,
) -> Literal[
    AgentName.ENGINEER_EXECUTION_REVIEWER,
    END,
]:
    if await _should_end_scoped_run_after_node(state, AgentName.ENGINEER_CODER):
        return END
    worker_client = state.worker_client
    created_worker_client = False
    if worker_client is None:
        worker_client = WorkerClient(
            base_url=controller_settings.worker_light_url,
            heavy_url=controller_settings.worker_heavy_url,
            session_id=state.session_id,
        )
        created_worker_client = True
    try:
        handover_error = await _materialize_reviewer_handover(
            worker_client,
            reviewer_stage=AgentName.ENGINEER_EXECUTION_REVIEWER,
        )
        if handover_error:
            logger.warning(
                "engineer_execution_handover_materialization_failed",
                episode_id=state.episode_id,
                session_id=state.session_id,
                error=handover_error,
            )
    finally:
        if created_worker_client:
            await worker_client.aclose()
    return AgentName.ENGINEER_EXECUTION_REVIEWER


# Initialize the StateGraph with our AgentState
builder = StateGraph(AgentState)

# Add nodes
builder.add_node(
    AgentName.ENGINEER_PLANNER,
    _guarded_node(AgentName.ENGINEER_PLANNER, planner_node),
)
builder.add_node(
    AgentName.ENGINEER_PLAN_REVIEWER,
    _guarded_node(AgentName.ENGINEER_PLAN_REVIEWER, engineer_plan_reviewer_node),
)
builder.add_node(
    AgentName.ENGINEER_CODER,
    _guarded_node(AgentName.ENGINEER_CODER, coder_node),
)
builder.add_node(
    AgentName.ENGINEER_EXECUTION_REVIEWER,
    _guarded_node(
        AgentName.ENGINEER_EXECUTION_REVIEWER, engineer_execution_reviewer_node
    ),
)


# Set the entry point and edges
def route_start(
    state: AgentState,
) -> Literal[
    AgentName.ENGINEER_PLANNER,
    AgentName.ENGINEER_PLAN_REVIEWER,
    AgentName.ENGINEER_CODER,
    AgentName.ENGINEER_EXECUTION_REVIEWER,
]:
    start_node = (state.start_node or "").strip()
    if not start_node:
        return AgentName.ENGINEER_PLANNER

    try:
        requested = AgentName(start_node)
    except ValueError:
        logger.warning("invalid_engineer_start_node", start_node=start_node)
        return AgentName.ENGINEER_PLANNER

    allowed_start_nodes = {
        AgentName.ENGINEER_PLANNER,
        AgentName.ENGINEER_PLAN_REVIEWER,
        AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_EXECUTION_REVIEWER,
    }
    if requested not in allowed_start_nodes:
        logger.warning("unsupported_engineer_start_node", start_node=start_node)
        return AgentName.ENGINEER_PLANNER

    return requested


builder.add_conditional_edges(START, route_start)
builder.add_conditional_edges(
    AgentName.ENGINEER_PLANNER,
    route_after_engineer_planner,
    {
        AgentName.ENGINEER_PLAN_REVIEWER: AgentName.ENGINEER_PLAN_REVIEWER,
        END: END,
    },
)

builder.add_conditional_edges(
    AgentName.ENGINEER_PLAN_REVIEWER,
    should_continue_after_plan_review,
    {
        AgentName.ENGINEER_CODER: AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_PLANNER: AgentName.ENGINEER_PLANNER,
        END: END,
    },
)

builder.add_conditional_edges(
    AgentName.ENGINEER_CODER,
    route_after_engineer_coder,
    {
        AgentName.ENGINEER_EXECUTION_REVIEWER: AgentName.ENGINEER_EXECUTION_REVIEWER,
        END: END,
    },
)

# Conditional routing from execution reviewer
builder.add_conditional_edges(
    AgentName.ENGINEER_EXECUTION_REVIEWER,
    should_continue,
    {
        AgentName.ENGINEER_CODER: AgentName.ENGINEER_CODER,
        AgentName.ENGINEER_PLANNER: AgentName.ENGINEER_PLANNER,
        END: END,
    },
)

# T026: Implement Checkpointing
memory = MemorySaver()

graph = builder.compile(checkpointer=memory)


def _build_single_node_graph(node_name: AgentName, node_callable):
    single = StateGraph(AgentState)
    single.add_node(node_name, _guarded_node(node_name, node_callable))
    single.add_edge(START, node_name)
    single.add_edge(node_name, END)
    return single.compile(checkpointer=MemorySaver())


engineer_planner_graph = _build_single_node_graph(
    AgentName.ENGINEER_PLANNER, planner_node
)
