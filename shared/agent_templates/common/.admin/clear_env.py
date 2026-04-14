"""Reset a seeded Codex workspace in place.

The helper removes the current workspace contents and re-materializes the same
seeded row so the Codex conversation can continue without restarting.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import ModuleType

from shared.enums import AgentName


def _parse_prompt_metadata(workspace_dir: Path) -> tuple[AgentName, str]:
    prompt_path = workspace_dir / "prompt.md"
    if not prompt_path.exists():
        raise SystemExit(f"prompt.md not found in {workspace_dir}")

    agent_value: str | None = None
    task_id: str | None = None
    for line in prompt_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Agent: "):
            agent_value = line.split(": ", 1)[1].strip()
        elif line.startswith("Task ID: "):
            task_id = line.split(": ", 1)[1].strip()

    if not agent_value:
        raise SystemExit("prompt.md does not contain an Agent line")
    if not task_id:
        raise SystemExit("prompt.md does not contain a Task ID line")

    try:
        agent_name = AgentName(agent_value)
    except ValueError as exc:
        raise SystemExit(f"Unknown agent in prompt.md: {agent_value}") from exc

    return agent_name, task_id


def _resolve_repo_root() -> Path:
    raw_root = os.getenv("PROBLEMOLOGIST_REPO_ROOT", "").strip()
    if not raw_root:
        raise SystemExit("PROBLEMOLOGIST_REPO_ROOT is required to reset the workspace")

    repo_root = Path(raw_root).expanduser().resolve()
    if not repo_root.exists():
        raise SystemExit(f"Repository root not found: {repo_root}")
    return repo_root


def _load_materializer_module(repo_root: Path) -> ModuleType:
    module_path = repo_root / "dataset" / "evals" / "materialize_seed_workspace.py"
    if not module_path.exists():
        raise SystemExit(f"Materializer not found: {module_path}")

    spec = importlib.util.spec_from_file_location(
        "problemologist_materialize_seed_workspace",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load materializer module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clear_workspace(workspace_dir: Path) -> list[str]:
    removed: list[str] = []
    for path in sorted(workspace_dir.iterdir(), key=lambda entry: entry.name):
        if path.name == ".git":
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(path.name)
    return removed


def main() -> int:
    workspace_dir = Path.cwd().expanduser().resolve()
    if workspace_dir == Path(workspace_dir.anchor):
        raise SystemExit("Refusing to clear the filesystem root")

    agent_name, task_id = _parse_prompt_metadata(workspace_dir)
    repo_root = _resolve_repo_root()
    materializer = _load_materializer_module(repo_root)
    dataset_path, rows = materializer._load_dataset(agent_name)  # type: ignore[attr-defined]
    row = materializer._select_row(  # type: ignore[attr-defined]
        rows,
        task_id=task_id,
        agent=agent_name,
    )
    row = materializer.EvalDatasetItem.model_validate(  # type: ignore[attr-defined]
        {
            **row,
            "seed_dataset": str(dataset_path.relative_to(repo_root)),
        }
    )

    removed = _clear_workspace(workspace_dir)
    restored = materializer.materialize_workspace(  # type: ignore[attr-defined]
        item=row,
        agent_name=agent_name,
        workspace_dir=workspace_dir,
    )

    print(
        json.dumps(
            {
                "agent": agent_name.value,
                "copied_paths": restored.copied_paths,
                "ok": True,
                "removed_paths": removed,
                "seed_dataset": str(dataset_path.relative_to(repo_root)),
                "task_id": task_id,
                "workspace_dir": str(restored.workspace_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
