from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from controller.agent.node_entry_validation import (
    _materialize_reviewer_handover,
    reviewer_handover_custom_check_from_session_id,
)
from controller.agent.review_handover import validate_reviewer_handover
from controller.clients.worker import WorkerClient
from evals.logic.codex_workspace import (
    copy_workspace_contents as _copy_workspace_contents,
)
from evals.logic.codex_workspace import launch_cli_exec as _launch_cli_exec
from evals.logic.codex_workspace import (
    materialize_seed_workspace as _materialize_workspace,
)
from evals.logic.codex_workspace import (
    verify_workspace_for_agent as _verify_workspace_for_agent,
)
from evals.logic.models import AgentEvalSpec, EvalDatasetItem
from evals.logic.review_checks import (
    requires_expected_review_decision as _requires_expected_review_decision,
)
from evals.logic.specs import (
    AGENT_SPECS,
    JUDGE_REVIEWER_CHAIN,
)
from shared.agents.config import load_agents_config
from shared.enums import (
    AgentName,
    EpisodeStatus,
    EvalMode,
    ResponseStatus,
    ReviewDecision,
)
from shared.logging import get_logger
from shared.models.schemas import EpisodeMetadata

logger = get_logger(__name__)


def _episode_terminal(status: str | None) -> bool:
    if not status:
        return False
    return status in {
        EpisodeStatus.COMPLETED,
        EpisodeStatus.FAILED,
        EpisodeStatus.CANCELLED,
    }


def _planned_counts_as_success(agent_name: AgentName, spec: AgentEvalSpec) -> bool:
    if agent_name == AgentName.BENCHMARK_PLAN_REVIEWER:
        return True
    if spec.mode == EvalMode.BENCHMARK and not _requires_expected_review_decision(spec):
        return True
    return agent_name in {
        AgentName.ENGINEER_PLANNER,
        AgentName.BENCHMARK_PLANNER,
    }


def _validate_unit_eval_allowlist(agent_name: AgentName, spec: AgentEvalSpec) -> None:
    config = load_agents_config()
    allowed = config.get_allowed_during_unit_eval(agent_name)
    if not allowed:
        raise ValueError(
            f"unit-eval allowlist missing for {agent_name.value}; "
            "configure allowed_during_unit_eval in config/agents_config.yaml"
        )

    required_roles: set[AgentName] = {agent_name}
    if spec.request_agent_name is not None:
        required_roles.add(spec.request_agent_name)
    if spec.start_node is not None:
        required_roles.add(spec.start_node)
    required_roles.update(JUDGE_REVIEWER_CHAIN.get(agent_name, ()))

    allowed_set = set(allowed)
    missing_roles = sorted(
        role.value for role in required_roles if role not in allowed_set
    )
    if missing_roles:
        allowed_roles = ", ".join(role.value for role in allowed)
        raise ValueError(
            f"unit-eval allowlist for {agent_name.value} is missing required roles: "
            f"{', '.join(missing_roles)}. Allowed roles: {allowed_roles}"
        )


