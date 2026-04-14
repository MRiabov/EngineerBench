from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import yaml

from controller.agent.dspy_utils import evaluate_formula, map_events_to_prediction
from controller.agent.reward import (
    AgentRewardConfig,
    MilestoneConfig,
    load_reward_config,
)
from evals.logic.codex_workspace import LocalWorkspaceClient as _LocalWorkspaceClient
from evals.logic.models import HardCheckAggregate
from evals.logic.review_checks import (
    planner_artifacts_present as _planner_artifacts_present,
)
from evals.logic.review_checks import (
    review_artifacts_complete_for_prefix as _review_artifacts_complete_for_prefix,
)
from evals.logic.runner_reporting import (
    RunnerLogContext,
    _build_seed_failure_pointer,
    _sanitize_readable_text,
)
from evals.logic.specs import AGENT_SPECS, required_plan_artifacts_for_agent
from shared.enums import AgentName
from shared.models.schemas import EpisodeMetadata
from shared.models.simulation import SimulationResult
from shared.workers.schema import ValidationResultRecord

METRIC_HANDLERS = {}


def _load_agent_reward_configs() -> dict[AgentName, AgentRewardConfig]:
    try:
        reward_cfg = load_reward_config()
    except Exception:
        from shared.logging import get_logger

        get_logger(__name__).exception("reward_config_load_failed")
        return {}

    configs: dict[AgentName, AgentRewardConfig] = {}
    for group in (reward_cfg.benchmark, reward_cfg.engineer, reward_cfg.shared):
        for name, cfg in group.items():
            with contextlib.suppress(ValueError):
                configs[AgentName(name)] = cfg
    return configs


