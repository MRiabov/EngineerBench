from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.dataset_selection import (  # noqa: E402
    parse_level_filters,
    resolve_agents_for,
)
from evals.logic.seed_maintenance import refresh_seed_artifact_manifests  # noqa: E402
from scripts.internal.eval_seed_selection import (  # noqa: E402
    infer_seed_agent_for_task_id,
    load_seed_dataset,
    seed_dataset_agents,
)
from shared.agent_templates import load_seed_starter_template_files  # noqa: E402
from shared.enums import AgentName  # noqa: E402


def _resolve_seed_artifact_dir(item, *, root: Path) -> Path | None:
    if item.seed_artifact_dir is None:
        return None

    artifact_dir = Path(item.seed_artifact_dir)
    if artifact_dir.is_absolute():
        return artifact_dir

    repo_relative = root / artifact_dir
    if repo_relative.exists():
        return repo_relative

    if item.seed_dataset is not None:
        dataset_relative = (root / item.seed_dataset).parent / artifact_dir
        if dataset_relative.exists():
            return dataset_relative

    return repo_relative


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy canonical starter templates into seeded eval artifact dirs "
            "for the roles that are expected to begin from template baseline."
        )
    )
    parser.add_argument(
        "--agent",
        type=str,
        action="append",
        required=False,
        help=(
            "Agent dataset(s) to update. Supports a single agent, repeated "
            "flags, comma-separated values, list syntax like [a,b], or 'or' "
            "separators. Use 'all' to run every seed-backed agent. Omit when "
            "--task-id is set to infer the matching agent automatically."
        ),
    )
    parser.add_argument(
        "--task-id",
        type=str,
        default=None,
        help="Update only one specific task ID.",
    )
    parser.add_argument(
        "--level",
        action="append",
        default=None,
        help=(
            "Update only evals at the selected complexity levels. Supports a "
            "single level, repeated flags, comma-separated values, or list "
            "syntax like [0,1]."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of rows per agent after task-id filtering.",
    )
    parser.add_argument(
        "--update-manifests",
        dest="update_manifests",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Refresh deterministic seed-manifest hashes after copying the "
            "starter templates (default: enabled)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report the paths that would be updated without writing files.",
    )
    return parser.parse_args()


def _write_starter_files(
    artifact_dir: Path,
    starter_files: dict[str, str],
    *,
    dry_run: bool,
) -> list[str]:
    updated: list[str] = []
    for rel_path, content in sorted(starter_files.items()):
        file_path = artifact_dir / rel_path
        current = file_path.read_text(encoding="utf-8") if file_path.exists() else None
        if current == content:
            continue
        updated.append(rel_path)
        if dry_run:
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return updated


def _update_item(
    agent: AgentName,
    item,
    *,
    update_manifests: bool,
    dry_run: bool,
) -> tuple[bool, bool, list[str]]:
    artifact_dir = _resolve_seed_artifact_dir(item, root=ROOT)
    if artifact_dir is None:
        return True, False, []

    starter_files = load_seed_starter_template_files(agent)
    if not starter_files:
        return True, False, []

    updated_paths = _write_starter_files(
        artifact_dir,
        starter_files,
        dry_run=dry_run,
    )

    if not dry_run and update_manifests and updated_paths:
        refreshed = refresh_seed_artifact_manifests(artifact_dir, fix=True)
        updated_paths.extend(
            str(path.relative_to(artifact_dir)).replace("\\", "/")
            for path in refreshed
            if path.exists()
        )

    return True, bool(updated_paths), updated_paths


def main() -> int:
    args = _parse_args()
    if args.agent:
        agents = resolve_agents_for(
            args.agent,
            available_agents=seed_dataset_agents(root=ROOT),
        )
    elif args.task_id:
        agents = [infer_seed_agent_for_task_id(args.task_id, root=ROOT)]
    else:
        raise SystemExit("Provide --agent or --task-id.")

    levels = parse_level_filters(args.level)
    if args.level and not levels:
        raise SystemExit("No valid --level values were parsed.")

    changed_rows = 0
    changed_files = 0
    for agent in agents:
        dataset = load_seed_dataset(
            agent,
            task_id=args.task_id,
            limit=args.limit,
            levels=levels if levels else None,
        )
        for item in dataset:
            _, changed, updated_paths = _update_item(
                agent,
                item,
                update_manifests=args.update_manifests,
                dry_run=args.dry_run,
            )
            if not changed:
                continue
            changed_rows += 1
            changed_files += len(updated_paths)
            action = "WOULD UPDATE" if args.dry_run else "UPDATED"
            print(f"{action} {agent.value} {item.id}: {', '.join(updated_paths)}")

    summary = (
        f"{'Would update' if args.dry_run else 'Updated'} "
        f"{changed_rows} row(s), {changed_files} path(s)."
    )
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
