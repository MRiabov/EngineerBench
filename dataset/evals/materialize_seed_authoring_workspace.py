"""Materialize a blank workspace for seed authoring.

This helper is for seed creators, not for evaluating an existing row. It
creates a fresh run-local workspace that contains the starter/template files
for the selected agent plus the workspace metadata needed to begin authoring a
new seed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.codex_workspace import (
    MaterializedWorkspace,  # noqa: E402
    sync_repo_venv,  # noqa: E402
)
from evals.logic.codex_workspace import (
    materialize_seed_workspace as materialize_workspace,  # noqa: E402
)
from evals.logic.models import EvalDatasetItem  # noqa: E402
from evals.logic.temp_paths import mkdtemp_in_eval_temp_root  # noqa: E402
from shared.agent_templates import load_seed_starter_template_files  # noqa: E402
from shared.enums import AgentName  # noqa: E402

DEFAULT_TASK_ID = "seed-authoring"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a blank seed-authoring workspace with the same starter "
            "files and workspace metadata the target agent expects."
        )
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="Target agent name, for example engineer_coder.",
    )
    parser.add_argument(
        "--task-id",
        default=DEFAULT_TASK_ID,
        help=(
            "Label for the authoring workspace. Used in the prompt and the "
            "default temp-directory prefix."
        ),
    )
    parser.add_argument(
        "--task",
        default=None,
        help=(
            "Optional authoring note shown in the prompt. Defaults to a "
            "generic seed-authoring instruction."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional destination directory. If omitted, a persistent tempdir "
            "is created under /tmp/problemologist-evals/seed_authoring/."
        ),
    )
    return parser.parse_args()


def _ensure_destination(
    output_dir: str | None, *, agent: AgentName, task_id: str
) -> Path:
    if output_dir:
        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    prefix = f"problemologist-{agent.value}-{task_id}-"
    return mkdtemp_in_eval_temp_root(family_name="seed_authoring", prefix=prefix)


def _build_authoring_item(
    *, agent: AgentName, task_id: str, task: str | None
) -> EvalDatasetItem:
    task_text = (
        task
        if task is not None
        else (
            "Seed authoring workspace bootstrap. "
            f"Create a new seed for {agent.value} from the starter files in "
            "this workspace."
        )
    )
    return EvalDatasetItem(
        id=task_id,
        task=task_text,
        complexity_level=0,
    )


def _write_starter_files(
    workspace_dir: Path, starter_files: dict[str, str]
) -> list[str]:
    copied_paths: list[str] = []
    for rel_path, content in sorted(starter_files.items()):
        file_path = workspace_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        copied_paths.append(rel_path)
    return copied_paths


def materialize_seed_authoring_workspace(
    *,
    agent: AgentName,
    task_id: str,
    task: str | None = None,
    output_dir: str | None = None,
) -> MaterializedWorkspace:
    starter_files = load_seed_starter_template_files(agent)
    if not starter_files:
        raise SystemExit(f"Agent '{agent.value}' does not have a seed starter set.")

    workspace_dir = _ensure_destination(output_dir, agent=agent, task_id=task_id)
    item = _build_authoring_item(agent=agent, task_id=task_id, task=task)
    materialized = materialize_workspace(
        item=item,
        agent_name=agent,
        workspace_dir=workspace_dir,
    )
    sync_repo_venv(materialized.workspace_dir)
    starter_paths = _write_starter_files(materialized.workspace_dir, starter_files)
    for rel_path in starter_paths:
        if rel_path not in materialized.copied_paths:
            materialized.copied_paths.append(rel_path)

    return materialized


def _print_materialization_summary(materialized: MaterializedWorkspace) -> None:
    print(f"workspace: {materialized.workspace_dir}")
    print(f"prompt: {materialized.prompt_path}")
    print(f"agent: {materialized.agent_name.value}")
    print(f"task_id: {materialized.task_id}")
    print(f"venv: {materialized.workspace_dir / '.venv'}")
    print("files:")
    for rel_path in materialized.copied_paths:
        print(f"  - {rel_path}")


def main() -> int:
    args = _parse_args()
    try:
        agent = AgentName(args.agent)
    except ValueError as exc:
        available = ", ".join(sorted(agent.value for agent in list(AgentName)))
        raise SystemExit(
            f"Unknown agent '{args.agent}'. Available: {available}"
        ) from exc

    materialized = materialize_seed_authoring_workspace(
        agent=agent,
        task_id=args.task_id,
        task=args.task,
        output_dir=args.output_dir,
    )
    _print_materialization_summary(materialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
