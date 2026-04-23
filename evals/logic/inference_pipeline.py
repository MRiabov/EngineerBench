from __future__ import annotations

import json
import time
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.enums import AgentName

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INFERENCE_CONFIG_PATH = ROOT / "inference_config.yaml"
DEFAULT_INFERENCE_ROOT_REL = Path("logs/evals/inference_pipeline")
DEFAULT_INFERENCE_RUNS_REL = DEFAULT_INFERENCE_ROOT_REL / "runs"
DEFAULT_INFERENCE_STATE_REL = DEFAULT_INFERENCE_ROOT_REL / "task_state.json"


class InferencePipelineMode(StrEnum):
    APPLICATION = "application"
    EVAL_SEED_BACKFILL = "eval_seed_backfill"
    COMPATIBILITY_SEED_AUTOPILOT = "compatibility_seed_autopilot"


class InferenceJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATED = "validated"
    REVIEWED = "reviewed"
    PERSISTED = "persisted"
    SKIPPED = "skipped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class InferenceWorkspaceSourceType(StrEnum):
    SEED_ROW = "seed_row"
    ARTIFACT_DIR = "artifact_dir"
    DERIVED_JOB = "derived_job"
    BUNDLE = "bundle"


class InferenceStageExecutorName(StrEnum):
    PLANNED = "planned"
    SEED_WORKER = "seed_worker"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InferenceWorkerHints(StrictModel):
    seed_workers: int | None = Field(default=None, ge=1)
    author_retries: int | None = Field(default=None, ge=0)
    queue: bool | None = None
    skip_env_up: bool | None = None
    validation_scope: str | None = None
    update_manifests: bool | None = None


class InferenceRetryPolicy(StrictModel):
    max_attempts_per_job: int = Field(default=1, ge=1)
    retry_failed_validation: bool = True
    retry_failed_review: bool = True


class InferenceResumePolicy(StrictModel):
    checkpoint_on: list[InferenceJobStatus] = Field(
        default_factory=lambda: [
            InferenceJobStatus.VALIDATED,
            InferenceJobStatus.REVIEWED,
            InferenceJobStatus.PERSISTED,
            InferenceJobStatus.FAILED,
        ]
    )


class InferenceDeduplicationPolicy(StrictModel):
    skip_existing_clean_rows: bool = True
    skip_existing_repaired_rows: bool = False
    skip_existing_outputs: bool = False


class InferenceWorkspaceSource(StrictModel):
    source_type: InferenceWorkspaceSourceType
    task_id: str | None = None
    seed_artifact_dir: Path | None = None
    upstream_job_id: str | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_source(self) -> "InferenceWorkspaceSource":
        if self.source_type == InferenceWorkspaceSourceType.SEED_ROW:
            if not self.task_id:
                raise ValueError("seed_row workspace_source requires task_id")
        elif self.source_type == InferenceWorkspaceSourceType.ARTIFACT_DIR:
            if self.seed_artifact_dir is None:
                raise ValueError(
                    "artifact_dir workspace_source requires seed_artifact_dir"
                )
        elif self.source_type == InferenceWorkspaceSourceType.DERIVED_JOB:
            if not self.upstream_job_id:
                raise ValueError(
                    "derived_job workspace_source requires upstream_job_id"
                )
        return self


class InferenceStageConfig(StrictModel):
    name: str
    agent_name: AgentName
    outputs_per_success: int = Field(default=1, ge=1)
    persist_back_to_seed: bool = False
    downstream_stage_names: list[str] = Field(default_factory=list)
    worker_hints: InferenceWorkerHints = Field(default_factory=InferenceWorkerHints)
    executor: InferenceStageExecutorName = InferenceStageExecutorName.PLANNED
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("stage name must be a non-empty string")
        return text

    @field_validator("downstream_stage_names", mode="before")
    @classmethod
    def _normalize_downstream_stage_names(cls, value: object) -> list[str] | object:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return value
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_name in value:
            name = str(raw_name).strip()
            if not name:
                continue
            if name in seen:
                continue
            normalized.append(name)
            seen.add(name)
        return normalized


class InferencePipelineConfig(StrictModel):
    pipeline_name: str = "application_inference"
    version: int = Field(default=1, ge=1)
    mode: InferencePipelineMode = InferencePipelineMode.APPLICATION
    entry_stage_name: str
    stages: list[InferenceStageConfig] = Field(default_factory=list)
    worker_hints: InferenceWorkerHints = Field(default_factory=InferenceWorkerHints)
    retry_policy: InferenceRetryPolicy = Field(default_factory=InferenceRetryPolicy)
    resume_policy: InferenceResumePolicy = Field(default_factory=InferenceResumePolicy)
    deduplication: InferenceDeduplicationPolicy = Field(
        default_factory=InferenceDeduplicationPolicy
    )

    @field_validator("pipeline_name")
    @classmethod
    def _validate_pipeline_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("pipeline_name must be a non-empty string")
        return text

    @field_validator("entry_stage_name")
    @classmethod
    def _validate_entry_stage_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("entry_stage_name must be a non-empty string")
        return text

    @model_validator(mode="after")
    def _validate_stage_graph(self) -> "InferencePipelineConfig":
        stage_names: dict[str, InferenceStageConfig] = {}
        for stage in self.stages:
            if stage.name in stage_names:
                raise ValueError(f"duplicate inference stage name: {stage.name}")
            stage_names[stage.name] = stage

        if self.entry_stage_name not in stage_names:
            raise ValueError(
                f"entry_stage_name {self.entry_stage_name!r} is not declared in stages"
            )

        for stage in self.stages:
            for downstream_name in stage.downstream_stage_names:
                if downstream_name not in stage_names:
                    raise ValueError(
                        f"stage {stage.name!r} references unknown downstream "
                        f"stage {downstream_name!r}"
                    )
        return self

    def stage(self, stage_name: str) -> InferenceStageConfig:
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        raise KeyError(stage_name)

    def stage_names(self) -> tuple[str, ...]:
        return tuple(stage.name for stage in self.stages)


