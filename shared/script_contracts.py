from __future__ import annotations

from pathlib import Path

from shared.enums import AgentName

_BENCHMARK_ROLE_NAMES = {
    AgentName.BENCHMARK_PLANNER,
    AgentName.BENCHMARK_PLAN_REVIEWER,
    AgentName.BENCHMARK_CODER,
    AgentName.BENCHMARK_REVIEWER,
}
_ENGINEERING_ROLE_NAMES = {
    AgentName.ENGINEER_CODER,
    AgentName.ENGINEER_EXECUTION_REVIEWER,
    AgentName.ELECTRONICS_REVIEWER,
    AgentName.ENGINEER_PLANNER,
    AgentName.ENGINEER_PLAN_REVIEWER,
    AgentName.ELECTRONICS_PLANNER,
}

BENCHMARK_SCRIPT_PATH = "benchmark_script.py"
BENCHMARK_PLAN_PATH = "benchmark_plan.md"
BENCHMARK_PLAN_EVIDENCE_SCRIPT_PATH = "benchmark_plan_evidence_script.py"
PAYLOAD_TRAJECTORY_DEFINITION_PATH = "payload_trajectory_definition.yaml"
# Compatibility alias for older imports during the rename rollout.
PRECISE_PATH_DEFINITION_PATH = PAYLOAD_TRAJECTORY_DEFINITION_PATH
SOLUTION_SCRIPT_PATH = "solution_script.py"
ENGINEERING_PLAN_PATH = "engineering_plan.md"
SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH = "solution_plan_evidence_script.py"
LEGACY_SCRIPT_PATH = "script.py"
CURRENT_ROLE_MANIFEST_PATH = Path(".manifests/current_role.json")


def _normalize_agent_name(agent_name: AgentName | str | None) -> AgentName | None:
    if agent_name is None:
        return None
    if isinstance(agent_name, AgentName):
        return agent_name
    try:
        return AgentName(str(agent_name))
    except ValueError:
        return None


def _as_path(script_path: str) -> Path:
    return Path(script_path)


def _normalize_reviewer_stage(
    reviewer_stage: AgentName | str | None,
) -> AgentName | None:
    if reviewer_stage is None:
        return None
    if isinstance(reviewer_stage, AgentName):
        return reviewer_stage
    stage = str(reviewer_stage).strip()
    if stage == "engineer_execution_reviewer":
        return AgentName.ENGINEER_EXECUTION_REVIEWER
    try:
        return AgentName(stage)
    except ValueError:
        return None


def role_family_for_agent(agent_name: AgentName | str | None) -> str | None:
    normalized = _normalize_agent_name(agent_name)
    if normalized in _BENCHMARK_ROLE_NAMES:
        return "benchmark"
    if normalized in _ENGINEERING_ROLE_NAMES:
        return "engineering"
    return None


def authored_script_path_for_agent(agent_name: AgentName | str | None) -> Path:
    normalized = _normalize_agent_name(agent_name)
    if normalized in _BENCHMARK_ROLE_NAMES:
        return _as_path(BENCHMARK_SCRIPT_PATH)
    if normalized in _ENGINEERING_ROLE_NAMES:
        return _as_path(SOLUTION_SCRIPT_PATH)
    return _as_path(LEGACY_SCRIPT_PATH)


def plan_path_for_agent(agent_name: AgentName | str | None) -> Path:
    normalized = _normalize_agent_name(agent_name)
    if normalized in _BENCHMARK_ROLE_NAMES:
        return _as_path(BENCHMARK_PLAN_PATH)
    if normalized in _ENGINEERING_ROLE_NAMES:
        return _as_path(ENGINEERING_PLAN_PATH)
    return _as_path("plan.md")


def plan_artifact_candidates_for_agent(
    agent_name: AgentName | str | None,
) -> tuple[str, ...]:
    """Return accepted plan-file names for the requested role.

    Historical benchmark and engineer bundles may still carry the legacy
    ``plan.md`` filename, while newly materialized workspaces use the role-
    specific plan filename. Validation should accept either spelling for the
    same role, but not cross-role plan files.
    """
    canonical = plan_path_for_agent(agent_name).as_posix()
    if canonical == "plan.md":
        return (canonical,)
    return (canonical, "plan.md")


def authored_script_path_for_reviewer_stage(
    reviewer_stage: AgentName | str | None,
) -> Path:
    stage = _normalize_reviewer_stage(reviewer_stage)
    if stage == AgentName.BENCHMARK_REVIEWER:
        return _as_path(BENCHMARK_SCRIPT_PATH)
    if stage in {
        AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.ELECTRONICS_REVIEWER,
    }:
        return _as_path(SOLUTION_SCRIPT_PATH)
    return _as_path(LEGACY_SCRIPT_PATH)


def plan_path_for_reviewer_stage(reviewer_stage: AgentName | str | None) -> Path:
    stage = _normalize_reviewer_stage(reviewer_stage)
    if stage == AgentName.BENCHMARK_REVIEWER:
        return _as_path(BENCHMARK_PLAN_PATH)
    if stage in {
        AgentName.ENGINEER_EXECUTION_REVIEWER,
        AgentName.ELECTRONICS_REVIEWER,
    }:
        return _as_path(ENGINEERING_PLAN_PATH)
    return _as_path("plan.md")
