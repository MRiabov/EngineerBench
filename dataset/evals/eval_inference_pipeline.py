#!/usr/bin/env python3
"""Run the application inference pipeline with explicit job progression.

This entrypoint is the formal application-facing wrapper around the stage
driven inference pipeline. It loads ``inference_config.yaml`` for the
pipeline contract, keeps explicit job state under ``logs/evals/``, and can
optionally persist successful outputs back into the seed corpus.

The implementation deliberately reuses the existing seed worker where a stage
is wired while the outer orchestration becomes a product-level pipeline.
"""

from __future__ import annotations

import asyncio
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import shutil
import time
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.logic.dataset_selection import (  # noqa: E402
    parse_level_filters,
    parse_task_id_filters,
)
from evals.logic.codex_workspace import (  # noqa: E402
    launch_cli_exec,
    materialize_seed_workspace,
    verify_workspace_for_agent,
)
from evals.logic.inference_pipeline import (  # noqa: E402
    DEFAULT_INFERENCE_CONFIG_PATH,
    InferenceJobRequest,
    InferenceJobResult,
    InferenceJobState,
    InferenceJobStatus,
    InferencePipelineConfig,
    InferencePipelineMode,
    InferenceRunSummary,
    InferenceStageConfig,
    InferenceStageExecutorName,
    InferenceWorkspaceSource,
    InferenceWorkspaceSourceType,
    load_inference_config,
    load_inference_job_state,
    prepare_inference_run_dir,
    write_inference_job_state,
)
from evals.logic.models import EvalDatasetItem  # noqa: E402
from evals.logic.seed_maintenance import (  # noqa: E402
    refresh_seed_artifact_manifests,
)
from shared.eval_artifacts import workspace_artifacts_for_agent  # noqa: E402
from shared.enums import AgentName  # noqa: E402


DEFAULT_PROVIDER = "codex"
DEFAULT_SEED_WORKERS = 4
DEFAULT_AUTHOR_RETRIES = 1
DEFAULT_VALIDATION_SCOPE = "current-and-previous-nodes"
DEFAULT_FAMILIES = [
    "gap_bridge",
    "central_bypass",
    "narrow_funnel",
    "lower_bin",
    "shelf_ascent",
    "clearance_gate",
    "s_corridor",
    "terrain_ridge",
    "post_capture",
    "motion_aware",
]
ENGINEER_TASK_STATE_REL = Path("logs/evals/seed_update_autopilot/task_state.json")
_ENGINEER_TASK_ID_RE = re.compile(r"^ep-(?P<family>[a-z-]+)-(?P<variant>\d{2})$")
_WORKSPACE_SKIP_DIR_NAMES = {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the formal application inference pipeline with stage-driven "
            "job progression."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_INFERENCE_CONFIG_PATH,
        help="Path to inference_config.yaml.",
    )
    parser.add_argument(
        "--stage",
        default=None,
        help=(
            "Pipeline stage to execute. Defaults to the config entry stage. "
            "The selected stage must have a wired executor."
        ),
    )
    parser.add_argument(
        "--author",
        action="store_true",
        help="Run the author/validate/review worker loop.",
    )
    parser.add_argument(
        "--family",
        action="append",
        choices=DEFAULT_FAMILIES,
        default=None,
        help="Restrict the run to one or more engineer_planner families.",
    )
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help=(
            "Restrict the run to one or more canonical task ids. Supports "
            "repeated flags, comma-separated values, or list syntax."
        ),
    )
    parser.add_argument(
        "--level",
        action="append",
        default=None,
        help=(
            "Restrict the run to selected complexity levels. Supports "
            "repeated flags, comma-separated values, or list syntax."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of selected jobs after filtering.",
    )
    parser.add_argument(
        "--provider",
        choices=("codex", "qwen"),
        default=DEFAULT_PROVIDER,
        help="CLI provider used for both authoring and review prompts.",
    )
    parser.add_argument(
        "--seed-workers",
        type=int,
        default=None,
        help="Override the configured worker count for selected jobs.",
    )
    parser.add_argument(
        "--author-retries",
        type=int,
        default=None,
        help="Override the configured extra repair rounds per job.",
    )
    parser.add_argument(
        "--skip-env-up",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Assume the eval stack is already running.",
    )
    parser.add_argument(
        "--queue",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Wait for shared eval locks instead of failing fast.",
    )
    parser.add_argument(
        "--validation-scope",
        default=None,
        help="Validation scope forwarded to scripts/validate_eval_seed.py.",
    )
    parser.add_argument(
        "--update-manifests",
        dest="update_manifests",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Refresh deterministic seed manifests during maintenance.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip the review prompt after deterministic validation.",
    )
    parser.add_argument(
        "--persist-results",
        dest="persist_results",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Copy successful outputs back into the seed corpus after "
            "validation and review. Use --no-persist-results to run the "
            "pipeline without backfilling the corpus."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned jobs without executing them.",
    )
    parser.add_argument(
        "--resume-token",
        default=None,
        help=(
            "Resume selection after the named job id. The token must match a "
            "candidate job in the selected stage, otherwise the run fails closed."
        ),
    )
    return parser.parse_args()


def _sanitize_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)
    cleaned = cleaned.strip("-")
    return cleaned or "item"


