"""Materialize a seeded eval row into a local temp workspace.

This is an inspection helper, not the eval runner. It copies the seeded
artifacts for a single dataset row into a persistent temp directory under
`/tmp/problemologist-evals/<agent>/` and writes the provider prompt to
`prompt.md` so you can inspect the exact workspace contents an agent would
start from.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.cli_provider import available_cli_providers  # noqa: E402
from evals.logic.codex_workspace import (  # noqa: E402
    LocalWorkspaceClient,
)
from evals.logic.specs import AGENT_SPECS  # noqa: E402
from evals.logic.stack_profiles import apply_stack_profile_env  # noqa: E402
from evals.logic.temp_paths import mkdtemp_in_eval_temp_root  # noqa: E402
from evals.logic.workspace import (  # noqa: E402
    preflight_seeded_entry_contract,
)
from scripts.internal.eval_run_lock import (  # noqa: E402
    EvalRunSelection,
    acquire_eval_run_lock,
    downgrade_eval_run_lock_to_shared,
    release_eval_run_lock,
)

apply_stack_profile_env("eval", env=os.environ, root=ROOT)

from evals.logic.codex_workspace import (  # noqa: E402
    launch_cli_exec,
    open_cli_ui,
)
from evals.logic.codex_workspace import (
    materialize_seed_workspace as materialize_workspace,
)
from evals.logic.models import EvalDatasetItem  # noqa: E402
from evals.logic.startup_checks import fail_closed_if_integration_test_setup
from shared.enums import AgentName  # noqa: E402
from shared.logging import get_logger  # noqa: E402

logger = get_logger(__name__)


def _dataset_roots() -> tuple[Path, ...]:
    configured_roots = os.getenv("PROBLEMOLOGIST_SEED_DATASET_ROOTS", "").strip()
    if configured_roots:
        roots: list[Path] = []
        seen: set[Path] = set()
        for raw_root in configured_roots.split(os.pathsep):
            raw_root = raw_root.strip()
            if not raw_root:
                continue
            dataset_root = Path(raw_root).expanduser()
            if not dataset_root.is_absolute():
                dataset_root = ROOT / dataset_root
            if dataset_root in seen:
                continue
            seen.add(dataset_root)
            roots.append(dataset_root)
        return tuple(roots)

    return (
        ROOT / "dataset" / "evals" / "datasets",
        ROOT / "dataset" / "data" / "seed" / "role_based",
    )


async def _validate_materialized_workspace(
    *,
    agent: AgentName,
    item: EvalDatasetItem,
    workspace_dir: Path,
) -> None:
    session_id = f"seed-materializer-{agent.value}-{item.id}"
    workspace_client = LocalWorkspaceClient(
        root=workspace_dir,
        session_id=session_id,
    )
    await preflight_seeded_entry_contract(
        item=item,
        session_id=session_id,
        agent_name=agent,
        spec=AGENT_SPECS[agent],
        root=ROOT,
        worker_light_url=os.getenv("WORKER_LIGHT_URL", "http://localhost:18001"),
        logger=logger,
        workspace_client=workspace_client,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a local temp workspace from a seeded eval row and write "
            "prompt.md for inspection or CLI-provider launching."
        )
    )
    parser.add_argument(
        "--agent",
        required=True,
        help="Agent dataset to materialize, for example engineer_coder.",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="Specific dataset row ID to materialize. Required when the agent has multiple rows.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Optional destination directory. If omitted, a persistent tempdir "
            "is created under /tmp/problemologist-evals/<agent>/."
        ),
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("PROBLEMOLOGIST_CLI_PROVIDER", "qwen"),
        choices=available_cli_providers(),
        help=(
            "CLI provider to use when launching the workspace after materialization "
            "(default: qwen)."
        ),
    )
    parser.add_argument(
        "--launch-cli-exec",
        "--launch-codex",
        dest="launch_cli_exec",
        action="store_true",
        help=(
            "After materializing the workspace, launch the configured CLI "
            "provider in that directory using prompt.md as the prompt."
        ),
    )
    parser.add_argument(
        "--open-cli-ui",
        "--open-codex",
        "--open",
        dest="open_cli_ui",
        action="store_true",
        help=(
            "After materializing the workspace, open the interactive CLI "
            "provider UI in that directory using prompt.md as the initial prompt."
        ),
    )
    parser.add_argument(
        "--new-terminal",
        action="store_true",
        help=(
            "When used with --open-cli-ui, open the UI in a separate terminal "
            "window instead of the current shell."
        ),
    )
    parser.add_argument(
        "--env-up",
        action="store_true",
        help=(
            "Run scripts/env_up.sh before launching the configured CLI "
            "provider so the controller and worker services are available on the "
            "local ports."
        ),
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Wait for the eval lock instead of failing fast when another eval run is active.",
    )
    parser.add_argument(
        "--force-no-validate-seed",
        action="store_true",
        help=(
            "Disable the seeded-entry validation step before the workspace "
            "launches. Urgent demo use only; do not use this in normal runs."
        ),
    )
    yolo_group = parser.add_mutually_exclusive_group(required=True)
    yolo_group.add_argument(
        "--yolo",
        dest="yolo",
        action="store_true",
        help="Launch the configured CLI provider without approvals or sandboxing.",
    )
    yolo_group.add_argument(
        "--no-yolo",
        dest="yolo",
        action="store_false",
        help="Launch the configured CLI provider with the normal sandboxed behavior.",
    )
    return parser.parse_args()


def _load_dataset(agent: AgentName) -> tuple[Path, list[dict[str, object]]]:
    dataset_roots = _dataset_roots()
    json_path = next(
        (
            root / f"{agent.value}.json"
            for root in dataset_roots
            if (root / f"{agent.value}.json").exists()
        ),
        None,
    )
    if json_path is None:
        searched = ", ".join(str(path) for path in dataset_roots)
        raise FileNotFoundError(
            f"Dataset for agent '{agent.value}' not found. Searched: {searched}"
        )

    with json_path.open(encoding="utf-8") as handle:
        raw_rows = json.load(handle)

    rows = raw_rows
    return json_path, rows


def _select_row(
    rows: list[dict[str, object]], *, task_id: str | None, agent: AgentName
) -> dict[str, object]:
    if task_id:
        for row in rows:
            if row.get("id") == task_id:
                return row
        available = ", ".join(str(row.get("id")) for row in rows)
        raise SystemExit(
            f"Task id '{task_id}' was not found for agent '{agent.value}'. "
            f"Available rows: {available}"
        )

    if len(rows) == 1:
        return rows[0]

    available = ", ".join(str(row.get("id")) for row in rows)
    raise SystemExit(
        f"Agent '{agent.value}' has multiple rows. Pass --task-id. Available rows: {available}"
    )


def _ensure_destination(
    output_dir: str | None, *, agent: AgentName, task_id: str
) -> Path:
    if output_dir:
        destination = Path(output_dir).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    prefix = f"problemologist-{agent.value}-{task_id}-"
    return mkdtemp_in_eval_temp_root(family_name=agent.value, prefix=prefix)


def _env_up() -> None:
    env_up_path = ROOT / "scripts" / "env_up.sh"
    if not env_up_path.exists():
        raise FileNotFoundError(f"Missing env bootstrap script: {env_up_path}")

    print(f"bootstrapping eval environment with: {env_up_path}")
    completed = subprocess.run(
        [str(env_up_path), "--profile", "eval"],
        check=False,
        env={**os.environ, "PROBLEMOLOGIST_EVAL_LOCK_HELD": "1"},
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    args = _parse_args()
    try:
        agent = AgentName(args.agent)
    except ValueError as exc:
        available = ", ".join(sorted(agent.value for agent in list(AgentName)))
        raise SystemExit(
            f"Unknown agent '{args.agent}'. Available: {available}"
        ) from exc

    fail_closed_if_integration_test_setup(
        os.getenv("CONTROLLER_URL", "http://localhost:18000"),
        context="seed workspace materializer startup",
    )

    json_path, rows = _load_dataset(agent)
    row_raw = _select_row(rows, task_id=args.task_id, agent=agent)
    seed_dataset = json_path.relative_to(ROOT)
    row = EvalDatasetItem.model_validate({**row_raw, "seed_dataset": seed_dataset})

    workspace_dir = _ensure_destination(args.output_dir, agent=agent, task_id=row.id)
    materialized = materialize_workspace(
        item=row,
        agent_name=agent,
        workspace_dir=workspace_dir,
        provider_name=args.provider,
    )

    if args.force_no_validate_seed:
        warning = (
            "--force-no-validate-seed disables the seeded-entry validation "
            "step before the workspace starts. Urgent demo use only; do not "
            "use this in normal runs."
        )
        print(warning, file=sys.stderr)
        logger.warning(warning)
    else:
        try:
            asyncio.run(
                _validate_materialized_workspace(
                    agent=agent,
                    item=row,
                    workspace_dir=materialized.workspace_dir,
                )
            )
        except Exception as exc:
            raise SystemExit(
                f"Seeded entry contract invalid for {agent.value} {row.id}: {exc}"
            ) from exc

    print(f"workspace: {materialized.workspace_dir}")
    print(f"prompt: {materialized.prompt_path}")
    print(f"agent: {agent.value}")
    print(f"task_id: {row.id}")
    print("files:")
    for rel_path in materialized.copied_paths:
        print(f"  - {rel_path}")

    if args.launch_cli_exec and args.open_cli_ui:
        raise SystemExit("Choose only one of --launch-cli-exec or --open-cli-ui.")
    if args.new_terminal and not args.open_cli_ui:
        raise SystemExit("--new-terminal requires --open-cli-ui.")

    if args.launch_cli_exec or args.open_cli_ui:
        os.environ["PROBLEMOLOGIST_CLI_ALLOW_HOST_LOOPBACK"] = "1"

    lock_lease = None
    if args.env_up:
        lock_lease = acquire_eval_run_lock(
            queue=args.queue,
            requested_command=[sys.argv[0], *sys.argv[1:]],
            requested_selection=EvalRunSelection(
                agent=agent.value,
                task_ids=[row.id],
                levels=[],
            ),
        )
        if lock_lease is None:
            raise SystemExit(1)
        atexit.register(release_eval_run_lock, lock_lease)
        lock_lease.update_state(current_phase="env_up")
        _env_up()
        lock_lease.update_state(current_phase="ready")
        # Keep the lock exclusive only through bootstrap, then downgrade so
        # other workspace consumers can coexist on the shared lock.
        downgrade_eval_run_lock_to_shared(lock_lease)
        fail_closed_if_integration_test_setup(
            os.getenv("CONTROLLER_URL", "http://localhost:18000"),
            context="seed workspace materializer startup",
        )

    if args.launch_cli_exec:
        raise SystemExit(
            launch_cli_exec(
                materialized.workspace_dir,
                materialized.prompt_text,
                agent_name=agent,
                task_id=row.id,
                yolo=args.yolo,
                provider_name=args.provider,
            )
        )

    if args.open_cli_ui:
        raise SystemExit(
            open_cli_ui(
                materialized.workspace_dir,
                materialized.prompt_text,
                agent_name=agent,
                task_id=row.id,
                yolo=args.yolo,
                provider_name=args.provider,
                new_terminal=args.new_terminal,
            )
        )


if __name__ == "__main__":
    main()
