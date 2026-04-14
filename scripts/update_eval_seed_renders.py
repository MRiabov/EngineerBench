from __future__ import annotations

import argparse
import asyncio
import atexit
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
from evals.logic.stack_profiles import apply_stack_profile_env  # noqa: E402
from scripts.internal.eval_run_lock import (  # noqa: E402
    EvalRunSelection,
    acquire_eval_run_shared_lock,
    release_eval_run_lock,
)
from scripts.internal.eval_seed_selection import (  # noqa: E402
    infer_seed_agent_for_task_id,
    load_seed_dataset,
    seed_dataset_agents,
)
from shared.enums import AgentName  # noqa: E402
from shared.workers.schema import RenderManifest  # noqa: E402

_STACK_PROFILE_NAME = (
    "integration"
    if os.getenv("IS_INTEGRATION_TEST", "").strip().lower() == "true"
    else "eval"
)
apply_stack_profile_env(_STACK_PROFILE_NAME, env=os.environ, root=ROOT)


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


_RENDER_SIDE_CAR_FILENAMES = {
    "render_index.jsonl",
    "preview_scene.json",
    "frames.jsonl",
    "objects.parquet",
}
_RENDER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_RENDER_EVIDENCE_EXTENSIONS = _RENDER_IMAGE_EXTENSIONS | {".mp4"}


def _discover_render_sidecars(artifact_dir: Path) -> list[str]:
    renders_dir = artifact_dir / "renders"
    if not renders_dir.exists():
        return []

    discovered: list[str] = []
    for path in renders_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name not in _RENDER_SIDE_CAR_FILENAMES:
            continue
        discovered.append(str(path.relative_to(artifact_dir)).replace("\\", "/"))
    return sorted(dict.fromkeys(discovered))


def _render_manifest_image_paths(
    manifest: RenderManifest,
) -> tuple[list[str], list[str]]:
    preview_paths = sorted(
        dict.fromkeys(
            Path(path).as_posix().lstrip("/")
            for path in manifest.preview_evidence_paths
            if path and Path(path).suffix.lower() in _RENDER_IMAGE_EXTENSIONS
        )
    )
    artifact_paths = sorted(
        dict.fromkeys(
            Path(path).as_posix().lstrip("/")
            for path in manifest.artifacts
            if Path(path).suffix.lower() in _RENDER_IMAGE_EXTENSIONS
        )
    )
    return preview_paths, artifact_paths