def _workspace_dir_for_item(
    run_dir: Path, stage_name: str, item_id: str
) -> Path:
    return run_dir / "workspaces" / _sanitize_slug(stage_name) / _sanitize_slug(item_id)


def _prepare_run_dir(pipeline_name: str) -> Path:
    run_dir = prepare_inference_run_dir(root=ROOT, pipeline_name=pipeline_name)
    return run_dir


def _load_selected_stage(
    config: InferencePipelineConfig, stage_name: str | None
) -> InferenceStageConfig:
    chosen_name = stage_name or config.entry_stage_name
    return config.stage(chosen_name)


def _job_id(stage_name: str, task_id: str) -> str:
    return f"{stage_name}:{task_id}"


def _job_state_allows_retry(status: InferenceJobStatus) -> bool:
    return status in {
        InferenceJobStatus.FAILED,
        InferenceJobStatus.INTERRUPTED,
    }


def _fanout_output_job_ids(stage: InferenceStageConfig, job_id: str) -> list[str]:
    output_job_ids: list[str] = []
    for downstream_stage_name in stage.downstream_stage_names:
        for index in range(1, stage.outputs_per_success + 1):
            output_job_ids.append(
                f"{job_id}->{downstream_stage_name}#{index:02d}"
            )
    return output_job_ids


def _queue_downstream_job_states(
    *,
    pipeline_job_state: dict[str, InferenceJobState],
    summary: InferenceRunSummary,
    stage: InferenceStageConfig,
    source_job_id: str,
    started_at: str,
    finished_at: str,
    recorded_at: str,
    stage_config: InferencePipelineConfig,
) -> list[str]:
    queued_job_ids: list[str] = []
    for downstream_stage_name in stage.downstream_stage_names:
        downstream_stage = stage_config.stage(downstream_stage_name)
        for index in range(1, stage.outputs_per_success + 1):
            queued_job_id = f"{source_job_id}->{downstream_stage_name}#{index:02d}"
            pipeline_job_state[queued_job_id] = InferenceJobState(
                job_id=queued_job_id,
                stage_name=downstream_stage.name,
                agent_name=downstream_stage.agent_name,
                status=InferenceJobStatus.QUEUED,
                source_job_id=source_job_id,
                source_run_started_at=started_at,
                source_run_finished_at=finished_at,
                recorded_at=recorded_at,
                output_job_ids=[],
            )
            queued_job_ids.append(queued_job_id)
    if queued_job_ids:
        summary.queued_job_ids.extend(queued_job_ids)
    return queued_job_ids


def _apply_resume_token(
    selected_items: list[SelectedStageItem],
    *,
    stage: InferenceStageConfig,
    resume_token: str | None,
) -> tuple[list[SelectedStageItem], list[str]]:
    if resume_token is None:
        return selected_items, []

    job_ids = [_job_id(stage.name, selected.item.id) for selected in selected_items]
    if resume_token not in job_ids:
        raise SystemExit(
            f"Stale --resume-token {resume_token!r}: it does not match any "
            f"candidate job for stage {stage.name!r}"
        )
    resume_index = job_ids.index(resume_token)
    return selected_items[resume_index + 1 :], job_ids[: resume_index + 1]


def _stage_persistence_target_dir(stage: InferenceStageConfig, item: EvalDatasetItem) -> Path | None:
    if item.seed_artifact_dir is None:
        return None
    if stage.agent_name == AgentName.ENGINEER_PLANNER:
        return ROOT / item.seed_artifact_dir
    return ROOT / "dataset" / "data" / "seed" / "artifacts" / "engineer_planner" / item.id


