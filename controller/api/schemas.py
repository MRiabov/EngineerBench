import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from shared.enums import (
    AgentName,
    AssetType,
    EpisodeStatus,
    FailureClass,
    ResponseStatus,
    ReviewDecision,
    TerminalReason,
    TraceType,
)
from shared.models.schemas import (
    DatasetRowArchiveManifest,
    EntryValidationContext,
    EpisodeMetadata,
    ReplayArtifactRecord,
    ReplayFailureSignal,
    ReplayTraceIds,
    TraceMetadata,
)
from shared.models.simulation import SimulationResult
from shared.observability.schemas import ReviewDecisionEvent
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.workers.schema import (
    PlanReviewManifest,
    ReviewManifest,
    ValidationResultRecord,
)


class StandardResponse(BaseModel):
    status: ResponseStatus
    message: str


class BenchmarkGenerateResponse(StandardResponse):
    session_id: uuid.UUID
    episode_id: uuid.UUID


class BenchmarkConfirmResponse(StandardResponse):
    pass


class IntegrationTestStatusResponse(BaseModel):
    is_integration_test: bool


class ObjectStoragePointer(BaseModel):
    bucket: str
    key: str
    sha256: str
    size_bytes: int


class AgentRunResponse(StandardResponse):
    episode_id: uuid.UUID


class TraceResponse(BaseModel):
    id: int
    user_session_id: uuid.UUID | None = None
    langfuse_trace_id: str | None
    simulation_run_id: str | None = None
    cots_query_id: str | None = None
    review_id: str | None = None
    trace_type: TraceType
    name: str | None
    content: str | None
    metadata_vars: TraceMetadata | None = None
    feedback_score: int | None = None
    feedback_comment: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @property
    def metadata(self) -> TraceMetadata | None:
        """Backward-compatible alias for clients using `metadata`."""
        return self.metadata_vars


class AssetResponse(BaseModel):
    id: int
    user_session_id: uuid.UUID | None = None
    asset_type: AssetType
    s3_path: str
    content: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BenchmarkObjectivesResponse(StandardResponse):
    objectives: dict


class DatasetExportRequest(BaseModel):
    episode_id: uuid.UUID


class DatasetExportResponse(StandardResponse):
    export_id: uuid.UUID
    episode_id: uuid.UUID
    archive: ObjectStoragePointer
    manifest: DatasetRowArchiveManifest


class EpisodeResponse(BaseModel):
    id: uuid.UUID
    user_session_id: uuid.UUID | None = None
    task: StrictStr
    status: EpisodeStatus
    created_at: datetime
    updated_at: datetime
    skill_git_hash: str | None = None
    template_versions: dict | None = None
    metadata_vars: EpisodeMetadata | None = None
    todo_list: dict | None = None
    journal: str | None = None
    plan: str | None = None
    validation_logs: list[str] | None = None
    last_trace_id: int | None = None
    traces: list[TraceResponse] = []
    assets: list[AssetResponse] = []

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @property
    def metadata(self) -> EpisodeMetadata | None:
        """Backward-compatible alias for clients using `metadata`."""
        return self.metadata_vars


class ReplayReviewManifestResponse(BaseModel):
    path: str
    manifest: ReviewManifest | PlanReviewManifest

    model_config = ConfigDict(extra="forbid")


class EpisodeReplayResponse(EpisodeResponse):
    worker_session_id: str | None = None
    simulation_run_id: str | None = None
    cots_query_id: str | None = None
    review_id: str | None = None
    terminal_reason: TerminalReason | None = None
    failure_class: FailureClass | None = None
    detailed_status: str | None = None
    entry_validation: EntryValidationContext | None = None
    replay_artifacts: list[ReplayArtifactRecord] = Field(default_factory=list)
    trace_ids: ReplayTraceIds = Field(default_factory=ReplayTraceIds)
    validation_result: ValidationResultRecord | None = None
    simulation_result: SimulationResult | None = None
    review_manifests: list[ReplayReviewManifestResponse] = Field(default_factory=list)
    review_decision_events: list[ReviewDecisionEvent] = Field(default_factory=list)
    failure_signals: list[ReplayFailureSignal] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ArtifactEntry(BaseModel):
    """A single artifact entry from the /artifacts/{session_id} endpoint."""

    path: str
    size: int | None = None
    content: str | None = None


class EpisodeCreateResponse(BaseModel):
    """Response from the /test/episodes endpoint (used in integration tests)."""

    __test__ = False
    episode_id: uuid.UUID


class TestEpisodeCreateResponse(EpisodeCreateResponse):
    """Backward-compatible alias for episode create response."""

    __test__ = False


