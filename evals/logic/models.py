from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.enums import AgentName, EvalMode, ReviewDecision


class AgentEvalSpec(BaseModel):
    """Runtime details for an eval agent type."""

    mode: EvalMode  # benchmark | agent | git
    request_agent_name: AgentName | None = None
    required_trace_names: tuple[AgentName, ...] = ()
    start_node: AgentName | None = None
    required_reviewer_handover_manifest: str | None = None
    required_reviewer_stage: str | None = None
    materialize_reviewer_handover: bool = False
    review_filename_prefix: str | None = None


class EvalDatasetItem(BaseModel):
    id: str
    task: str
    complexity_level: int = Field(ge=0, le=5)
    family_name: str | None = None
    seed_dataset: Path | None = None
    seed_artifact_dir: Path | None = None
    seed_files: dict[str, str] | None = None
    split_source_task_id: str | None = None
    git_eval: "GitEvalConfig | None" = None
    expected_decision: ReviewDecision | None = None

    model_config = ConfigDict(extra="allow")


class E2EResumeStageRecord(BaseModel):
    stage_index: int = Field(ge=0)
    agent_name: AgentName
    workspace_dir: Path
    session_id: str | None = None
    launch_return_code: int | None = None
    verification_name: str | None = None
    verification_success: bool | None = None
    simulation_success: bool | None = None
    review_decision: str | None = None


class E2EResumeState(BaseModel):
    seed_dir: Path
    workspace_root: Path
    stages: list[E2EResumeStageRecord] = Field(default_factory=list)

    def last_completed_stage(self) -> E2EResumeStageRecord | None:
        if not self.stages:
            return None
        return self.stages[-1]


class HardCheckAggregate(BaseModel):
    total: int = 0
    passed: int = 0
    failed_seeds: list[str] = Field(default_factory=list)
    failure_pointers: dict[str, "HardCheckFailurePointer"] = Field(default_factory=dict)


class HardCheckRunLogPointer(BaseModel):
    path: str
    line: int
    event: str | None = None
    hint: str | None = None


class HardCheckFailurePointer(BaseModel):
    session_id: str | None = None
    session_status: str | None = None
    session_log_dir: str | None = None
    log_pointers: list[str] = Field(default_factory=list)
    run_log_pointers: list[HardCheckRunLogPointer] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    error_sources: list[str] = Field(default_factory=list)


class GitStatusExpectation(BaseModel):
    branch: str | None = None
    is_dirty: bool | None = None
    is_merging: bool | None = None
    conflicts: list[str] | None = None


class GitConflictResolutionStep(BaseModel):
    file_path: str
    strategy: Literal["ours", "theirs"]


class GitEvalConfig(BaseModel):
    setup_commands: list[str] = Field(default_factory=list)
    commit_message: str | None = None
    expect_commit_hash: bool | None = None
    resolve_conflicts: list[GitConflictResolutionStep] = Field(default_factory=list)
    abort_merge: bool = False
    merge_complete_message: str | None = None
    expected_status: GitStatusExpectation | None = None

    @model_validator(mode="after")
    def validate_merge_actions(self) -> "GitEvalConfig":
        if self.abort_merge and self.merge_complete_message is not None:
            raise ValueError(
                "git_eval.abort_merge and git_eval.merge_complete_message "
                "are mutually exclusive"
            )
        return self