class InferenceJobRequest(StrictModel):
    job_id: str
    stage_name: str
    mode: InferencePipelineMode = InferencePipelineMode.APPLICATION
    workspace_source: InferenceWorkspaceSource
    persist_results: bool = False
    resume_token: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("job_id", "stage_name")
    @classmethod
    def _validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("value must be a non-empty string")
        return text


class InferenceJobResult(StrictModel):
    job_id: str
    stage_name: str
    agent_name: AgentName
    status: InferenceJobStatus
    source_job_id: str | None = None
    task_id: str | None = None
    workspace_dir: Path | None = None
    run_dir: Path | None = None
    copied_back: bool = False
    validation_passed: bool | None = None
    review_passed: bool | None = None
    bundle_fingerprint: str | None = None
    failure_reason: str | None = None
    selected_task_ids: list[str] = Field(default_factory=list)
    completed_task_ids: list[str] = Field(default_factory=list)
    skipped_task_ids: list[str] = Field(default_factory=list)
    output_job_ids: list[str] = Field(default_factory=list)

    @field_validator("job_id", "stage_name")
    @classmethod
    def _validate_result_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("value must be a non-empty string")
        return text


class InferenceJobState(StrictModel):
    job_id: str
    stage_name: str
    agent_name: AgentName
    status: InferenceJobStatus
    source_job_id: str | None = None
    bundle_fingerprint: str | None = None
    last_validation_passed: bool | None = None
    last_review_passed: bool | None = None
    source_run_started_at: str | None = None
    source_run_finished_at: str | None = None
    recorded_at: str
    failure_reason: str | None = None
    output_job_ids: list[str] = Field(default_factory=list)


class InferenceRunSummary(StrictModel):
    pipeline_name: str
    version: int
    mode: InferencePipelineMode
    started_at: str
    finished_at: str | None = None
    resume_token: str | None = None
    next_resume_token: str | None = None
    config_path: Path | None = None
    run_dir: Path | None = None
    selected_job_ids: list[str] = Field(default_factory=list)
    skipped_job_ids: list[str] = Field(default_factory=list)
    queued_job_ids: list[str] = Field(default_factory=list)
    completed_job_ids: list[str] = Field(default_factory=list)
    failed_job_ids: list[str] = Field(default_factory=list)
    persisted_job_ids: list[str] = Field(default_factory=list)
    jobs: list[InferenceJobResult] = Field(default_factory=list)
    success: bool = False


def inference_root(root: Path | None = None) -> Path:
    base = ROOT if root is None else root
    return base / DEFAULT_INFERENCE_ROOT_REL


def inference_runs_root(root: Path | None = None) -> Path:
    return inference_root(root) / "runs"


def inference_state_path(root: Path | None = None) -> Path:
    return inference_root(root) / "task_state.json"


def inference_config_path(root: Path | None = None) -> Path:
    base = ROOT if root is None else root
    return base / "inference_config.yaml"


def load_inference_config(config_path: Path | None = None) -> InferencePipelineConfig:
    path = config_path or inference_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Missing inference config: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, Mapping):
        raise ValueError(f"Inference config is not a mapping: {path}")
    return InferencePipelineConfig.model_validate(data)


def _load_state_payload(state_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_inference_job_state(root: Path | None = None) -> dict[str, InferenceJobState]:
    state_path = inference_state_path(root)
    if not state_path.exists():
        return {}
    payload = _load_state_payload(state_path)
    states: dict[str, InferenceJobState] = {}
    for job_id, raw_state in payload.items():
        if not isinstance(job_id, str) or not isinstance(raw_state, dict):
            continue
        try:
            states[job_id] = InferenceJobState.model_validate(raw_state)
        except Exception:
            continue
    return states


def write_inference_job_state(
    root: Path | None, states: dict[str, InferenceJobState]
) -> Path:
    state_path = inference_state_path(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        job_id: state.model_dump(mode="json")
        for job_id, state in sorted(states.items())
    }
    state_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return state_path


def _sanitize_pipeline_name(name: str) -> str:
    text = name.strip()
    if not text:
        return "pipeline"
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in text)


def prepare_inference_run_dir(
    *,
    root: Path | None = None,
    pipeline_name: str,
) -> Path:
    base = inference_runs_root(root)
    base.mkdir(parents=True, exist_ok=True)
    run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir = base / f"{run_id}_{_sanitize_pipeline_name(pipeline_name)}"
    suffix = 1
    while run_dir.exists():
        run_dir = base / f"{run_id}_{_sanitize_pipeline_name(pipeline_name)}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=True)

    current_link = inference_root(root) / "current"
    current_link.parent.mkdir(parents=True, exist_ok=True)
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to(run_dir.relative_to(inference_root(root)))
    return run_dir


def dump_inference_summary(summary: InferenceRunSummary) -> str:
    return yaml.safe_dump(
        summary.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
    )
