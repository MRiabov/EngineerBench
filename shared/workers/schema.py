from enum import StrEnum
from typing import Any, Literal, TypeAlias

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from shared.enums import (
    AgentName,
    AssetType,
    EpisodeStatus,
    ResponseStatus,
    SimulationConfidence,
)
from shared.models.simulation import (
    MultiRunResult,
    SimulationFailure,
)
from shared.observability.schemas import BaseEvent
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)
from shared.simulation.smoke_mode import ensure_smoke_test_mode_allowed
from shared.workers.workbench_models import ManufacturingMethod


def _validate_preview_camera_value(
    value: float | list[float],
    *,
    field_name: str,
) -> float | list[float]:
    if field_name == "orbit_pitch":
        lower_bound = -90.0
        upper_bound = 90.0
        upper_inclusive = True
    else:
        lower_bound = 0.0
        upper_bound = 360.0
        upper_inclusive = False

    values = value if isinstance(value, list) else [value]
    if not values:
        raise ValueError(f"{field_name} must contain at least one value")

    for item in values:
        if (
            item < lower_bound
            or item > upper_bound
            or (not upper_inclusive and item == upper_bound)
        ):
            if upper_inclusive:
                raise ValueError(
                    f"{field_name} values must be between {lower_bound} and {upper_bound} degrees"
                )
            raise ValueError(
                f"{field_name} values must be between {lower_bound} degrees and less than {upper_bound} degrees"
            )
    return value


class PreviewRenderingType(StrEnum):
    """Supported single-view preview modalities."""

    RGB = "rgb"
    DEPTH = "depth"
    SEGMENTATION = "segmentation"


class PreviewViewSpec(BaseModel):
    """One requested preview camera view after normalization."""

    view_index: StrictInt = Field(ge=0)
    orbit_pitch: float
    orbit_yaw: float

    model_config = ConfigDict(extra="forbid")


LEGACY_REVIEWER_STAGE_ALIASES = {
    "engineer_execution_reviewer": AgentName.ENGINEER_EXECUTION_REVIEWER,
}


class ReadFileResponse(BaseModel):
    """Response from reading a file."""

    content: StrictStr


class ReadFileBlobEntry(BaseModel):
    """One binary file returned from a batch read request."""

    path: StrictStr
    content_b64: StrictStr


class ReadFilesRequest(BaseModel):
    """Request to read multiple files as binary blobs."""

    paths: list[StrictStr] = Field(..., min_length=1)
    bypass_agent_permissions: bool = False


class ReadFilesResponse(BaseModel):
    """Response from a batch binary file read."""

    files: list[ReadFileBlobEntry] = Field(default_factory=list)
    missing_paths: list[StrictStr] = Field(default_factory=list)


class ExistsResponse(BaseModel):
    """Response for file existence check."""

    exists: StrictBool


class StatusResponse(BaseModel):
    """Generic status response."""

    status: ResponseStatus


class HealthResponse(BaseModel):
    """Health payload returned by controller/worker `/health` endpoints."""

    status: ResponseStatus

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value


class FailureSimulationConfig(BaseModel):
    """Configuration for simulating failures in activities."""

    mjcf_compilation: bool = False
    run_simulation: bool = False
    render_video: bool = False
    s3_upload: bool = False


class SimulationWorkflowParams(BaseModel):
    """Parameters for the simulation workflow."""

    compound_json: str
    episode_id: str
    simulate_failures: FailureSimulationConfig = Field(
        default_factory=FailureSimulationConfig
    )


class UpdateTraceParams(BaseModel):
    """Parameters for update_trace_activity."""

    episode_id: str
    s3_path: str
    asset_type: AssetType = AssetType.VIDEO
    status: EpisodeStatus = EpisodeStatus.COMPLETED
    error: str | None = None


class ListFilesRequest(BaseModel):
    """Request to list files in a directory."""

    path: StrictStr = Field(default="/")
    bypass_agent_permissions: bool = False