def _validate_required_render_sidecars(
    artifact_dir: Path,
    *,
    render_paths: list[str],
) -> None:
    missing: list[str] = []

    for rel_path in render_paths:
        if not rel_path.endswith("render_manifest.json"):
            continue

        manifest_path = artifact_dir / rel_path
        if not manifest_path.exists():
            continue

        manifest = RenderManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        bundle_root = artifact_dir / Path(manifest.bundle_path or Path(rel_path).parent)
        preview_image_paths, artifact_image_paths = _render_manifest_image_paths(
            manifest
        )
        if (
            preview_image_paths
            and artifact_image_paths
            and (preview_image_paths != artifact_image_paths)
        ):
            raise RuntimeError(
                f"{manifest_path.relative_to(artifact_dir)} preview evidence paths "
                "do not match the render artifact image set"
            )

        evidence_paths = [
            Path(path)
            for path in manifest.preview_evidence_paths
            if path and Path(path).suffix.lower() in _RENDER_EVIDENCE_EXTENSIONS
        ]
        if not evidence_paths:
            evidence_paths = [
                Path(path)
                for path in manifest.artifacts
                if Path(path).suffix.lower() in _RENDER_EVIDENCE_EXTENSIONS
            ]

        expected_image_paths = (
            preview_image_paths if preview_image_paths else artifact_image_paths
        )
        missing_images = [
            Path(path).as_posix().lstrip("/")
            for path in expected_image_paths
            if not (artifact_dir / path).exists()
        ]
        if missing_images:
            raise RuntimeError(
                "Rendered eval seed bundle is missing required render image "
                f"file(s): {sorted(dict.fromkeys(missing_images))}"
            )

        if any(path.suffix.lower() == ".mp4" for path in evidence_paths):
            for required_name in ("frames.jsonl", "objects.parquet"):
                required_path = bundle_root / required_name
                if required_path.exists():
                    continue
                missing.append(
                    str(required_path.relative_to(artifact_dir)).replace("\\", "/")
                )

    if missing:
        raise RuntimeError(
            "Rendered eval seed bundle is missing required sidecar file(s): "
            f"{sorted(dict.fromkeys(missing))}"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate deterministic seeded eval render bundles without "
            "running seed validation."
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
        help="Update renders only for one specific task ID.",
    )
    parser.add_argument(
        "--level",
        action="append",
        default=None,
        help=(
            "Update renders only for the selected complexity levels. Supports "
            "a single level, repeated flags, comma-separated values, or list "
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
        "--queue",
        action="store_true",
        help=(
            "Wait for the eval lock when another eval consumer is active "
            "instead of failing fast."
        ),
    )
    parser.add_argument(
        "--skip-env-up",
        action="store_true",
        help=(
            "Compatibility alias for eval-maintenance workflows. This "
            "command never bootstraps env_up and always joins the shared "
            "eval lock directly."
        ),
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Suppress per-row progress output.",
    )
    return parser.parse_args()


def _update_item(
    agent: AgentName,
    item,
    *,
    errors_only: bool,
) -> tuple[bool, bool, str]:
    artifact_dir = _resolve_seed_artifact_dir(item, root=ROOT)
    if artifact_dir is None:
        if not errors_only:
            print(f"SKIP {agent.value} {item.id}: prompt-only row")
        return True, False, "prompt-only row; no seeded artifact directory"

    from scripts.internal.eval_seed_renders import update_seed_artifact_renders

    saved_paths = update_seed_artifact_renders(artifact_dir)
    saved_paths.extend(_discover_render_sidecars(artifact_dir))
    saved_paths = sorted(dict.fromkeys(saved_paths))
    _validate_required_render_sidecars(artifact_dir, render_paths=saved_paths)
    saved_count = len(saved_paths)
    if not errors_only:
        print(f"UPDATED {agent.value} {item.id}: {saved_count} render file(s)")
    return True, True, "seed render bundle updated"


async def _async_main(args: argparse.Namespace) -> int:
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

    lock_lease = acquire_eval_run_shared_lock(
        queue=args.queue,
        requested_command=[sys.argv[0], *sys.argv[1:]],
        requested_selection=EvalRunSelection(
            agent=agents[0].value if len(agents) == 1 else None,
            task_ids=[args.task_id] if args.task_id else [],
            levels=sorted(levels) if levels else [],
        ),
    )
    if lock_lease is None:
        return 1
    atexit.register(release_eval_run_lock, lock_lease)

    checked = 0
    touched = 0
    skipped = 0
    failures: list[tuple[str, str, str]] = []

    for agent in agents:
        dataset = load_seed_dataset(
            agent,
            task_id=args.task_id,
            limit=args.limit,
            levels=levels if levels else None,
            root=ROOT,
        )
        if args.task_id and not dataset:
            failures.append((agent.value, args.task_id, "task id not found in dataset"))
            continue
        for item in dataset:
            checked += 1
            try:
                ok, rendered, detail = _update_item(
                    agent,
                    item,
                    errors_only=args.errors_only,
                )
            except Exception as exc:
                ok, rendered, detail = False, False, str(exc)
            if not ok:
                failures.append((agent.value, item.id, detail))
            elif rendered:
                touched += 1
            else:
                skipped += 1

    if checked == 0 and not failures:
        print("No dataset rows matched the requested filter.", file=sys.stderr)
        return 1

    if failures:
        for agent_value, item_id, detail in failures:
            print(
                f"FAILED {agent_value} {item_id}: {detail}",
                file=sys.stderr,
            )
        if not args.errors_only:
            print(
                f"Processed {checked} row(s): {touched} updated, {skipped} skipped, "
                f"{len(failures)} failed.",
                file=sys.stderr,
            )
        return 1

    if not args.errors_only:
        print(f"Processed {checked} row(s): {touched} updated, {skipped} skipped.")

    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
