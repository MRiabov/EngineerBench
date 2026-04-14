from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.models import EvalDatasetItem  # noqa: E402
from evals.logic.specs import AGENT_SPECS  # noqa: E402
from shared.enums import AgentName  # noqa: E402


def _seed_dataset_roots(root: Path) -> tuple[Path, Path]:
    return (
        root / "dataset" / "evals" / "datasets",
        root / "dataset" / "data" / "seed" / "role_based",
    )


def _seed_dataset_path_for_agent(
    agent: AgentName, dataset_roots: tuple[Path, Path]
) -> Path | None:
    return next(
        (
            dataset_root / f"{agent.value}.json"
            for dataset_root in dataset_roots
            if (dataset_root / f"{agent.value}.json").exists()
        ),
        None,
    )


def seed_dataset_agents(*, root: Path = ROOT) -> list[AgentName]:
    dataset_roots = _seed_dataset_roots(root)
    return [
        agent
        for agent in AGENT_SPECS
        if _seed_dataset_path_for_agent(agent, dataset_roots) is not None
    ]


def infer_seed_agent_for_task_id(task_id: str, *, root: Path = ROOT) -> AgentName:
    matches: dict[AgentName, Path] = {}
    dataset_roots = _seed_dataset_roots(root)
    for dataset_root in dataset_roots:
        if not dataset_root.exists():
            continue
        for json_path in sorted(dataset_root.glob("*.json")):
            try:
                agent = AgentName(json_path.stem)
            except ValueError:
                continue
            with json_path.open(encoding="utf-8") as handle:
                rows = json.load(handle)
            if any(row.get("id") == task_id for row in rows):
                matches.setdefault(agent, json_path)

    if not matches:
        searched = ", ".join(str(path) for path in dataset_roots)
        raise SystemExit(
            f"Task id '{task_id}' was not found in any seed dataset. Searched: {searched}"
        )

    if len(matches) > 1:
        match_list = ", ".join(
            f"{agent.value}={path.relative_to(root)}"
            for agent, path in sorted(matches.items(), key=lambda item: item[0].value)
        )
        raise SystemExit(
            f"Task id '{task_id}' is ambiguous across seed datasets: {match_list}"
        )

    return next(iter(matches))


def load_seed_dataset(
    agent: AgentName,
    *,
    task_id: str | None,
    limit: int,
    levels: set[int] | None,
    root: Path = ROOT,
) -> list[EvalDatasetItem]:
    dataset_roots = _seed_dataset_roots(root)
    json_path = _seed_dataset_path_for_agent(agent, dataset_roots)
    if json_path is None:
        searched = ", ".join(str(path) for path in dataset_roots)
        raise FileNotFoundError(
            f"Dataset for agent '{agent.value}' not found. Searched: {searched}"
        )

    with json_path.open() as handle:
        data = json.load(handle)

    if task_id:
        data = [item for item in data if item["id"] == task_id]
    if levels:
        data = [item for item in data if item.get("complexity_level") in levels]
    if limit > 0:
        data = data[:limit]

    seed_dataset = json_path.relative_to(root)
    return [
        EvalDatasetItem.model_validate({**item_raw, "seed_dataset": seed_dataset})
        for item_raw in data
    ]