class FsFileEntry(BaseModel):
    """A single entry returned by the /fs/ls endpoint."""

    name: StrictStr
    path: StrictStr
    is_dir: bool
    size: int | None = None


class ReadFileRequest(BaseModel):
    """Request to read a file."""

    path: StrictStr = Field(..., min_length=1)
    bypass_agent_permissions: bool = False


class DeleteFileRequest(BaseModel):
    """Request to delete a file."""

    path: StrictStr = Field(..., min_length=1)
    bypass_agent_permissions: bool = False


class WriteFileRequest(BaseModel):
    """Request to write a file."""

    path: StrictStr = Field(..., min_length=1)
    content: StrictStr
    overwrite: bool = False  # was and should've been StrictBool?
    bypass_agent_permissions: bool = False


class UploadFilePayload(BaseModel):
    """A single file payload for batch workspace upload."""

    path: StrictStr = Field(..., min_length=1)
    content_b64: StrictStr = Field(..., min_length=1)


class UploadFilesRequest(BaseModel):
    """Request to upload multiple files in one JSON payload."""

    files: list[UploadFilePayload] = Field(..., min_length=1)
    bypass_agent_permissions: bool = False


class ObjectStoreUploadFilePayload(BaseModel):
    """One file staged by object-store key for a direct worker-side pull."""

    path: StrictStr = Field(..., min_length=1)
    object_store_key: StrictStr = Field(..., min_length=1)


class UploadFilesFromObjectStoreRequest(BaseModel):
    """Request to stage multiple files from object-store keys."""

    files: list[ObjectStoreUploadFilePayload] = Field(..., min_length=1)
    bypass_agent_permissions: bool = False


class EditOp(BaseModel):
    """A single edit operation (find and replace)."""

    old_string: StrictStr = Field(..., min_length=1)
    new_string: StrictStr


class EditFileRequest(BaseModel):
    """Request to edit a file with one or more operations."""

    path: StrictStr = Field(..., min_length=1)
    edits: list[EditOp] = Field(..., min_length=1)
    bypass_agent_permissions: bool = False


class GrepMatch(BaseModel):
    """A single match from a grep operation."""

    path: StrictStr
    line: StrictInt
    text: StrictStr


class GrepRequest(BaseModel):
    """Request to search for a pattern in files."""

    pattern: StrictStr = Field(..., min_length=1)
    path: StrictStr | None = None
    glob: StrictStr | None = None
    bypass_agent_permissions: bool = False


class ExecuteRequest(BaseModel):
    """Request to execute a shell command in the session workspace."""

    code: StrictStr = Field(..., min_length=1)
    timeout: StrictInt = Field(default=30, ge=1, le=1000)
    episode_id: StrictStr | None = None