class EpisodeListItem(BaseModel):
    """A lightweight episode entry from the GET /episodes/ list endpoint."""

    id: uuid.UUID
    user_session_id: uuid.UUID | None = None
    task: str
    status: EpisodeStatus
    created_at: datetime
    updated_at: datetime
    skill_git_hash: str | None = None
    metadata_vars: EpisodeMetadata | None = None
    journal: str | None = None
    plan: str | None = None
    todo_list: dict | None = None
    last_trace_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


class ReviewResponse(BaseModel):
    """Response from posting a review decision to /episodes/{id}/review."""

    status: ResponseStatus
    decision: ReviewDecision


class CotsSearchItem(BaseModel):
    """A single COTS part returned from search."""

    part_id: str
    name: str
    category: str
    manufacturer: str
    price: float
    source: str
    weight_g: float
    metadata: dict[str, Any] = Field(alias="metadata_vars", default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class CotsMetadataResponse(BaseModel):
    """Metadata for the current COTS catalog."""

    catalog_version: str
    bd_warehouse_commit: str
    generated_at: str | None = None


class OpenAPISchema(BaseModel):
    """Minimal OpenAPI schema for integration testing contracts."""

    paths: dict[str, dict[str, Any]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


# --- Consolidated Request Models ---


class AgentRunRequest(BaseModel):
    task: StrictStr = Field(..., description="The task for the agent to perform.")
    session_id: StrictStr = Field(..., description="Session ID for the worker.")
    start_node: AgentName | None = Field(
        None,
        description="Optional first node to enter within a unified agent graph.",
    )
    user_session_id: uuid.UUID | None = Field(
        None, description="UI conversation scope session ID."
    )
    metadata_vars: EpisodeMetadata | None = Field(
        None, description="Additional metadata for the episode."
    )
    skill_git_hash: str | None = Field(
        None, description="Git hash of the skills used for this run."
    )
    agent_name: AgentName = Field(
        AgentName.ENGINEER_CODER, description="The name of the agent to run."
    )

    @field_validator("task", "session_id", "skill_git_hash")
    @classmethod
    def strip_null_bytes(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.replace("\u0000", "")

    @field_validator("metadata_vars", mode="before")
    @classmethod
    def strip_null_bytes_in_metadata(cls, v: Any) -> Any:
        if v is None:
            return None

        def _clean(value):
            if isinstance(value, str):
                return value.replace("\u0000", "")
            if isinstance(value, dict):
                return {
                    (_clean(k) if isinstance(k, str) else k): _clean(val)
                    for k, val in value.items()
                }
            if isinstance(value, list):
                return [_clean(item) for item in value]
            return value

        return _clean(v)


class BenchmarkGenerateRequest(BaseModel):
    prompt: str
    start_node: AgentName | None = None
    max_cost: float | None = Field(default=None, gt=0)
    max_weight: float | None = Field(default=None, gt=0)
    target_quantity: int | None = Field(default=None, ge=1)
    seed_id: str | None = None
    seed_dataset: str | None = None
    generation_kind: str | None = None
    backend: SimulatorBackendType = Field(default_factory=get_default_simulator_backend)

    @field_validator("prompt")
    @classmethod
    def strip_null_bytes(cls, v: str) -> str:
        return v.replace("\u0000", "")


class ConfirmRequest(BaseModel):
    comment: str | None = None
    additional_turns: int = Field(
        default=0,
        ge=0,
        description="Optional extra turns to grant before resuming execution.",
    )


class UpdateObjectivesRequest(BaseModel):
    max_cost: float | None = Field(default=None, gt=0)
    max_weight: float | None = Field(default=None, gt=0)
    target_quantity: int | None = Field(default=None, ge=1)


class FeedbackRequest(BaseModel):
    score: Literal[0, 1]
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def strip_null_bytes(cls, v: str | None) -> str | None:
        if v is not None:
            return v.replace("\u0000", "")
        return v


class ReviewRequest(BaseModel):
    review_content: str

    @field_validator("review_content")
    @classmethod
    def strip_null_bytes(cls, v: str) -> str:
        return v.replace("\u0000", "")


class MessageRequest(BaseModel):
    message: StrictStr
    additional_turns: int = Field(
        default=0,
        ge=0,
        description="Optional extra turns to grant before continuing the episode.",
    )
    metadata_vars: EpisodeMetadata | None = Field(
        None, description="Additional metadata for the message."
    )

    @field_validator("message")
    @classmethod
    def strip_null_bytes(cls, v: str) -> str:
        return v.replace("\u0000", "")
