from __future__ import annotations

from collections.abc import Iterable

from shared.enums import AgentName
from shared.script_contracts import (
    CURRENT_ROLE_MANIFEST_PATH,
)

_BENCHMARK_PLAN_BASE_FILES: tuple[str, ...] = (
    "benchmark_plan.md",
    "todo.md",
    "benchmark_definition.yaml",
    "benchmark_assembly_definition.yaml",
)

_ENGINEER_PLAN_BASE_FILES: tuple[str, ...] = (
    "engineering_plan.md",
    "todo.md",
    "benchmark_definition.yaml",
    "assembly_definition.yaml",
)

_BENCHMARK_PLAN_ROLES = {
    AgentName.BENCHMARK_PLANNER,
    AgentName.BENCHMARK_PLAN_REVIEWER,
    AgentName.BENCHMARK_CODER,
    AgentName.BENCHMARK_REVIEWER,
}

_ENGINEER_PLAN_ROLES = {
    AgentName.ENGINEER_PLANNER,
    AgentName.ENGINEER_PLAN_REVIEWER,
    AgentName.ENGINEER_CODER,
    AgentName.ENGINEER_EXECUTION_REVIEWER,
}


def _dedupe_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(paths))


def plan_artifacts_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    if agent_name in _BENCHMARK_PLAN_ROLES:
        return _BENCHMARK_PLAN_BASE_FILES

    if agent_name in _ENGINEER_PLAN_ROLES:
        return _ENGINEER_PLAN_BASE_FILES

    return ()


def workspace_artifacts_for_agent(agent_name: AgentName) -> tuple[str, ...]:
    """Return the base workspace contract including backend-owned metadata."""
    return (
        CURRENT_ROLE_MANIFEST_PATH.as_posix(),
        *plan_artifacts_for_agent(agent_name),
    )


__all__ = ["plan_artifacts_for_agent", "workspace_artifacts_for_agent"]
