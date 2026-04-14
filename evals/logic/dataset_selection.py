from __future__ import annotations

from collections.abc import Iterable

from evals.logic.cli_args import parse_cli_int_set, parse_cli_list_values
from evals.logic.models import EvalDatasetItem
from evals.logic.specs import AGENT_SPECS
from shared.enums import AgentName


def resolve_agents(agent_args: Iterable[str]) -> list[AgentName]:
    return resolve_agents_for(
        agent_args,
        available_agents=AGENT_SPECS.keys(),
    )


def resolve_agents_for(
    agent_args: Iterable[str],
    *,
    available_agents: Iterable[AgentName],
) -> list[AgentName]:
    parsed = parse_cli_list_values(agent_args)
    if not parsed:
        raise SystemExit("No valid --agent values were parsed.")

    available_agents = tuple(available_agents)
    allowed_agents = set(available_agents)
    available = ", ".join(sorted(agent.value for agent in available_agents))

    if any(agent_arg.lower() == "all" for agent_arg in parsed):
        return list(available_agents)

    agents: list[AgentName] = []
    seen: set[AgentName] = set()
    for agent_arg in parsed:
        try:
            agent = AgentName(agent_arg)
        except ValueError as exc:
            raise SystemExit(
                f"Unknown agent '{agent_arg}'. Available: {available}"
            ) from exc

        if agent not in allowed_agents:
            raise SystemExit(
                f"Agent '{agent.value}' is not available for this command. "
                f"Available: {available}"
            )
        if agent in seen:
            continue
        seen.add(agent)
        agents.append(agent)

    return agents


def parse_task_id_filters(raw_task_id_filters: Iterable[str] | None) -> set[str]:
    if not raw_task_id_filters:
        return set()
    return set(parse_cli_list_values(raw_task_id_filters))


def parse_level_filters(raw_level_filters: Iterable[str] | None) -> set[int]:
    if not raw_level_filters:
        return set()
    return parse_cli_int_set(
        raw_level_filters,
        minimum=0,
        maximum=5,
        label="complexity level",
    )


def filter_eval_rows(
    rows: list[EvalDatasetItem],
    *,
    task_ids: set[str] | None = None,
    levels: set[int] | None = None,
    limit: int = 0,
) -> list[EvalDatasetItem]:
    selected: list[EvalDatasetItem] = []
    for row in rows:
        if task_ids and row.id not in task_ids:
            continue
        if levels and row.complexity_level not in levels:
            continue
        selected.append(row)
        if limit > 0 and len(selected) >= limit:
            break
    return selected