def _load_resume_state_skip_ids(
    pipeline_states: dict[str, InferenceJobState]
) -> set[str]:
    skipped: set[str] = set()
    for job_id, state in pipeline_states.items():
        if not _job_state_allows_retry(state.status):
            skipped.add(job_id)
    return skipped


def _job_state_from_result(
    *,
    result: InferenceJobResult,
    started_at: str,
    finished_at: str | None = None,
) -> InferenceJobState:
    return InferenceJobState(
        job_id=result.job_id,
        stage_name=result.stage_name,
        agent_name=result.agent_name,
        status=result.status,
        source_job_id=result.source_job_id,
        bundle_fingerprint=result.bundle_fingerprint,
        last_validation_passed=result.validation_passed,
        last_review_passed=result.review_passed,
        source_run_started_at=started_at,
        source_run_finished_at=finished_at,
        recorded_at=finished_at or started_at,
        failure_reason=result.failure_reason,
        output_job_ids=result.output_job_ids,
    )


def _write_summary(run_dir: Path, summary: InferenceRunSummary) -> Path:
    summary_path = run_dir / "inference_pipeline_summary.json"
    summary_path.write_text(
        summary.model_dump_json(indent=2, exclude_none=True) + "\n",
        encoding="utf-8",
    )
    return summary_path


@dataclass(slots=True)
class SelectedStageItem:
    item: EvalDatasetItem
    raw_row: dict[str, Any]
    family: str | None = None


def _seed_dataset_path_for_agent(agent_name: AgentName) -> Path:
    return ROOT / "dataset" / "data" / "seed" / "role_based" / f"{agent_name.value}.json"


def _infer_row_family(agent_name: AgentName, raw_row: dict[str, Any]) -> str | None:
    family = raw_row.get("family")
    if isinstance(family, str) and family.strip():
        return family.strip()

    if agent_name != AgentName.ENGINEER_PLANNER:
        return None

    task_id = raw_row.get("id")
    if not isinstance(task_id, str):
        return None

    match = _ENGINEER_TASK_ID_RE.fullmatch(task_id)
    if match is None:
        return None
    return match.group("family").replace("-", "_")


def _load_stage_items(
    *,
    stage: InferenceStageConfig,
    families: list[str] | None,
    task_ids: set[str] | None,
    levels: set[int] | None,
    limit: int,
) -> tuple[list[SelectedStageItem], list[str]]:
    dataset_path = _seed_dataset_path_for_agent(stage.agent_name)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Missing seed dataset for {stage.agent_name.value}: {dataset_path}")

    try:
        rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Failed to read seed dataset {dataset_path}") from exc
    if not isinstance(rows, list):
        raise ValueError(f"Seed dataset is not a list: {dataset_path}")

    requested_task_ids = set(task_ids or set())
    selected: list[SelectedStageItem] = []
    seen_requested: set[str] = set()

    for raw_row in rows:
        if not isinstance(raw_row, dict):
            continue

        task_id = raw_row.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            continue
        task_id = task_id.strip()

        if requested_task_ids and task_id not in requested_task_ids:
            continue

        complexity_level = raw_row.get("complexity_level")
        if levels and not isinstance(complexity_level, int):
            continue
        if levels and complexity_level not in levels:
            continue

        row_family = _infer_row_family(stage.agent_name, raw_row)
        if families and row_family not in families:
            continue

        payload = dict(raw_row)
        payload["seed_dataset"] = dataset_path.relative_to(ROOT)
        try:
            item = EvalDatasetItem.model_validate(payload)
        except Exception as exc:
            raise RuntimeError(
                f"Invalid seed row for {stage.agent_name.value}: {task_id}"
            ) from exc

        selected.append(
            SelectedStageItem(item=item, raw_row=raw_row, family=row_family)
        )
        seen_requested.add(task_id)

        if limit > 0 and len(selected) >= limit:
            break

    if requested_task_ids:
        missing = sorted(requested_task_ids - seen_requested)
        if missing:
            raise SystemExit(
                "Unknown canonical inference task id(s) for "
                f"{stage.agent_name.value}: " + ", ".join(missing)
            )

    return selected, []


