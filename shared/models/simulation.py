from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from shared.enums import FailureReason, SimulationConfidence
from shared.simulation.schemas import SimulatorBackendType


class RenderMode(StrEnum):
    STATIC_PREVIEW = "static_preview"
    SIMULATION_VIDEO = "simulation_video"


class RendererCapabilities(BaseModel):
    backend_name: str
    artifact_modes_supported: list[RenderMode] = Field(default_factory=list)
    supports_default_view: bool = True
    supports_named_cameras: bool = True
    supports_rgb: bool = True
    supports_depth: bool = False
    supports_segmentation: bool = False
    default_view_label: str | None = None


class SimulationRenderProvenance(BaseModel):
    artifact_mode: RenderMode = RenderMode.SIMULATION_VIDEO
    backend_type: SimulatorBackendType
    backend_name: str
    renderer_capabilities: RendererCapabilities | None = None
    available_camera_names: list[str] = Field(default_factory=list)
    camera_candidates: list[str] = Field(default_factory=list)
    resolved_camera_name: str | None = None
    used_default_view: bool = False
    resolved_default_view_label: str | None = None
    capture_interval_seconds: float | None = None
    capture_interval_steps: int | None = None
    captured_frame_count: int = 0
    render_error: str | None = None


class PayloadTrajectoryMonitorState(BaseModel):
    """Runtime stop context for engineer-owned payload trajectory monitoring."""

    tracked_body_names: list[str] = Field(default_factory=list)
    last_checked_anchor_index: int | None = None
    last_checked_anchor_t_s: float | None = None
    monitor_sample_stride_s: float | None = None
    configured_consecutive_miss_count: int | None = None
    consecutive_miss_count: int = 0
    observed_position_mm: tuple[float, float, float] | None = None
    observed_rotation_deg: tuple[float, float, float] | None = None
    position_error_mm: tuple[float, float, float] | None = None
    rotation_error_deg: tuple[float, float, float] | None = None
    required_first_contacts: list[str] = Field(default_factory=list)
    observed_first_contacts: list[str] = Field(default_factory=list)
    terminal_goal_zone_proven: bool = False
    failure_detail: str | None = None

    model_config = {"extra": "forbid"}


class SimulationFailure(BaseModel):
    """Structured failure information for simulation."""

    reason: FailureReason
    detail: str | None = None
    payload_trajectory_monitor: PayloadTrajectoryMonitorState | None = None

    def __str__(self) -> str:
        if self.detail:
            return f"{self.reason}:{self.detail}"
        return str(self.reason)

    def __eq__(self, other: Any) -> bool:
        """
        Supports exact match with another SimulationFailure or
        a reason-only match with a FailureReason enum.
        """
        if isinstance(other, FailureReason):
            return self.reason == other
        return super().__eq__(other)


class SimulationMetrics(BaseModel):
    total_time: float = 0.0
    total_energy: float = 0.0
    max_velocity: float = 0.0
    success: bool = False
    fail_reason: str | None = None
    fail_mode: FailureReason | None = None
    failure: SimulationFailure | None = None
    payload_trajectory_monitor: PayloadTrajectoryMonitorState | None = None
    events: list[dict] = Field(default_factory=list)
    confidence: SimulationConfidence = SimulationConfidence.HIGH


class SimulationResult(BaseModel):
    success: bool
    summary: str
    failure_reason: str | None = None
    fail_mode: FailureReason | None = None
    failure: SimulationFailure | None = None
    payload_trajectory_monitor: PayloadTrajectoryMonitorState | None = None
    render_provenance: SimulationRenderProvenance | None = None
    render_paths: list[str] = Field(default_factory=list)
    render_object_store_keys: dict[str, str] = Field(default_factory=dict)
    mjcf_content: str | None = None
    total_cost: float = 0.0
    total_weight_g: float = 0.0
    confidence: SimulationConfidence = SimulationConfidence.HIGH


class MultiRunResult(BaseModel):
    """Result of batched runtime-randomization verification."""

    num_scenes: int
    success_count: int
    success_rate: float
    is_consistent: bool  # True if all runs agree on success/fail
    individual_results: list[SimulationMetrics]
    fail_reasons: list[str]  # Unique failure reasons across runs
    scene_build_count: int = 1
    backend_run_count: int = 1
    batched_execution: bool = True

    model_config = {"extra": "forbid"}