async def _wait_for_controller_ready(
    controller_url: str,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_error: str | None = None

    async with httpx.AsyncClient(timeout=5.0) as client:
        while time.monotonic() < deadline:
            attempt += 1
            try:
                health_resp = await client.get(f"{controller_url}/health")
                health_payload = health_resp.json()
                if (
                    health_resp.status_code == 200
                    and health_payload.get("status") == "healthy"
                ):
                    logger.info("controller_health_check_ok", attempts=attempt)
                    return
                last_error = (
                    f"status_code={health_resp.status_code}, "
                    f"status={health_payload.get('status')}"
                )
            except Exception as exc:
                last_error = str(exc)

            logger.warning(
                "controller_health_check_retry", attempt=attempt, error=last_error
            )
            await asyncio.sleep(poll_interval_seconds)

    raise RuntimeError(
        "Controller did not become healthy within "
        f"{timeout_seconds}s. last_error={last_error}"
    )


async def _wait_for_worker_ready(
    worker_light_url: str,
    timeout_seconds: float = 60.0,
    poll_interval_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_error: str | None = None
    temp_client = WorkerClient(base_url=worker_light_url, session_id="healthcheck")

    while time.monotonic() < deadline:
        attempt += 1
        try:
            health = await temp_client.get_health()
            if health.status == ResponseStatus.HEALTHY:
                logger.info("worker_health_check_ok", attempts=attempt)
                return
            last_error = f"status={health.status}"
        except Exception as exc:
            last_error = str(exc)

        logger.warning("worker_health_check_retry", attempt=attempt, error=last_error)
        await asyncio.sleep(poll_interval_seconds)

    raise RuntimeError(
        "Worker did not become healthy within "
        f"{timeout_seconds}s. last_error={last_error}"
    )


async def _fetch_episode(
    controller_url: str, client: httpx.AsyncClient, episode_id: str
) -> dict[str, Any]:
    response = await client.get(f"{controller_url}/episodes/{episode_id}")
    response.raise_for_status()
    return response.json()


async def _request_episode_interrupt(
    controller_url: str,
    episode_id: str,
    *,
    log,
) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{controller_url}/episodes/{episode_id}/interrupt"
            )
        if resp.status_code in {200, 202}:
            log.warning("eval_interrupt_requested", episode_id=episode_id)
            return
        log.warning(
            "eval_interrupt_request_failed",
            episode_id=episode_id,
            status_code=resp.status_code,
            response_text=resp.text,
        )
    except Exception:
        log.exception("eval_interrupt_request_exception", episode_id=episode_id)


def _trace_names_lower(episode: dict[str, Any]) -> set[str]:
    traces = episode.get("traces") or []
    names = set()
    for trace in traces:
        name = trace.get("name")
        if isinstance(name, str) and name:
            names.add(name.lower())
    return names


def _missing_required_traces(
    required: tuple[AgentName, ...], episode: dict[str, Any]
) -> list[str]:
    names = _trace_names_lower(episode)
    return [trace.value for trace in required if trace.value.lower() not in names]


async def _run_reviewer_episode_for_judge(
    *,
    controller_url: str,
    client: httpx.AsyncClient,
    reviewer_agent: AgentName,
    session_id: str,
    task_description: str,
    lineage: EpisodeMetadata,
    log,
) -> dict[str, Any] | None:
    reviewer_spec = AGENT_SPECS.get(reviewer_agent)
    if reviewer_spec is None:
        log.warning("judge_reviewer_spec_missing", reviewer_agent=reviewer_agent.value)
        return None

    payload = {
        "task": task_description,
        "agent_name": reviewer_agent,
        "start_node": reviewer_agent,
        "session_id": session_id,
        "metadata_vars": lineage.model_dump(exclude_none=True),
    }
    response = await client.post(f"{controller_url}/agent/run", json=payload)
    if response.status_code >= 400:
        log.warning(
            "judge_reviewer_trigger_failed",
            reviewer_agent=reviewer_agent.value,
            status_code=response.status_code,
            response_text=response.text,
            session_id=session_id,
        )
        return None

    response_data = response.json()
    episode_id = str(response_data.get("episode_id") or "")
    if not episode_id:
        log.warning(
            "judge_reviewer_missing_episode_id",
            reviewer_agent=reviewer_agent.value,
            session_id=session_id,
        )
        return None

    log.info(
        "judge_reviewer_triggered",
        reviewer_agent=reviewer_agent.value,
        episode_id=episode_id,
        session_id=session_id,
    )

    max_attempts = 60
    attempt = 0
    latest_episode: dict[str, Any] | None = None
    while attempt < max_attempts:
        attempt += 1
        await asyncio.sleep(5)
        try:
            latest_episode = await _fetch_episode(controller_url, client, episode_id)
        except Exception:
            log.exception(
                "judge_reviewer_status_fetch_failed",
                reviewer_agent=reviewer_agent.value,
                episode_id=episode_id,
            )
            continue

        status = latest_episode.get("status")
        if status == EpisodeStatus.PLANNED or _episode_terminal(status):
            break

    if latest_episode is None:
        log.warning(
            "judge_reviewer_no_episode_data",
            reviewer_agent=reviewer_agent.value,
            episode_id=episode_id,
        )
        return None

    if attempt >= max_attempts and not _episode_terminal(latest_episode.get("status")):
        log.warning(
            "judge_reviewer_timeout",
            reviewer_agent=reviewer_agent.value,
            episode_id=episode_id,
            max_attempts=max_attempts,
        )

    missing_traces = _missing_required_traces(
        reviewer_spec.required_trace_names, latest_episode
    )
    if missing_traces:
        log.warning(
            "judge_reviewer_missing_traces",
            reviewer_agent=reviewer_agent.value,
            episode_id=episode_id,
            missing_traces=missing_traces,
        )

    return latest_episode


async def _run_reviewer_chain_for_judge(
    *,
    controller_url: str,
    client: httpx.AsyncClient,
    agent_name: AgentName,
    session_id: str,
    task_description: str,
    lineage: EpisodeMetadata,
    log,
) -> list[dict[str, Any]]:
    reviewer_chain = JUDGE_REVIEWER_CHAIN.get(agent_name, ())
    if not reviewer_chain:
        return []

    episodes: list[dict[str, Any]] = []
    for reviewer_agent in reviewer_chain:
        episode = await _run_reviewer_episode_for_judge(
            controller_url=controller_url,
            client=client,
            reviewer_agent=reviewer_agent,
            session_id=session_id,
            task_description=task_description,
            lineage=lineage,
            log=log,
        )
        if episode is not None:
            episodes.append(episode)
    return episodes


def _decision_value_to_enum(value: Any) -> ReviewDecision | None:
    if value is None:
        return None
    if isinstance(value, ReviewDecision):
        return value
    text = getattr(value, "value", value)
    if isinstance(text, str):
        with contextlib.suppress(ValueError):
            return ReviewDecision(text)
    return None


def _reviewer_metrics_from_verification(
    *,
    verification_result: Any,
    expected_decision: ReviewDecision | None,
) -> dict[str, Any]:
    if isinstance(verification_result, dict):
        success = bool(verification_result.get("success", False))
        details = verification_result.get("details")
    else:
        success = bool(getattr(verification_result, "success", False))
        details = getattr(verification_result, "details", None)

    metrics: dict[str, Any] = {"review_artifacts_complete": success}
    if not isinstance(details, dict):
        return metrics

    review_decision = details.get("review_decision")
    if isinstance(review_decision, dict):
        decision = _decision_value_to_enum(review_decision.get("decision"))
        if decision is not None:
            metrics["reviewer_decision"] = decision.value
            metrics["reviewer_accepted"] = decision == ReviewDecision.APPROVED
            review_summary = details.get("review_comments")
            if isinstance(review_summary, dict):
                summary = review_summary.get("summary")
                if isinstance(summary, str):
                    metrics["reviewer_feedback"] = summary
                checklist = review_summary.get("checklist")
                if isinstance(checklist, dict):
                    metrics["checklist"] = checklist
            if expected_decision is not None:
                metrics["decision_correct"] = decision == expected_decision
            else:
                metrics["decision_correct"] = decision == ReviewDecision.APPROVED
            metrics["review_actionable"] = decision != ReviewDecision.APPROVED

    return metrics


async def _run_reviewer_chain_for_judge(
    *,
    item: EvalDatasetItem,
    agent_name: AgentName,
    source_workspace_dir: Path,
    task_description: str,
    session_id: str,
    codex_workspace_root: Path,
    codex_runtime_root: Path,
    provider_name: str | None = None,
    log,
) -> list[dict[str, Any]]:
    reviewer_chain = JUDGE_REVIEWER_CHAIN.get(agent_name, ())
    if not reviewer_chain:
        return []

    reviewer_results: list[dict[str, Any]] = []
    source_workspace_dir = source_workspace_dir.expanduser().resolve()

    for reviewer_agent in reviewer_chain:
        reviewer_session_id = f"{session_id}-{reviewer_agent.value}"
        reviewer_workspace_dir = codex_workspace_root / (
            f"{reviewer_agent.value}-{item.id}-{uuid.uuid4().hex[:8]}"
        )
        materialized = _materialize_workspace(
            item=item,
            agent_name=reviewer_agent,
            workspace_dir=reviewer_workspace_dir,
        )
        _copy_workspace_contents(
            source_workspace_dir,
            reviewer_workspace_dir,
            exclude_rel_paths={"prompt.md", "reviews"},
        )
        log.info(
            "codex_reviewer_workspace_materialized",
            reviewer_agent=reviewer_agent.value,
            workspace_dir=str(reviewer_workspace_dir),
            prompt_path=str(materialized.prompt_path),
        )

        launch_return_code = await asyncio.to_thread(
            _launch_cli_exec,
            materialized.workspace_dir,
            materialized.prompt_text,
            task_id=item.id,
            agent_name=reviewer_agent,
            session_id=reviewer_session_id,
            runtime_root=codex_runtime_root,
            yolo=False,
            provider_name=provider_name,
        )

        verification_result = await _verify_workspace_for_agent(
            workspace_dir=materialized.workspace_dir,
            agent_name=reviewer_agent,
            session_id=reviewer_session_id,
            expected_decision=item.expected_decision,
        )

        reviewer_results.append(
            {
                "reviewer_agent": reviewer_agent.value,
                "session_id": reviewer_session_id,
                "workspace_dir": str(materialized.workspace_dir),
                "launch_return_code": launch_return_code,
                "verification_name": verification_result.verification_name,
                "success": verification_result.success,
                "errors": verification_result.errors,
                "details": verification_result.details,
            }
        )
        log.info(
            "codex_reviewer_run_completed",
            reviewer_agent=reviewer_agent.value,
            session_id=reviewer_session_id,
            launch_return_code=launch_return_code,
            verification=verification_result.verification_name,
            success=verification_result.success,
        )

    return reviewer_results


_codex_reviewer_metrics_from_verification = _reviewer_metrics_from_verification
_run_codex_reviewer_chain_for_judge = _run_reviewer_chain_for_judge


async def _completion_contract_error(
    *,
    worker_light_url: str,
    spec: AgentEvalSpec,
    session_id: str,
) -> str | None:
    manifest_path = spec.required_reviewer_handover_manifest
    expected_stage = spec.required_reviewer_stage
    if not manifest_path or not expected_stage:
        return None

    worker = WorkerClient(base_url=worker_light_url, session_id=session_id)
    try:
        if spec.materialize_reviewer_handover:
            materialize_error = await _materialize_reviewer_handover(
                worker,
                reviewer_stage=expected_stage,
            )
            if materialize_error:
                return materialize_error
            errors = await reviewer_handover_custom_check_from_session_id(
                session_id=session_id,
                reviewer_label="Execution",
                manifest_path=manifest_path,
                expected_stage=expected_stage,
            )
            if errors:
                return "; ".join(error.message for error in errors)
            return None

        return await validate_reviewer_handover(
            worker,
            manifest_path=manifest_path,
            expected_stage=expected_stage,
        )
    finally:
        await worker.aclose()