def _extract_episode_events(episode: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(episode, dict):
        return []

    traces = episode.get("traces")
    if not isinstance(traces, list):
        return []

    events: list[dict[str, Any]] = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        if str(trace.get("trace_type") or "").upper() != "EVENT":
            continue
        metadata = trace.get("metadata_vars")
        if isinstance(metadata, dict):
            event = dict(metadata)
            content = trace.get("content")
            if isinstance(content, str):
                with contextlib.suppress(Exception):
                    parsed = yaml.safe_load(content)
                    if isinstance(parsed, dict):
                        for key, value in parsed.items():
                            event.setdefault(key, value)
            if "event_type" not in event and trace.get("name"):
                event["event_type"] = trace["name"]
            events.append(event)
            continue
        content = trace.get("content")
        if isinstance(content, str):
            with contextlib.suppress(Exception):
                parsed = yaml.safe_load(content)
                if isinstance(parsed, dict):
                    if "event_type" not in parsed and trace.get("name"):
                        parsed = dict(parsed)
                        parsed["event_type"] = trace["name"]
                    events.append(parsed)
    return events


def _extract_episode_cost_usd(episode: dict[str, Any] | None) -> float | None:
    if not isinstance(episode, dict):
        return None

    metadata_raw = episode.get("metadata_vars")
    if not isinstance(metadata_raw, dict):
        return None

    with contextlib.suppress(Exception):
        metadata = EpisodeMetadata.model_validate(metadata_raw)
        additional = dict(metadata.additional_info or {})
        credit_usage = additional.get("credit_usage")
        if isinstance(credit_usage, dict):
            raw_cost = credit_usage.get("total_cost_usd")
            if isinstance(raw_cost, int | float):
                return float(raw_cost)

    return None


def _extract_episode_failure_reason(episode: dict[str, Any] | None) -> str:
    if not isinstance(episode, dict):
        return ""

    metadata_raw = episode.get("metadata_vars")
    if isinstance(metadata_raw, dict):
        with contextlib.suppress(Exception):
            metadata = EpisodeMetadata.model_validate(metadata_raw)
            for candidate in (
                metadata.error,
                metadata.detailed_status,
                metadata.terminal_reason,
                metadata.failure_class,
            ):
                if candidate is None:
                    continue
                value = getattr(candidate, "value", candidate)
                text = _sanitize_readable_text(value)
                if text:
                    return text

    for key in ("error", "failure_reason", "reason", "detail", "message"):
        value = episode.get(key)
        if value is None:
            continue
        text = _sanitize_readable_text(value)
        if text:
            return text

    return ""


def _resolve_check_value(
    check_name: str,
    metrics: dict[str, Any],
    *,
    success: bool,
) -> Any:
    aliases: dict[str, tuple[str, ...]] = {
        "script_compiles": ("script_compiled", "compiled"),
        "simulation_result": ("simulation_success", "simulation_ran"),
        "cad_geometry_valid": ("geometry_valid", "cad_geometry_valid"),
        "reviewer_accepted": ("accepted", "reviewer_accepted"),
        "engineer_implemented_successfully": (
            "engineer_implemented_successfully",
            "simulation_success",
        ),
    }
    for key in (check_name, *aliases.get(check_name, ())):
        if key in metrics:
            return metrics[key]
    if check_name == "task_success":
        return success
    return None


def _normalize_checklist_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "pass":
            return 1.0
        if normalized == "fail":
            return 0.0
        if normalized in {"not_applicable", "n/a", "na"}:
            return 1.0
    return None


def _resolve_metric_value_for_check(
    check_name: str,
    metrics: dict[str, Any],
    *,
    success: bool,
) -> Any:
    if check_name.startswith("checklist."):
        checklist_key = check_name.split(".", 1)[1]
        checklist = metrics.get("checklist")
        if isinstance(checklist, dict):
            return _normalize_checklist_value(checklist.get(checklist_key))
        return None
    return _resolve_check_value(check_name, metrics, success=success)


def _check_needs_constraints(check_cfg: MilestoneConfig) -> bool:
    formulas = [check_cfg.penalty_formula, check_cfg.formula]
    return any(
        isinstance(formula, str)
        and ("max_unit_cost" in formula or "max_weight" in formula)
        for formula in formulas
    )


def _score_milestone_check(
    *,
    check_name: str,
    check_cfg: MilestoneConfig,
    metrics: dict[str, Any],
    success: bool,
) -> tuple[float, bool]:
    raw_value = _resolve_metric_value_for_check(check_name, metrics, success=success)
    if check_cfg.partial:
        formula = check_cfg.penalty_formula or check_cfg.formula
        if formula:
            score = evaluate_formula(formula, metrics)
        elif isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            score = float(raw_value)
        else:
            score = 1.0 if bool(raw_value) else 0.0
    else:
        if isinstance(raw_value, int | float) and not isinstance(raw_value, bool):
            score = float(raw_value)
        else:
            score = 1.0 if bool(raw_value) else 0.0

    score = max(0.0, min(1.0, float(score)))
    return score, score >= 0.999


def _extract_events_from_episodes(
    episodes: list[dict[str, Any] | None],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for episode in episodes:
        merged.extend(_extract_episode_events(episode))
    return merged


async def _load_constraint_context(
    session_id: str, *, worker_light_url: str
) -> dict[str, float]:
    if not session_id:
        return {}

    worker = WorkerClient(base_url=worker_light_url, session_id=session_id)
    try:
        content = await worker.read_file("benchmark_definition.yaml")
    finally:
        await worker.aclose()

    if not isinstance(content, str) or content.startswith("Error:"):
        return {}

    with contextlib.suppress(Exception):
        parsed = yaml.safe_load(content)
        if not isinstance(parsed, dict):
            return {}
        constraints = parsed.get("constraints")
        if not isinstance(constraints, dict):
            return {}
        context: dict[str, float] = {}
        max_unit_cost = constraints.get("max_unit_cost")
        max_weight_g = constraints.get("max_weight_g", constraints.get("max_weight"))
        if isinstance(max_unit_cost, int | float):
            context["max_unit_cost"] = float(max_unit_cost)
        if isinstance(max_weight_g, int | float):
            context["max_weight_g"] = float(max_weight_g)
            context["max_weight"] = float(max_weight_g)
        return context

    return {}


def _load_constraint_context_from_workspace(workspace_dir: Path) -> dict[str, float]:
    benchmark_definition_path = workspace_dir / "benchmark_definition.yaml"
    if not benchmark_definition_path.exists():
        return {}

    with contextlib.suppress(Exception):
        parsed = yaml.safe_load(benchmark_definition_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            return {}
        constraints = parsed.get("constraints")
        if not isinstance(constraints, dict):
            return {}
        context: dict[str, float] = {}
        max_unit_cost = constraints.get("max_unit_cost")
        max_weight_g = constraints.get("max_weight_g", constraints.get("max_weight"))
        if isinstance(max_unit_cost, int | float):
            context["max_unit_cost"] = float(max_unit_cost)
        if isinstance(max_weight_g, int | float):
            context["max_weight_g"] = float(max_weight_g)
            context["max_weight"] = float(max_weight_g)
        return context

    return {}


def _load_validation_result_record(
    workspace_dir: Path,
) -> ValidationResultRecord | None:
    validation_path = workspace_dir / "validation_results.json"
    if not validation_path.exists():
        return None
    with contextlib.suppress(Exception):
        return ValidationResultRecord.model_validate_json(
            validation_path.read_text(encoding="utf-8")
        )
    return None


def _load_simulation_result(workspace_dir: Path) -> SimulationResult | None:
    simulation_path = workspace_dir / "simulation_result.json"
    if not simulation_path.exists():
        return None
    with contextlib.suppress(Exception):
        return SimulationResult.model_validate_json(
            simulation_path.read_text(encoding="utf-8")
        )
    return None


def _workspace_metrics(
    *,
    workspace_dir: Path,
    success: bool,
    verification_result: Any | None = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "task_success": success,
    }
    metrics.update(_load_constraint_context_from_workspace(workspace_dir))

    validation_record = _load_validation_result_record(workspace_dir)
    if validation_record is not None:
        validation_success = bool(validation_record.success)
        metrics.update(
            {
                "script_compiled": validation_success,
                "cad_geometry_valid": validation_success,
                "manufacturability_valid": validation_success,
                "parts_within_build_zone": validation_success,
            }
        )
        if validation_record.verification_result is not None:
            individual_results = list(
                validation_record.verification_result.individual_results or []
            )
            if individual_results:
                min_distance = None
                initial_distance = None
                for result in individual_results:
                    candidate_min = getattr(result, "min_distance_to_goal", None)
                    if isinstance(candidate_min, int | float):
                        candidate_min_f = float(candidate_min)
                        min_distance = (
                            candidate_min_f
                            if min_distance is None
                            else min(min_distance, candidate_min_f)
                        )
                    candidate_initial = getattr(result, "initial_distance", None)
                    if isinstance(candidate_initial, int | float):
                        candidate_initial_f = float(candidate_initial)
                        initial_distance = (
                            candidate_initial_f
                            if initial_distance is None
                            else max(initial_distance, candidate_initial_f)
                        )
                if min_distance is not None:
                    metrics["min_distance_to_goal"] = min_distance
                if initial_distance is not None:
                    metrics["initial_distance"] = max(initial_distance, 1e-9)

    simulation_result = _load_simulation_result(workspace_dir)
    if simulation_result is not None:
        metrics.update(
            {
                "simulation_ran": True,
                "simulation_success": bool(simulation_result.success),
                "engineer_implemented_successfully": bool(simulation_result.success),
                "actual_cost": float(simulation_result.total_cost),
                "actual_weight": float(simulation_result.total_weight_g),
                "estimated_cost": float(simulation_result.total_cost),
                "estimated_weight": float(simulation_result.total_weight_g),
            }
        )

    if verification_result is not None:
        details = getattr(verification_result, "details", None)
        if isinstance(details, dict):
            if details.get("validation_success") is not None:
                metrics["validation_success"] = details.get("validation_success")
            if details.get("simulation_success") is not None:
                metrics["simulation_success"] = details.get("simulation_success")
            if details.get("review_decision") is not None:
                metrics["review_decision"] = details.get("review_decision")
            if details.get("review_comments") is not None:
                metrics["review_comments"] = details.get("review_comments")

    return metrics


_codex_workspace_metrics = _workspace_metrics


async def _collect_metrics_for_checks(
    *,
    check_configs: dict[str, MilestoneConfig],
    success: bool,
    session_id: str,
    worker_light_url: str,
    workspace_dir: Path | None = None,
    episode_data: dict[str, Any] | None,
    extra_episodes: list[dict[str, Any] | None] | None = None,
    agent_name: AgentName | None = None,
    metrics_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    episodes = [episode_data]
    if extra_episodes:
        episodes.extend(extra_episodes)

    events = _extract_events_from_episodes(episodes)
    metrics_model = map_events_to_prediction(events, agent_name=agent_name)
    metrics = metrics_model.model_dump(mode="json")
    metrics["task_success"] = success
    if metrics_override:
        metrics.update(metrics_override)

    check_names = set(check_configs.keys())
    needs_worker_checks = check_names.intersection(
        {"review_artifacts_complete", "plan_artifacts_present"}
    )
    if needs_worker_checks and agent_name:
        review_prefix = AGENT_SPECS.get(agent_name).review_filename_prefix
        required_files = required_plan_artifacts_for_agent(agent_name)

        if workspace_dir is not None and workspace_dir.exists():
            worker = _LocalWorkspaceClient(
                root=workspace_dir,
                session_id=session_id or f"workspace-{agent_name.value}",
            )
        elif session_id:
            worker = WorkerClient(base_url=worker_light_url, session_id=session_id)
        else:
            worker = None

        if worker is not None:
            try:
                if "review_artifacts_complete" in needs_worker_checks and review_prefix:
                    metrics[
                        "review_artifacts_complete"
                    ] = await _review_artifacts_complete_for_prefix(
                        worker=worker,
                        review_filename_prefix=review_prefix,
                    )

                if "plan_artifacts_present" in needs_worker_checks and required_files:
                    metrics[
                        "plan_artifacts_present"
                    ] = await _planner_artifacts_present(
                        worker=worker,
                        required_files=required_files,
                    )
            finally:
                await worker.aclose()

    if any(_check_needs_constraints(check) for check in check_configs.values()):
        if workspace_dir is not None and workspace_dir.exists():
            metrics.update(_load_constraint_context_from_workspace(workspace_dir))
        else:
            metrics.update(
                await _load_constraint_context(
                    session_id, worker_light_url=worker_light_url
                )
            )

    return metrics


async def _record_hard_check_outcomes(
    *,
    stats: dict[AgentName, Any],
    reward_agent_configs: dict[AgentName, AgentRewardConfig],
    agent_name: AgentName,
    item,
    success: bool,
    episode_data: dict[str, Any] | None,
    session_id: str,
    worker_light_url: str,
    log_context: RunnerLogContext,
    workspace_dir: Path | None = None,
    failure_context: dict[str, Any] | None = None,
    metrics_override: dict[str, Any] | None = None,
) -> bool | None:
    cfg = reward_agent_configs.get(agent_name)
    if cfg is None or not cfg.hard_checks:
        return None

    metrics = await _collect_metrics_for_checks(
        check_configs=cfg.hard_checks,
        success=success,
        session_id=session_id,
        worker_light_url=worker_light_url,
        workspace_dir=workspace_dir,
        episode_data=episode_data,
        agent_name=agent_name,
        metrics_override=metrics_override,
    )

    hard_check_stats = stats[agent_name].setdefault("hard_checks", {})
    seed_id = item.id
    failure_pointer: dict[str, Any] | None = None
    all_passed = True
    for check_name, check_cfg in cfg.hard_checks.items():
        bucket = hard_check_stats.setdefault(
            check_name,
            HardCheckAggregate().model_dump(mode="json"),
        )
        bucket["total"] += 1

        _, passed = _score_milestone_check(
            check_name=check_name,
            check_cfg=check_cfg,
            metrics=metrics,
            success=success,
        )
        if passed:
            bucket["passed"] += 1
        else:
            all_passed = False
            if failure_pointer is None:
                failure_pointer = _build_seed_failure_pointer(
                    task_id=item.id,
                    session_id=session_id,
                    episode_data=episode_data,
                    failure_context=failure_context,
                    log_context=log_context,
                )
            if seed_id not in bucket["failed_seeds"]:
                bucket["failed_seeds"].append(seed_id)
            failure_pointers = bucket.setdefault("failure_pointers", {})
            if seed_id not in failure_pointers:
                failure_pointers[seed_id] = failure_pointer

    return all_passed


async def _record_judge_outcomes(
    *,
    stats: dict[AgentName, Any],
    reward_agent_configs: dict[AgentName, AgentRewardConfig],
    agent_name: AgentName,
    item,
    success: bool,
    session_id: str,
    worker_light_url: str,
    log_context: RunnerLogContext,
    workspace_dir: Path | None = None,
    episode_data: dict[str, Any] | None,
    extra_episodes: list[dict[str, Any] | None] | None = None,
    metrics_override: dict[str, Any] | None = None,
) -> None:
    cfg = reward_agent_configs.get(agent_name)
    if cfg is None:
        return

    judge_checks = cfg.judge_evaluation.all_milestones()
    if not judge_checks:
        return

    metrics = await _collect_metrics_for_checks(
        check_configs=judge_checks,
        success=success,
        session_id=session_id,
        worker_light_url=worker_light_url,
        workspace_dir=workspace_dir,
        episode_data=episode_data,
        extra_episodes=extra_episodes,
        agent_name=agent_name,
        metrics_override=metrics_override,
    )

    judge_stats = stats[agent_name].setdefault("judge_checks", {})
    seed_id = item.id
    for check_name, check_cfg in judge_checks.items():
        bucket = judge_stats.setdefault(
            check_name,
            HardCheckAggregate().model_dump(mode="json"),
        )
        bucket["total"] += 1
        _, passed = _score_milestone_check(
            check_name=check_name,
            check_cfg=check_cfg,
            metrics=metrics,
            success=success,
        )
        if passed:
            bucket["passed"] += 1
        elif seed_id not in bucket["failed_seeds"]:
            bucket["failed_seeds"].append(seed_id)