class ExecuteResponse(BaseModel):
    """Response from executing a shell command."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    events: list[BaseEvent] = Field(default_factory=list)


class ScriptExecutionRequest(BaseModel):
    """Internal request for shell-command execution with session context."""

    code: StrictStr
    session_id: StrictStr
    timeout: StrictInt = 30
    episode_id: StrictStr | None = None


class BenchmarkToolRequest(BaseModel):
    """Request to run a benchmark tool (simulate, validate, etc.)."""

    script_path: StrictStr = Field(
        default="script.py",
        description=(
            "Path to the authored script. The runtime expects a build() "
            "function in benchmark_script.py or solution_script.py."
        ),
    )
    script_content: StrictStr | None = Field(
        default=None,
        description="Direct content of the script.",
    )
    bundle_base64: str | None = Field(
        default=None,
        description="Gzipped tarball of the session workspace (base64 encoded).",
    )
    backend: SimulatorBackendType = Field(
        default_factory=get_default_simulator_backend,
        description="Physics backend to use.",
    )
    smoke_test_mode: bool | None = Field(
        default=None,
        description="If true: cap particles to 5000, label results as approximate.",
    )
    stream_render_frames: bool = Field(
        default=False,
        description="If true, stream low-frequency simulation frames to the episode websocket.",
    )
    particle_budget: int | None = Field(
        default=None,
        description="Optional particle budget override.",
    )
    reviewer_stage: AgentName | None = Field(
        default=None,
        description="Reviewer stage when calling the benchmark or engineering submit route.",
    )
    episode_id: StrictStr | None = None

    @field_validator("backend", mode="before")
    @classmethod
    def normalize_backend(cls, value: object) -> object:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("reviewer_stage", mode="before")
    @classmethod
    def normalize_reviewer_stage(cls, value: object) -> object:
        if isinstance(value, str):
            stage = LEGACY_REVIEWER_STAGE_ALIASES.get(value, value)
            return AgentName(stage)
        return value


class AnalyzeRequest(BenchmarkToolRequest):
    """Request to run manufacturing analysis."""

    method: ManufacturingMethod = Field(
        ...,
        description="Manufacturing method to analyze (cnc, 3dp, im).",
    )
    quantity: StrictInt = Field(
        default=1,
        ge=1,
        description="Number of units to manufacture for pricing.",
    )


class VerificationRequest(BenchmarkToolRequest):
    """Request to run batched runtime-randomization verification."""

    jitter_range: tuple[float, float, float] = Field(
        default=(0.002, 0.002, 0.001),
        description="(x, y, z) position jitter range in meters.",
    )
    num_scenes: int = Field(
        default=5,
        ge=1,
        description="Number of parallel jittered scene instances in one backend run.",
    )
    duration: float = Field(default=10.0, ge=0.1, description="Duration per run.")
    seed: int = Field(default=42, description="Random seed.")


class SimulationArtifacts(BaseModel):
    """Structured artifacts from a simulation run."""

    render_paths: list[StrictStr] = Field(default_factory=list)
    render_blobs_base64: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    object_store_keys: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    mjcf_content: StrictStr | None = None
    scene_path: StrictStr | None = None
    failure: SimulationFailure | None = None
    verification_result: MultiRunResult | None = None
    total_cost: float | None = None
    total_weight_g: float | None = None
    validation_results_json: StrictStr | None = None
    simulation_result_json: StrictStr | None = None
    review_manifest_json: StrictStr | None = None
    review_manifests_json: dict[StrictStr, StrictStr] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class SimulationFrameStreamMessage(BaseModel):
    """Frame payload streamed live from worker-heavy during simulation."""

    type: Literal["simulation_frame"] = "simulation_frame"
    episode_id: StrictStr
    session_id: StrictStr
    frame_index: StrictInt = Field(ge=0)
    simulation_time_s: float = Field(ge=0.0)
    capture_interval_seconds: float = Field(gt=0.0)
    backend_type: SimulatorBackendType
    backend_name: StrictStr
    resolved_camera_name: StrictStr | None = None
    used_default_view: StrictBool = False
    resolved_default_view_label: StrictStr | None = None
    content_type: StrictStr = "image/png"
    image_bytes_base64: StrictStr


class BenchmarkToolResponse(BaseModel):
    """Response from a benchmark tool."""

    success: bool
    message: str
    confidence: SimulationConfidence = SimulationConfidence.HIGH
    artifacts: SimulationArtifacts | None = None
    events: list[BaseEvent] = Field(default_factory=list)


class ValidationResultRecord(BaseModel):
    """Persisted validation gate result for submission handoff checks."""

    success: bool
    message: str | None = None
    timestamp: float
    script_path: StrictStr | None = None
    script_sha256: StrictStr | None = None
    verification_result: MultiRunResult | None = None

    model_config = {"extra": "forbid"}


class ReviewManifest(BaseModel):
    """Persisted handoff manifest used to gate reviewer entry."""

    status: Literal["ready_for_review"]
    reviewer_stage: AgentName
    timestamp: str | None = None
    session_id: StrictStr
    revision: StrictStr | None = None
    episode_id: StrictStr | None = None
    worker_session_id: StrictStr | None = None
    benchmark_episode_id: StrictStr | None = None
    benchmark_worker_session_id: StrictStr | None = None
    benchmark_revision: StrictStr | None = None
    solution_revision: StrictStr | None = None
    environment_version: StrictStr | None = None
    preview_evidence_paths: list[StrictStr] = Field(default_factory=list)
    script_path: StrictStr
    script_sha256: StrictStr
    validation_success: bool
    validation_timestamp: float
    simulation_success: bool
    simulation_summary: StrictStr
    simulation_timestamp: float
    motion_evidence_verified: bool | None = None
    goal_reached: bool | None = None
    renders: list[StrictStr] = Field(default_factory=list)
    mjcf_path: StrictStr | None = None
    cad_path: StrictStr | None = None
    objectives_path: StrictStr | None = None
    assembly_definition_path: StrictStr | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("reviewer_stage", mode="before")
    @classmethod
    def normalize_reviewer_stage(cls, value: object) -> object:
        if isinstance(value, str):
            stage = LEGACY_REVIEWER_STAGE_ALIASES.get(value, value)
            return AgentName(stage)
        return value


class PlanReviewManifest(BaseModel):
    """Planner handoff manifest used to gate engineering plan reviewer entry."""

    status: Literal["ready_for_review"]
    reviewer_stage: Literal[
        AgentName.BENCHMARK_PLAN_REVIEWER,
        AgentName.ENGINEER_PLAN_REVIEWER,
    ]
    session_id: StrictStr
    planner_node_type: AgentName
    episode_id: StrictStr | None = None
    worker_session_id: StrictStr | None = None
    benchmark_revision: StrictStr | None = None
    environment_version: StrictStr | None = None
    artifact_hashes: dict[StrictStr, StrictStr]

    model_config = ConfigDict(extra="forbid")


class CurrentRoleManifest(BaseModel):
    """Backend-owned marker for the role actively running the workspace."""

    agent_name: AgentName

    model_config = ConfigDict(extra="forbid")


class BugReportArchiveManifest(BaseModel):
    """System-owned manifest for an archived bug report."""

    archived_at: StrictStr
    agent_name: AgentName
    session_id: StrictStr | None = None
    episode_id: StrictStr | None = None
    workspace_dir: StrictStr
    source_path: StrictStr
    archive_root: StrictStr
    archive_dir: StrictStr
    archived_report_path: StrictStr
    source_sha256: StrictStr | None = None
    bug_report_size_bytes: StrictInt | None = None

    model_config = ConfigDict(extra="forbid")


class GitCommitRequest(BaseModel):
    """Request to commit changes in the session workspace."""

    message: StrictStr = Field(..., min_length=1)


class GitCommitResponse(BaseModel):
    """Response from a git commit operation."""

    success: StrictBool
    commit_hash: StrictStr | None = None
    message: StrictStr


class GitStatusResponse(BaseModel):
    """Response from git status."""

    branch: StrictStr
    is_dirty: StrictBool
    is_merging: StrictBool
    conflicts: list[StrictStr] = Field(default_factory=list)
    error: StrictStr | None = None


class GitResolveRequest(BaseModel):
    """Request to resolve a merge conflict."""

    file_path: StrictStr = Field(..., min_length=1)
    strategy: Literal["ours", "theirs"]


class GitMergeRequest(BaseModel):
    """Request to complete a merge."""

    message: StrictStr | None = None


WorkerLightRpcAction: TypeAlias = Literal[
    "fs_ls",
    "fs_exists",
    "fs_read",
    "fs_read_blob",
    "fs_read_files",
    "fs_write",
    "fs_upload_files",
    "fs_upload_files_object_store",
    "fs_edit",
    "fs_upload_file",
    "fs_delete",
    "fs_grep",
    "fs_bundle",
    "git_init",
    "git_commit",
    "git_status",
    "git_resolve",
    "git_merge_abort",
    "git_merge_complete",
    "runtime_execute",
    "topology_inspect",
]


class WorkerLightRpcRequest(BaseModel):
    """Typed request envelope for the worker-light websocket RPC transport."""

    request_id: StrictStr
    action: WorkerLightRpcAction
    payload: dict[StrictStr, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class WorkerLightRpcError(BaseModel):
    """Structured error payload returned by worker-light websocket RPC."""

    message: StrictStr
    status_code: StrictInt | None = None
    error_type: StrictStr | None = None

    model_config = ConfigDict(extra="forbid")


class WorkerLightRpcResponse(BaseModel):
    """Typed response envelope for the worker-light websocket RPC transport."""

    request_id: StrictStr
    ok: StrictBool
    result: Any | None = None
    error: WorkerLightRpcError | None = None

    model_config = ConfigDict(extra="forbid")


class PreviewDesignRequest(BaseModel):
    """Request to preview a CAD design from specific angles."""

    script_path: StrictStr = Field(
        default="script.py",
        description=(
            "Path to the authored script. The runtime expects a build() "
            "function in benchmark_script.py or solution_script.py."
        ),
    )
    script_content: StrictStr | None = Field(
        default=None,
        description="Direct content of the script.",
    )
    agent_role: StrictStr | None = Field(
        default=None,
        description="Optional workflow role used to route preview artifacts.",
    )
    bundle_base64: str | None = Field(
        default=None,
        description="Gzipped tarball of the session workspace (base64 encoded).",
    )
    orbit_pitch: float | list[float] = Field(
        default=45.0,
        description=(
            "Camera elevation angle in degrees (negative = looking down). "
            "Scalar inputs are normalized to single-item view lists."
        ),
        validation_alias=AliasChoices("pitch", "orbit_pitch"),
    )
    orbit_yaw: float | list[float] = Field(
        default=45.0,
        description=(
            "Camera azimuth angle in degrees (clockwise from front). "
            "Scalar inputs are normalized to single-item view lists."
        ),
        validation_alias=AliasChoices("yaw", "orbit_yaw"),
    )
    rgb: bool | None = Field(default=None, description="Request RGB output.")
    depth: bool | None = Field(default=None, description="Request depth output.")
    segmentation: bool | None = Field(
        default=None, description="Request segmentation output."
    )
    payload_path: bool = Field(
        default=False,
        description=(
            "Request the optional payload-path overlay on persistent handoff "
            "bundles and scratch previews."
        ),
    )
    rendering_type: PreviewRenderingType | None = Field(
        default=None,
        description=(
            "Legacy single-modality preview selector. When explicit modality "
            "booleans are omitted, this maps to a single requested modality."
        ),
    )
    smoke_test_mode: bool | None = Field(
        default=None,
        description="If true: cap particles to 5000, label results as approximate.",
    )

    @model_validator(mode="after")
    def normalize_preview_request(self) -> "PreviewDesignRequest":
        explicit_modalities = any(
            getattr(self, field) is not None
            for field in ("rgb", "depth", "segmentation")
        )
        if not explicit_modalities and self.rendering_type is not None:
            self.rgb = self.rendering_type == PreviewRenderingType.RGB
            self.depth = self.rendering_type == PreviewRenderingType.DEPTH
            self.segmentation = self.rendering_type == PreviewRenderingType.SEGMENTATION
        else:
            self.rgb = bool(self.rgb) if self.rgb is not None else True
            self.depth = bool(self.depth) if self.depth is not None else True
            self.segmentation = (
                bool(self.segmentation) if self.segmentation is not None else False
            )
        if not any((self.rgb, self.depth, self.segmentation)):
            raise ValueError("at least one preview modality must be enabled")
        return self

    @field_validator("smoke_test_mode", mode="after")
    @classmethod
    def validate_smoke_test_mode(cls, value: bool | None) -> bool | None:
        return ensure_smoke_test_mode_allowed(value)

    @field_validator("orbit_pitch", "orbit_yaw", mode="after")
    @classmethod
    def validate_preview_camera_range(
        cls, value: float | list[float], info
    ) -> float | list[float]:
        return _validate_preview_camera_value(value, field_name=str(info.field_name))


class PreviewDesignResponse(BaseModel):
    """Response from preview design endpoint."""

    success: StrictBool
    status_text: StrictStr
    message: StrictStr | None = None
    job_id: StrictStr | None = None
    queued: StrictBool = False
    view_count: StrictInt | None = None
    view_specs: list[PreviewViewSpec] = Field(default_factory=list)
    artifact_path: StrictStr | None = None
    manifest_path: StrictStr | None = None
    rendering_type: PreviewRenderingType = PreviewRenderingType.RGB
    pitch: float | None = None
    yaw: float | None = None
    image_path: StrictStr | None = None
    image_bytes_base64: StrictStr | None = Field(
        default=None,
        description=(
            "Base64-encoded preview image payload used internally by worker "
            "delegation layers."
        ),
    )
    render_blobs_base64: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    object_store_keys: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    render_manifest_json: StrictStr | None = None
    events: list[BaseEvent] = Field(default_factory=list)


class PreviewWorkflowParams(BaseModel):
    """Parameters for the controller preview workflow."""

    bundle_base64: StrictStr
    script_path: StrictStr = Field(default="script.py")
    script_content: StrictStr | None = None
    orbit_pitch: float | list[float] = Field(
        default=45.0,
        validation_alias=AliasChoices("pitch", "orbit_pitch"),
    )
    orbit_yaw: float | list[float] = Field(
        default=45.0,
        validation_alias=AliasChoices("yaw", "orbit_yaw"),
    )
    rgb: bool | None = None
    depth: bool | None = None
    segmentation: bool | None = None
    payload_path: bool = False
    rendering_type: PreviewRenderingType | None = Field(
        default=None,
        description="Legacy single-modality preview selector.",
    )
    smoke_test_mode: bool | None = None
    session_id: StrictStr
    agent_role: StrictStr


class HeavySimulationParams(BaseModel):
    """Parameters for worker_run_simulation activity."""

    bundle_base64: StrictStr
    script_path: str
    backend: SimulatorBackendType
    smoke_test_mode: bool | None = None
    session_id: str
    episode_id: str | None = None
    stream_render_frames: bool = False


class HeavyVerifyParams(VerificationRequest):
    """Parameters for worker_verify_design activity."""

    session_id: str


class HeavyPreviewParams(BaseModel):
    """Parameters for worker_preview_design activity."""

    bundle_base64: StrictStr
    script_path: str
    orbit_pitch: float | list[float] = Field(
        default=45.0,
        validation_alias=AliasChoices("pitch", "orbit_pitch"),
    )
    orbit_yaw: float | list[float] = Field(
        default=45.0,
        validation_alias=AliasChoices("yaw", "orbit_yaw"),
    )
    rgb: bool | None = None
    depth: bool | None = None
    segmentation: bool | None = None
    payload_path: bool = False
    rendering_type: PreviewRenderingType | None = None

    @field_validator("orbit_pitch", "orbit_yaw", mode="after")
    @classmethod
    def validate_preview_camera_range(
        cls, value: float | list[float], info
    ) -> float | list[float]:
        return _validate_preview_camera_value(value, field_name=str(info.field_name))


class SimulationVideoRequest(BaseModel):
    """Request to encode simulation frames into a video artifact."""

    bundle_base64: StrictStr
    frame_paths: list[StrictStr] = Field(default_factory=list)
    output_name: StrictStr = "simulation.mp4"
    fps: StrictInt = Field(default=30, ge=1, le=240)
    session_id: StrictStr | None = None


class HeavySubmitParams(BaseModel):
    """Parameters for worker_submit_for_review activity."""

    bundle_base64: StrictStr
    script_path: str
    reviewer_stage: AgentName
    session_id: str
    episode_id: str | None = None


class HeavyPreviewResponse(BaseModel):
    """Response from worker_preview_design activity."""

    success: bool
    image_bytes: bytes | None = None
    image_path: str | None = None
    filename: str | None = None


class LintRequest(BaseModel):
    """Request to lint Python code."""

    path: StrictStr | None = Field(
        default=None,
        description="Path to file to lint (if in filesystem).",
    )
    content: StrictStr | None = Field(
        default=None,
        description="Direct content to lint.",
    )


class LintResponse(BaseModel):
    """Response from linting Python code."""

    success: StrictBool
    errors: list[dict[StrictStr, Any]] = Field(default_factory=list)
    warnings: list[dict[StrictStr, Any]] = Field(default_factory=list)


class InspectTopologyRequest(BaseModel):
    """Request to inspect topological features."""

    target_id: StrictStr = Field(..., description="Target ID (e.g. face_0, part_1).")
    script_path: StrictStr = Field(
        default="script.py",
        description="Path to the authored build script.",
    )


class InspectTopologyResponse(BaseModel):
    """Response from topology inspection."""

    success: StrictBool
    properties: dict[StrictStr, Any] | None = None
    message: StrictStr | None = None


class RenderSiblingPaths(BaseModel):
    """Sibling render artifact paths for a single camera/view group."""

    rgb: StrictStr | None = None
    depth: StrictStr | None = None
    segmentation: StrictStr | None = None
    svg: StrictStr | None = None
    dxf: StrictStr | None = None

    model_config = ConfigDict(extra="forbid")


class SegmentationLegendEntry(BaseModel):
    """One segmentation color entry exposed to media inspection."""

    instance_id: StrictStr
    instance_name: StrictStr
    semantic_label: StrictStr
    object_type: StrictStr
    object_id: StrictInt
    body_name: StrictStr | None = None
    geom_name: StrictStr | None = None
    color_rgb: tuple[int, int, int]
    color_hex: StrictStr


class RenderBundleIdentity(BaseModel):
    """Stable identity fields for one published render bundle."""

    bundle_id: StrictStr | None = None
    created_at: StrictStr | None = None
    revision: StrictStr | None = None
    scene_hash: StrictStr | None = None
    bundle_path: StrictStr | None = None

    model_config = ConfigDict(extra="forbid")


class RenderArtifactMetadata(BaseModel):
    """Structured metadata persisted for one render artifact."""

    modality: Literal["rgb", "depth", "segmentation", "unknown"] = "unknown"
    group_key: StrictStr | None = None
    view_index: StrictInt | None = None
    orbit_pitch: float | None = None
    orbit_yaw: float | None = None
    siblings: RenderSiblingPaths = Field(default_factory=RenderSiblingPaths)
    depth_min_m: float | None = None
    depth_max_m: float | None = None
    depth_interpretation: StrictStr | None = None
    segmentation_legend: list[SegmentationLegendEntry] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RenderManifest(BaseModel):
    """Manifest persisted alongside rendered artifacts under renders/."""

    version: StrictStr = "1.0"
    bundle_id: StrictStr | None = None
    created_at: StrictStr | None = None
    episode_id: StrictStr | None = None
    worker_session_id: StrictStr | None = None
    revision: StrictStr | None = None
    scene_hash: StrictStr | None = None
    bundle_path: StrictStr | None = None
    environment_version: StrictStr | None = None
    source_script_sha256: StrictStr | None = None
    preview_evidence_paths: list[StrictStr] = Field(default_factory=list)
    artifacts: dict[StrictStr, RenderArtifactMetadata] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class RenderBundleIndexEntry(RenderBundleIdentity):
    """Append-only discovery row for one published render bundle."""

    manifest_path: StrictStr
    preview_evidence_paths: list[StrictStr] = Field(default_factory=list)
    primary_media_paths: list[StrictStr] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class RenderFrameMetadata(BaseModel):
    """Sparse frame metadata for a published video bundle."""

    frame_index: StrictInt = Field(ge=0)
    source_path: StrictStr
    timestamp_s: float | None = None

    model_config = ConfigDict(extra="forbid")


class RenderBundleObjectPoseRecord(BaseModel):
    """Compact object pose row for query helpers.

    Orientation is stored as XYZ Euler degrees in bundle space.
    """

    frame_index: StrictInt | None = None
    object_id: StrictInt | None = None
    object_type: StrictStr | None = None
    label: StrictStr | None = None
    instance_id: StrictStr | None = None
    instance_name: StrictStr | None = None
    semantic_label: StrictStr | None = None
    body_name: StrictStr | None = None
    geom_name: StrictStr | None = None
    position: tuple[float, float, float] | None = None
    orientation: tuple[float, float, float] | None = None
    source_path: StrictStr | None = None

    model_config = ConfigDict(extra="forbid")


class RenderBundleObjectIdentity(BaseModel):
    """Identity fields returned by point-pick queries."""

    object_type: StrictStr | None = None
    object_id: StrictInt | None = None
    label: StrictStr | None = None
    instance_id: StrictStr | None = None
    instance_name: StrictStr | None = None
    semantic_label: StrictStr | None = None
    body_name: StrictStr | None = None
    geom_name: StrictStr | None = None

    model_config = ConfigDict(extra="forbid")


class RenderBundlePointPickRequest(BaseModel):
    """Request for a single point-pick query against one render bundle."""

    bundle_path: StrictStr
    pixel_x: StrictInt = Field(ge=0)
    pixel_y: StrictInt = Field(ge=0)
    image_width: StrictInt = Field(gt=0)
    image_height: StrictInt = Field(gt=0)
    orbit_pitch: float = 45.0
    orbit_yaw: float = 45.0
    view_index: StrictInt = Field(default=0, ge=0)
    bundle_id: StrictStr | None = None
    manifest_path: StrictStr | None = None
    rendering_type: PreviewRenderingType | None = None

    model_config = ConfigDict(extra="forbid")


class RenderBundlePointPickResult(BaseModel):
    """World-space hit record returned by point-pick queries."""

    bundle_id: StrictStr | None = None
    bundle_path: StrictStr
    revision: StrictStr | None = None
    scene_hash: StrictStr | None = None
    manifest_path: StrictStr | None = None
    view_index: StrictInt = Field(ge=0)
    pixel_x: StrictInt = Field(ge=0)
    pixel_y: StrictInt = Field(ge=0)
    image_width: StrictInt = Field(gt=0)
    image_height: StrictInt = Field(gt=0)
    orbit_pitch: float
    orbit_yaw: float
    ray_origin: tuple[float, float, float]
    ray_direction: tuple[float, float, float]
    hit: StrictBool
    distance: float | None = None
    world_point: tuple[float, float, float] | None = None
    object_identity: RenderBundleObjectIdentity | None = None

    model_config = ConfigDict(extra="forbid")


class RenderBundleQueryRequest(BaseModel):
    """Request for a compact render-bundle metadata query."""

    bundle_path: StrictStr
    manifest_path: StrictStr | None = None
    bundle_id: StrictStr | None = None
    limit: StrictInt | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid")


class RenderBundleQueryResult(BaseModel):
    """Compact bundle-level query response."""

    bundle_id: StrictStr | None = None
    bundle_path: StrictStr
    revision: StrictStr | None = None
    scene_hash: StrictStr | None = None
    manifest_path: StrictStr | None = None
    preview_evidence_paths: list[StrictStr] = Field(default_factory=list)
    frames: list[RenderFrameMetadata] = Field(default_factory=list)
    objects: list[RenderBundleObjectPoseRecord] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class MediaInspectionResult(BaseModel):
    """Structured result for agent-facing visual media inspection."""

    path: StrictStr
    mime_type: StrictStr
    media_kind: Literal["image", "video", "video_frames", "unsupported"]
    attached_to_model: bool = False
    attached_media_count: StrictInt = Field(default=0, ge=0)
    size_bytes: StrictInt = Field(ge=0)
    note: StrictStr
    render_metadata: RenderArtifactMetadata | None = None
    data_url: StrictStr | None = Field(default=None, exclude=True, repr=False)
    data_urls: list[StrictStr] = Field(default_factory=list, exclude=True, repr=False)


class PlanRefusal(BaseModel):
    """Information about a refused plan."""

    status: str = "plan_refused"
    reason: str
    timestamp: str | None = None
    session_id: str = "default"


ReviewManifest.model_rebuild()