def _compatibility_state_path(root: Path) -> Path:
    return root / ENGINEER_TASK_STATE_REL


def _load_compatibility_seed_state(root: Path) -> dict[str, dict[str, Any]]:
    state_path = _compatibility_state_path(root)
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    states: dict[str, dict[str, Any]] = {}
    for task_id, raw_state in payload.items():
        if isinstance(task_id, str) and isinstance(raw_state, dict):
            states[task_id] = raw_state
    return states


def _write_compatibility_seed_state(
    root: Path, states: dict[str, dict[str, Any]]
) -> Path:
    state_path = _compatibility_state_path(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {task_id: state for task_id, state in sorted(states.items())}
    state_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return state_path


def _bundle_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()

    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _bundle_copy_allowed(rel_path: str, stage_agent_name: AgentName) -> bool:
    allowed_exact = set(workspace_artifacts_for_agent(stage_agent_name))
    allowed_prefixes = (
        ".manifests/",
        "reviews/",
        "renders/",
    )
    allowed_exact.update(
        {
            "manufacturing_config.yaml",
            "simulation_result.json",
            "validation_results.json",
        }
    )
    return rel_path in allowed_exact or any(
        rel_path.startswith(prefix) for prefix in allowed_prefixes
    )


def _copy_workspace_bundle(
    *,
    workspace_dir: Path,
    target_dir: Path,
    stage_agent_name: AgentName,
) -> None:
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    for source_path in sorted(
        (path for path in workspace_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(workspace_dir).as_posix(),
    ):
        rel_path = source_path.relative_to(workspace_dir).as_posix()
        if not _bundle_copy_allowed(rel_path, stage_agent_name):
            continue
        destination = target_dir / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def _refresh_persisted_bundle_artifacts(
    target_dir: Path, *, update_manifests: bool
) -> None:
    refresh_seed_artifact_manifests(target_dir, fix=update_manifests)


def _job_request_for_item(
    *,
    stage: InferenceStageConfig,
    item: EvalDatasetItem,
    persist_results: bool,
    raw_row: dict[str, Any],
) -> InferenceJobRequest:
    metadata: dict[str, Any] = {
        "agent_name": stage.agent_name.value,
        "complexity_level": item.complexity_level,
    }
    if item.seed_artifact_dir is not None:
        metadata["seed_artifact_dir"] = str(item.seed_artifact_dir)
    row_family = _infer_row_family(stage.agent_name, raw_row)
    if row_family is not None:
        metadata["family"] = row_family
    if isinstance(raw_row.get("variant"), int):
        metadata["variant"] = int(raw_row["variant"])
    return InferenceJobRequest(
        job_id=_job_id(stage.name, item.id),
        stage_name=stage.name,
        mode=InferencePipelineMode.APPLICATION,
        workspace_source=InferenceWorkspaceSource(
            source_type=InferenceWorkspaceSourceType.SEED_ROW,
            task_id=item.id,
            seed_artifact_dir=item.seed_artifact_dir,
            notes=f"{stage.name} application inference job",
        ),
        persist_results=persist_results,
        metadata=metadata,
    )


def _result_status_for_success(
    *,
    copied_back: bool,
    validate_only: bool,
) -> InferenceJobStatus:
    if copied_back:
        return InferenceJobStatus.PERSISTED
    if validate_only:
        return InferenceJobStatus.VALIDATED
    return InferenceJobStatus.REVIEWED


def _run_workspace_job(
    *,
    stage: InferenceStageConfig,
    item: EvalDatasetItem,
    raw_row: dict[str, Any],
    provider_name: str,
    run_dir: Path,
    persist_results: bool,
    validate_only: bool,
    update_manifests: bool,
) -> InferenceJobResult:
    job_id = _job_id(stage.name, item.id)
    workspace_dir = _workspace_dir_for_item(run_dir, stage.name, item.id)
    workspace_dir.parent.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    request = _job_request_for_item(
        stage=stage,
        item=item,
        persist_results=persist_results,
        raw_row=raw_row,
    )
    session_id = f"{stage.name}-{_sanitize_slug(item.id)}-{time.strftime('%Y%m%d_%H%M%S')}"

    try:
        materialized = materialize_seed_workspace(
            item=item,
            agent_name=stage.agent_name,
            workspace_dir=workspace_dir,
            provider_name=provider_name,
        )
        launch_return_code = launch_cli_exec(
            materialized.workspace_dir,
            materialized.prompt_text,
            task_id=item.id,
            agent_name=stage.agent_name,
            session_id=session_id,
            runtime_root=run_dir,
            yolo=True,
            provider_name=provider_name,
        )
        if launch_return_code != 0:
            return InferenceJobResult(
                job_id=job_id,
                stage_name=stage.name,
                agent_name=stage.agent_name,
                status=InferenceJobStatus.FAILED,
                task_id=item.id,
                workspace_dir=materialized.workspace_dir,
                run_dir=run_dir,
                failure_reason=f"CLI provider exited with code {launch_return_code}",
                selected_task_ids=[],
                completed_task_ids=[],
                skipped_task_ids=[],
                output_job_ids=[],
            )

        verification = asyncio.run(
            verify_workspace_for_agent(
                workspace_dir=materialized.workspace_dir,
                agent_name=stage.agent_name,
                session_id=session_id,
                expected_decision=item.expected_decision,
            )
        )
        if not verification.success:
            return InferenceJobResult(
                job_id=job_id,
                stage_name=stage.name,
                agent_name=stage.agent_name,
                status=InferenceJobStatus.FAILED,
                task_id=item.id,
                workspace_dir=materialized.workspace_dir,
                run_dir=run_dir,
                failure_reason="; ".join(verification.errors) or verification.verification_name,
                selected_task_ids=[],
                completed_task_ids=[],
                skipped_task_ids=[],
                output_job_ids=[],
            )

        copied_back = False
        target_dir = _stage_persistence_target_dir(stage, item)
        if persist_results and not validate_only and target_dir is not None:
            _copy_workspace_bundle(
                workspace_dir=materialized.workspace_dir,
                target_dir=target_dir,
                stage_agent_name=stage.agent_name,
            )
            _refresh_persisted_bundle_artifacts(
                target_dir,
                update_manifests=update_manifests,
            )
            copied_back = True
            if stage.agent_name == AgentName.ENGINEER_PLANNER:
                compatibility_state = _load_compatibility_seed_state(ROOT)
                compatibility_state[item.id] = {
                    "task_id": item.id,
                    "bundle_fingerprint": _bundle_fingerprint(target_dir),
                    "last_validation_passed": True,
                    "last_review_passed": True,
                    "source_run_started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "source_run_finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
                _write_compatibility_seed_state(ROOT, compatibility_state)

        status = _result_status_for_success(
            copied_back=copied_back, validate_only=validate_only
        )
        fingerprint_source = (
            ROOT / item.seed_artifact_dir
            if copied_back and item.seed_artifact_dir
            else materialized.workspace_dir
        )
        bundle_fingerprint = _bundle_fingerprint(fingerprint_source)
        return InferenceJobResult(
            job_id=job_id,
            stage_name=stage.name,
            agent_name=stage.agent_name,
            status=status,
            source_job_id=request.metadata.get("upstream_job_id"),
            task_id=item.id,
            workspace_dir=materialized.workspace_dir,
            run_dir=run_dir,
            copied_back=copied_back,
            validation_passed=True,
            review_passed=not validate_only,
            bundle_fingerprint=bundle_fingerprint,
            selected_task_ids=[item.id],
            completed_task_ids=[item.id],
            skipped_task_ids=[],
            output_job_ids=(
                _fanout_output_job_ids(stage, job_id)
                if status != InferenceJobStatus.FAILED
                else []
            ),
        )
    except Exception as exc:
        return InferenceJobResult(
            job_id=job_id,
            stage_name=stage.name,
            agent_name=stage.agent_name,
            status=InferenceJobStatus.FAILED,
            task_id=item.id,
            workspace_dir=workspace_dir,
            run_dir=run_dir,
            failure_reason=str(exc),
            selected_task_ids=[],
            completed_task_ids=[],
            skipped_task_ids=[],
            output_job_ids=[],
        )


def _run_planned_stage(*, stage: InferenceStageConfig, **_: Any) -> None:
    raise SystemExit(
        f"Stage {stage.name!r} uses declarative executor {stage.executor!r}; "
        "there is no runtime adapter yet."
    )


EXECUTOR_REGISTRY: dict[
    InferenceStageExecutorName,
    Any,
] = {
    InferenceStageExecutorName.PLANNED: _run_planned_stage,
    InferenceStageExecutorName.SEED_WORKER: _run_workspace_job,
}


def main() -> int:
    args = _parse_args()
    if not args.author:
        raise SystemExit("--author is required for the inference pipeline")
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    if args.seed_workers is not None and args.seed_workers < 1:
        raise SystemExit("--seed-workers must be >= 1")
    if args.author_retries is not None and args.author_retries < 0:
        raise SystemExit("--author-retries must be >= 0")

    config = load_inference_config(args.config)
    selected_stage = _load_selected_stage(config, args.stage)
    stage_executor = EXECUTOR_REGISTRY.get(selected_stage.executor)
    if stage_executor is None:
        raise SystemExit(
            f"Unsupported executor for stage {selected_stage.name!r}: "
            f"{selected_stage.executor!r}"
        )

    seed_workers = (
        args.seed_workers
        if args.seed_workers is not None
        else selected_stage.worker_hints.seed_workers
        if selected_stage.worker_hints.seed_workers is not None
        else config.worker_hints.seed_workers
        if config.worker_hints.seed_workers is not None
        else DEFAULT_SEED_WORKERS
    )
    author_retries = (
        args.author_retries
        if args.author_retries is not None
        else selected_stage.worker_hints.author_retries
        if selected_stage.worker_hints.author_retries is not None
        else config.worker_hints.author_retries
        if config.worker_hints.author_retries is not None
        else DEFAULT_AUTHOR_RETRIES
    )
    queue = (
        args.queue
        if args.queue is not None
        else selected_stage.worker_hints.queue
        if selected_stage.worker_hints.queue is not None
        else config.worker_hints.queue
        if config.worker_hints.queue is not None
        else False
    )
    skip_env_up = (
        args.skip_env_up
        if args.skip_env_up is not None
        else selected_stage.worker_hints.skip_env_up
        if selected_stage.worker_hints.skip_env_up is not None
        else config.worker_hints.skip_env_up
        if config.worker_hints.skip_env_up is not None
        else False
    )
    validation_scope = (
        args.validation_scope
        if args.validation_scope is not None
        else selected_stage.worker_hints.validation_scope
        if selected_stage.worker_hints.validation_scope is not None
        else config.worker_hints.validation_scope
        if config.worker_hints.validation_scope is not None
        else DEFAULT_VALIDATION_SCOPE
    )
    update_manifests = (
        args.update_manifests
        if args.update_manifests is not None
        else selected_stage.worker_hints.update_manifests
        if selected_stage.worker_hints.update_manifests is not None
        else config.worker_hints.update_manifests
        if config.worker_hints.update_manifests is not None
        else True
    )
    persist_results = (
        args.persist_results
        if args.persist_results is not None
        else selected_stage.persist_back_to_seed
    )

    selected_families = (
        list(args.family)
        if args.family is not None
        else (
            list(DEFAULT_FAMILIES)
            if selected_stage.agent_name == AgentName.ENGINEER_PLANNER
            else None
        )
    )
    requested_task_ids = parse_task_id_filters(args.task_id)
    selected_levels = parse_level_filters(args.level)
    if args.level and not selected_levels:
        raise SystemExit("No valid --level values were parsed.")
    if args.family and selected_stage.agent_name != AgentName.ENGINEER_PLANNER:
        raise SystemExit("--family is only supported for engineer_planner stages")

    run_dir = _prepare_run_dir(config.pipeline_name)
    pipeline_task_state = load_inference_job_state(ROOT)
    pipeline_skip_ids = _load_resume_state_skip_ids(pipeline_task_state)
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary = InferenceRunSummary(
        pipeline_name=config.pipeline_name,
        version=config.version,
        mode=config.mode,
        started_at=started_at,
        finished_at=None,
        resume_token=args.resume_token,
        config_path=args.config,
        run_dir=run_dir,
    )

    selected_items, _ = _load_stage_items(
        stage=selected_stage,
        families=selected_families,
        task_ids=set(requested_task_ids) if requested_task_ids else None,
        levels=selected_levels,
        limit=args.limit,
    )
    selected_items, resumed_job_ids = _apply_resume_token(
        selected_items,
        stage=selected_stage,
        resume_token=args.resume_token,
    )
    compatibility_task_state = _load_compatibility_seed_state(ROOT)
    skipped_existing_job_ids: list[str] = []
    if selected_stage.agent_name == AgentName.ENGINEER_PLANNER:
        retained_items: list[SelectedStageItem] = []
        for selected in selected_items:
            item = selected.item
            task_id = item.id
            source_dir = item.seed_artifact_dir
            if source_dir is None:
                retained_items.append(selected)
                continue
            current_dir = ROOT / source_dir
            current_fingerprint = _bundle_fingerprint(current_dir)
            current_state = compatibility_task_state.get(task_id)
            if (
                current_state
                and current_state.get("bundle_fingerprint") == current_fingerprint
                and current_state.get("last_validation_passed")
                and current_state.get("last_review_passed")
            ):
                skipped_existing_job_ids.append(_job_id(selected_stage.name, task_id))
                continue
            retained_items.append(selected)
        selected_items = retained_items

    skipped_pipeline = [
        _job_id(selected_stage.name, selected.item.id)
        for selected in selected_items
        if _job_id(selected_stage.name, selected.item.id) in pipeline_skip_ids
    ]
    selected_items = [
        selected
        for selected in selected_items
        if _job_id(selected_stage.name, selected.item.id) not in pipeline_skip_ids
    ]
    summary.selected_job_ids = [
        _job_id(selected_stage.name, selected.item.id) for selected in selected_items
    ]
    summary.skipped_job_ids = sorted(
        set(skipped_existing_job_ids) | set(skipped_pipeline) | set(resumed_job_ids)
    )

    if not selected_items:
        if summary.skipped_job_ids:
            summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            summary.success = True
            summary.next_resume_token = summary.resume_token
            summary_path = _write_summary(run_dir, summary)
            print(f"Summary written to {summary_path}")
            print(f"Run directory: {run_dir}")
            print(
                "No pipeline jobs queued: matching rows are already complete "
                "or intentionally skipped."
            )
            return 0
        summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary.success = False
        summary.next_resume_token = summary.resume_token
        summary_path = _write_summary(run_dir, summary)
        print(f"Summary written to {summary_path}")
        raise SystemExit("No inference jobs matched the selection.")

    if args.dry_run:
        queued_job_ids: list[str] = []
        for selected in selected_items:
            request = _job_request_for_item(
                stage=selected_stage,
                item=selected.item,
                persist_results=persist_results,
                raw_row=selected.raw_row,
            )
            raw_variant = selected.raw_row.get("variant")
            variant_text = (
                f"{int(raw_variant):02d}"
                if isinstance(raw_variant, int)
                else "n/a"
            )
            print(
                f"DRY RUN {request.job_id}: family={selected.family or 'n/a'} "
                f"variant={variant_text} level={selected.item.complexity_level} "
                f"persist_results={request.persist_results}"
            )
            queued_job_ids.extend(
                _fanout_output_job_ids(selected_stage, request.job_id)
            )
        summary.jobs = [
            InferenceJobResult(
                job_id=_job_id(selected_stage.name, selected.item.id),
                stage_name=selected_stage.name,
                agent_name=selected_stage.agent_name,
                status=InferenceJobStatus.QUEUED,
                task_id=selected.item.id,
                run_dir=run_dir,
                selected_task_ids=[selected.item.id],
                output_job_ids=_fanout_output_job_ids(
                    selected_stage,
                    _job_id(selected_stage.name, selected.item.id),
                ),
            )
            for selected in selected_items
        ]
        summary.queued_job_ids = sorted(set(queued_job_ids))
        summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary.success = True
        summary.next_resume_token = summary.jobs[-1].job_id if summary.jobs else summary.resume_token
        summary_path = _write_summary(run_dir, summary)
        print(f"Summary written to {summary_path}")
        print(f"Run directory: {run_dir}")
        return 0

    if stage_executor is _run_planned_stage:
        summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary.success = False
        summary_path = _write_summary(run_dir, summary)
        print(f"Summary written to {summary_path}")
        stage_executor(stage=selected_stage)

    if not skip_env_up:
        env_up_path = ROOT / "scripts" / "env_up.sh"
        if not env_up_path.exists():
            raise FileNotFoundError(f"Missing env bootstrap script: {env_up_path}")
        env = dict(os.environ)
        if queue:
            env["PROBLEMOLOGIST_EVAL_LOCK_QUEUE"] = "1"
        print(f"bootstrapping eval environment with: {env_up_path}")
        completed = subprocess.run(
            [str(env_up_path), "--profile", "eval"],
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            summary.success = False
            summary_path = _write_summary(run_dir, summary)
            print(f"Summary written to {summary_path}")
            return completed.returncode

    pipeline_job_state = dict(pipeline_task_state)
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=seed_workers) as pool:
        future_map = {}
        for selected in selected_items:
            future = pool.submit(
                _run_workspace_job,
                stage=selected_stage,
                item=selected.item,
                raw_row=selected.raw_row,
                provider_name=args.provider,
                run_dir=run_dir,
                persist_results=persist_results,
                validate_only=args.validate_only,
                update_manifests=update_manifests,
            )
            future_map[future] = selected

        for future in as_completed(future_map):
            selected = future_map[future]
            request = _job_request_for_item(
                stage=selected_stage,
                item=selected.item,
                persist_results=persist_results,
                raw_row=selected.raw_row,
            )
            try:
                result = future.result()
            except Exception as exc:
                result = InferenceJobResult(
                    job_id=request.job_id,
                    stage_name=selected_stage.name,
                    agent_name=selected_stage.agent_name,
                    status=InferenceJobStatus.FAILED,
                    task_id=selected.item.id,
                    workspace_dir=_workspace_dir_for_item(
                        run_dir, selected_stage.name, selected.item.id
                    ),
                    run_dir=run_dir,
                    failure_reason=str(exc),
                )

            summary.jobs.append(result)
            if result.status == InferenceJobStatus.PERSISTED:
                summary.completed_job_ids.append(result.job_id)
                summary.persisted_job_ids.append(result.job_id)
                print(f"[job] PERSISTED {result.job_id}")
            elif result.status in {
                InferenceJobStatus.REVIEWED,
                InferenceJobStatus.VALIDATED,
            }:
                summary.completed_job_ids.append(result.job_id)
                print(f"[job] COMPLETED {result.job_id} status={result.status.value}")
            else:
                summary.failed_job_ids.append(result.job_id)
                failures.append(result.job_id)
                print(
                    f"[job] FAIL {result.job_id}: "
                    f"{result.failure_reason or 'unknown failure'}"
                )

            pipeline_job_state[result.job_id] = _job_state_from_result(
                result=result,
                started_at=summary.started_at,
                finished_at=None,
            )
            if result.status != InferenceJobStatus.FAILED:
                queued_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
                _queue_downstream_job_states(
                    pipeline_job_state=pipeline_job_state,
                    summary=summary,
                    stage=selected_stage,
                    source_job_id=result.job_id,
                    started_at=summary.started_at,
                    finished_at=queued_at,
                    recorded_at=queued_at,
                    stage_config=config,
                )
            write_inference_job_state(ROOT, pipeline_job_state)

            if result.workspace_dir is not None:
                shutil.rmtree(result.workspace_dir, ignore_errors=True)

            summary_path = _write_summary(run_dir, summary)
            print(f"Summary written to {summary_path}")

    summary.finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary.success = not failures
    summary.queued_job_ids = sorted(set(summary.queued_job_ids))
    summary.next_resume_token = summary.jobs[-1].job_id if summary.jobs else summary.resume_token

    for job in summary.jobs:
        state = pipeline_job_state.get(job.job_id)
        if state is None:
            continue
        pipeline_job_state[job.job_id] = InferenceJobState(
            job_id=state.job_id,
            stage_name=state.stage_name,
            agent_name=state.agent_name,
            status=state.status,
            source_job_id=state.source_job_id,
            bundle_fingerprint=state.bundle_fingerprint,
            last_validation_passed=state.last_validation_passed,
            last_review_passed=state.last_review_passed,
            source_run_started_at=state.source_run_started_at,
            source_run_finished_at=summary.finished_at,
            recorded_at=summary.finished_at,
            failure_reason=state.failure_reason,
            output_job_ids=state.output_job_ids,
        )
    write_inference_job_state(ROOT, pipeline_job_state)

    summary_path = _write_summary(run_dir, summary)
    print(f"Summary written to {summary_path}")
    print(f"Run directory: {run_dir}")
    if summary.completed_job_ids:
        print("Completed jobs: " + ", ".join(sorted(summary.completed_job_ids)))
    if failures:
        print("Failed jobs: " + ", ".join(sorted(failures)))

    return 0 if summary.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
