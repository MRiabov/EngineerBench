from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.enums import (
    AgentName,
    EntryFailureDisposition,
    FailureReason,
    ManufacturingMethod,
    ReviewDecision,
)

# Alias for backward compatibility
SimulationFailureMode = FailureReason


class ObservabilityEventType(StrEnum):
    # 1. Component usage
    COMPONENT_USAGE = "component_usage"
    # 2. Tool invocation
    TOOL_INVOCATION = "tool_invocation"
    # 3. Manufacturability and price check (engineer)
    MANUFACTURABILITY_CHECK = "manufacturability_check"
    # 4. Scene valiation (Benchmark CAD engineer)
    SCENE_VALIDATION = "scene_validation"
    # 5. Render request (engineer)
    RENDER_REQUEST_ENGINEER = "render_request_engineer"
    # 6. Render request (benchmark)
    RENDER_REQUEST_BENCHMARK = "render_request_benchmark"
    VALIDATION_PREVIEW_BACKEND_SELECTED = "validation_preview_backend_selected"
    VALIDATION_PREVIEW_RENDER_COMPLETE = "validation_preview_render_complete"
    # 7. Simulation request (engineer)
    SIMULATION_REQUEST = "simulation_request"
    # 8. Simulation result (engineer)
    SIMULATION_RESULT = "simulation_result"
    # 9. COTS search (engineer/planner?)
    COTS_SEARCH = "cots_search"
    COTS_SELECTION = "cots_selection"
    # 10. Plan submission (benchmark)
    PLAN_SUBMISSION_BENCHMARK = "plan_submission_benchmark"
    # 11. Plan submission (Engineer)
    PLAN_SUBMISSION_ENGINEER = "plan_submission_engineer"
    # 12. Price/weight failure escalation request (CAD engineer)
    ESCALATION_REQUEST = "escalation_request"
    # 13. Price/weight failure escalation decision (reviewer)
    ESCALATION_DECISION = "escalation_decision"
    TOOL_INSPECT_MEDIA = "inspect_media_tool"
    # 14. Submission validation
    SUBMISSION_VALIDATION = "submission_validation"
    # 15. Cost/weight delta heuristic
    COST_WEIGHT_DELTA = "cost_weight_delta"
    # 16. Review decision (full details)
    REVIEW_DECISION = "review_decision"
    EXCESSIVE_DOF_DETECTED = "excessive_dof_detected"

    # 25. Simulation and physics events
    SIMULATION_BACKEND_SELECTED = "simulation_backend_selected"
    MESHING_FAILURE = "meshing_failure"
    PHYSICS_INSTABILITY = "physics_instability"
    GPU_OOM_RETRY = "gpu_oom_retry"
    CONVERSATION_LENGTH_EXCEEDED = "conversation_length_exceeded"
    NODE_ENTRY_VALIDATION_FAILED = "node_entry_validation_failed"
    MEDIA_INSPECTION = "media_inspection"
    LLM_MEDIA_ATTACHED = "llm_media_attached"


class BaseEvent(BaseModel):
    """Base class for all observability events."""

    model_config = ConfigDict(use_enum_values=True, extra="allow")

    event_type: ObservabilityEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_id: str | None = None
    user_session_id: str | None = None
    episode_id: str | None = None


class ComponentUsageEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.COMPONENT_USAGE
    category: str
    part_number: str
    label: str
    price: float
    weight_g: float


class ToolInvocationEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.TOOL_INVOCATION
    tool_name: str
    arguments: dict[str, Any]


class ManufacturabilityCheckEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.MANUFACTURABILITY_CHECK
    part_id: str
    method: ManufacturingMethod
    result: bool  # pass/fail
    price: float | None = None
    weight_g: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneValidationEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.SCENE_VALIDATION
    result: bool
    errors: list[str] = Field(default_factory=list)


class RenderRequestEngineerEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.RENDER_REQUEST_ENGINEER
    num_views: int = 24


class RenderRequestBenchmarkEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.RENDER_REQUEST_BENCHMARK
    num_views: int = 24


class SimulationRequestEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.SIMULATION_REQUEST
    script_path: str


class SimulationMetadata(BaseModel):
    """Metadata for simulation results."""

    num_steps: int | None = None
    max_penetration: float | None = None
    is_clipping: bool = False


class SimulationResultEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.SIMULATION_RESULT
    success: bool
    failure_reason: SimulationFailureMode = SimulationFailureMode.NONE
    failure: Any | None = None  # Structured SimulationFailure
    time_elapsed_s: float
    compute_time_ms: float
    simulation_run_id: str | None = None
    metadata: SimulationMetadata = Field(default_factory=SimulationMetadata)


class COTSSearchEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.COTS_SEARCH
    query: str
    results_count: int
    catalog_version: str | None = None
    bd_warehouse_commit: str | None = None
    generated_at: str | None = None
    cots_query_id: str | None = None
    catalog_snapshot_id: str | None = None
    candidates: list[str] = Field(default_factory=list)  # Ordered part_ids
    selected_part_ids: list[str] = Field(default_factory=list)


class COTSSelectionEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.COTS_SELECTION
    selected_part_ids: list[str]
    query_ids: list[str] = Field(default_factory=list)


class PlanSubmissionBenchmarkEvent(BaseEvent):
    event_type: ObservabilityEventType = (
        ObservabilityEventType.PLAN_SUBMISSION_BENCHMARK
    )
    plan_path: str


class PlanSubmissionEngineerEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.PLAN_SUBMISSION_ENGINEER
    plan_path: str


class EscalationRequestEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.ESCALATION_REQUEST
    reason: str
    current_price: float | None = None
    current_weight: float | None = None


class EscalationDecisionEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.ESCALATION_DECISION
    decision: str  # "approved", "rejected"
    comments: list[str] = Field(default_factory=list)


class InspectMediaToolEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.TOOL_INSPECT_MEDIA
    path: str
    mime_type: str
    media_kind: str
    attached_to_model: bool = False
    attached_media_count: int = 0


class SubmissionValidationEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.SUBMISSION_VALIDATION
    artifacts_present: list[str]
    verification_passed: bool
    reasoning_trace_quality: float = Field(..., ge=0.0, le=1.0)
    errors: list[str] = Field(default_factory=list)


class CostWeightDeltaEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.COST_WEIGHT_DELTA
    best_simulated_cost: float
    best_simulated_weight_g: float
    final_cost: float
    final_weight_g: float
    is_worse: bool


class ReviewEvidenceStats(BaseModel):
    """Stats for evidence used in a review."""

    has_sim_report: bool = False
    has_mfg_report: bool = False
    num_renders: int = 0
    simulations_run: int = 0
    review_decision_path: str | None = None
    review_comments_path: str | None = None


class ReviewDecisionEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.REVIEW_DECISION
    decision: ReviewDecision
    reason: str
    review_id: str | None = None
    evidence_stats: ReviewEvidenceStats = Field(default_factory=ReviewEvidenceStats)
    checklist: dict[str, str | float | bool] = Field(default_factory=dict)


class ExcessiveDofDetectedEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.EXCESSIVE_DOF_DETECTED
    reviewer_stage: str
    part_id: str
    proposed_dofs: list[str]
    expected_minimal_engineering_dofs: list[str]
    expected_minimal_dofs: list[str]
    dof_count: int
    dof_count_gt_3: bool


class ReviewEvent(BaseEvent):
    """Event emitted when a review is submitted."""

    event_type: ObservabilityEventType = ObservabilityEventType.REVIEW_DECISION
    episode_id: str
    decision: ReviewDecision
    comments: list[str] = Field(default_factory=list)
    review_id: str | None = None
    checklist: dict[str, str | float | bool] = Field(default_factory=dict)


class SimulationBackendSelectedEvent(BaseEvent):
    event_type: ObservabilityEventType = (
        ObservabilityEventType.SIMULATION_BACKEND_SELECTED
    )
    backend: str
    compute_target: str


class PhysicsInstabilityEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.PHYSICS_INSTABILITY
    kinetic_energy: float
    threshold: float
    step: int


class GpuOomRetryEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.GPU_OOM_RETRY
    original_particles: int
    reduced_particles: int


class ConversationLengthExceededEvent(BaseEvent):
    event_type: ObservabilityEventType = (
        ObservabilityEventType.CONVERSATION_LENGTH_EXCEEDED
    )
    previous_length: int
    threshold: int
    compacted_length: int | None = None
    compaction_strategy: str = "journal_summarization"
    message: str = (
        "Conversation length exceeded configured limit; context was compacted."
    )


class NodeEntryValidationFailedEvent(BaseEvent):
    event_type: ObservabilityEventType = (
        ObservabilityEventType.NODE_ENTRY_VALIDATION_FAILED
    )
    node: AgentName
    disposition: EntryFailureDisposition
    reason_code: str
    errors: list[dict[str, Any]] = Field(default_factory=list)
    reroute_target: AgentName | None = None


class MediaInspectionEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.MEDIA_INSPECTION
    path: str
    mime_type: str
    media_kind: str
    attached_to_model: bool = False
    attached_media_count: int = 0
    review_stage: str | None = None


class LlmMediaAttachedEvent(BaseEvent):
    event_type: ObservabilityEventType = ObservabilityEventType.LLM_MEDIA_ATTACHED
    path: str
    mime_type: str
    media_kind: str
    node_name: AgentName
    tool_name: str = "inspect_media"
    attached_media_count: int = 0
