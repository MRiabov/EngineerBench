"""
Pydantic schemas for structured data validation across the Problemologist system.

These models define the contracts for:
- benchmark_definition.yaml: Central benchmark exchange object between agents
- Review frontmatter: YAML frontmatter for reviewer decisions
"""

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from shared.enums import (
    AgentName,
    AssetType,
    BenchmarkRefusalReason,
    DatasetCurationReasonCode,
    EntryFailureDisposition,
    EpisodePhase,
    EpisodeType,
    FailureClass,
    GenerationKind,
    ManufacturingMethod,
    MechanicalRefusalReason,
    ReviewDecision,
    SeedMatchMethod,
    TerminalReason,
)
from shared.simulation.schemas import (
    CustomObjectives,
    SimulatorBackendType,
    get_default_simulator_backend,
)

# =============================================================================
# Common Types
# =============================================================================


def _coerce_to_tuple(v: Any) -> Any:
    """Validator to coerce lists to tuples for consistent hashing and immutability."""
    if isinstance(v, list):
        return tuple(v)
    return v


def _normalize_material_id_text(value: Any) -> Any:
    """Normalize external material identifiers to the internal underscore form."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("material_id must be a non-empty string")
        return text.replace("-", "_")
    return value


CoercedTuple3D = Annotated[
    tuple[float, float, float], BeforeValidator(_coerce_to_tuple)
]
CoercedTuple2D = Annotated[tuple[float, float], BeforeValidator(_coerce_to_tuple)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
MinimumRotationToleranceFloat = Annotated[float, Field(ge=0.1)]
MaterialId = Annotated[str, BeforeValidator(_normalize_material_id_text)]
OptionalMaterialId = Annotated[str, BeforeValidator(_normalize_material_id_text)] | None


class StrictContractModel(BaseModel):
    """Strict contract model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


class CodeReference(BaseModel):
    """Reference to a specific line range in a file."""

    file_path: str
    start_line: int
    end_line: int


class BoundingBox(StrictContractModel):
    """Axis-aligned bounding box with min/max coordinates."""

    min: CoercedTuple3D
    max: CoercedTuple3D


# =============================================================================
# benchmark_definition.yaml Schema
# =============================================================================


class ForbidZone(StrictContractModel):
    """A zone that the payload must not enter."""

    name: str
    min: CoercedTuple3D
    max: CoercedTuple3D


class ObjectivesSection(StrictContractModel):
    """The objective section of benchmark_definition.yaml."""

    goal_zone: BoundingBox
    forbid_zones: list[ForbidZone] = []
    build_zone: BoundingBox


class StaticRandomization(StrictContractModel):
    """Per-benchmark-run randomization of object properties."""

    radius: CoercedTuple2D | None = None


class Payload(StrictContractModel):
    """The payload that must be guided to the goal zone."""

    label: str
    shape: str
    material_id: MaterialId
    static_randomization: StaticRandomization = StaticRandomization()
    start_position: CoercedTuple3D
    runtime_jitter: CoercedTuple3D

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        label = value.strip()
        if not label:
            raise ValueError("label must be a non-empty string")
        return label

    @field_validator("material_id")
    @classmethod
    def validate_material_id(cls, value: str) -> str:
        material = value.strip()
        if not material:
            raise ValueError("material_id must be a non-empty string")
        return material


class PayloadPart(StrictContractModel):
    """A part name referenced by a coarse payload trajectory."""

    part_name: str

    @field_validator("part_name")
    @classmethod
    def validate_part_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("part_name must be a non-empty string")
        return text


class PayloadTrajectoryContact(StrictContractModel):
    """One expected first-touch surface in the coarse payload trajectory."""

    order: int = Field(ge=1)
    surface: str
    first_touch_window_s: CoercedTuple2D | None = None

    @field_validator("surface")
    @classmethod
    def validate_non_empty_surface(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("surface must be a non-empty string")
        return text

    @model_validator(mode="after")
    def validate_contact_window(self) -> "PayloadTrajectoryContact":
        if self.first_touch_window_s is not None and (
            self.first_touch_window_s[0] > self.first_touch_window_s[1]
        ):
            raise ValueError("first_touch_window_s must be ordered as [start_s, end_s]")
        return self


class PayloadTrajectoryAnchor(StrictContractModel):
    """One coarse payload-trajectory anchor in world coordinates."""

    t_s: float = Field(ge=0)
    reference_point: str
    pos_mm: CoercedTuple3D
    rot_deg: CoercedTuple3D
    position_tolerance_mm: Annotated[
        tuple[NonNegativeFloat, NonNegativeFloat, NonNegativeFloat],
        BeforeValidator(_coerce_to_tuple),
    ]
    rotation_tolerance_deg: (
        Annotated[
            tuple[
                MinimumRotationToleranceFloat,
                MinimumRotationToleranceFloat,
                MinimumRotationToleranceFloat,
            ],
            BeforeValidator(_coerce_to_tuple),
        ]
        | None
    ) = None
    first_contacts: list[PayloadTrajectoryContact] = Field(default_factory=list)
    build_zone_valid: bool = False
    goal_zone_contact: bool = False
    goal_zone_entry: bool = False

    @field_validator("reference_point")
    @classmethod
    def validate_reference_point(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("reference_point must be a non-empty string")
        return text

    @model_validator(mode="after")
    def validate_anchor_contract(self) -> "PayloadTrajectoryAnchor":
        if self.first_contacts:
            orders = [contact.order for contact in self.first_contacts]
            if len(set(orders)) != len(orders):
                raise ValueError("first_contacts must not repeat order values")
            if orders != sorted(orders):
                raise ValueError("first_contacts must be sorted by order")
            if orders[0] != 1:
                raise ValueError("first_contacts must start at order 1")

        if self.goal_zone_contact and self.goal_zone_entry:
            raise ValueError(
                "goal_zone_contact and goal_zone_entry are mutually exclusive"
            )

        return self


class PayloadTrajectoryTerminalEvent(StrictContractModel):
    """Equivalent structured terminal proof for a coarse payload trajectory."""

    kind: Literal["goal_zone_entry", "goal_zone_contact"]
    t_s: float = Field(ge=0)
    reference_point: str
    pos_mm: CoercedTuple3D
    contact_surfaces: list[str] = Field(default_factory=list)
    zone_name: str = "goal_zone"

    @field_validator("reference_point", "zone_name")
    @classmethod
    def validate_non_empty_strings(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be a non-empty string")
        return text

    @field_validator("contact_surfaces")
    @classmethod
    def validate_contact_surfaces(cls, value: list[str]) -> list[str]:
        cleaned = [surface.strip() for surface in value if str(surface).strip()]
        if not cleaned:
            raise ValueError("contact_surfaces must contain at least one surface")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("contact_surfaces must not repeat surface names")
        return cleaned


class CoarsePayloadTrajectory(StrictContractModel):
    """Sparse planner-authored coarse payload trajectory contract."""

    payload_part_names: list[str] = Field(
        default_factory=list,
    )
    reference_frame: Literal["world"] = "world"
    sample_stride_s: float = Field(gt=0)
    anchors: list[PayloadTrajectoryAnchor] = Field(default_factory=list)
    terminal_event: PayloadTrajectoryTerminalEvent | None = None

    @field_validator("payload_part_names")
    @classmethod
    def validate_payload_part_names(cls, value: list[str]) -> list[str]:
        cleaned = [part_name.strip() for part_name in value if str(part_name).strip()]
        if not cleaned:
            raise ValueError(
                "coarse_payload_trajectory must name at least one payload part"
            )
        if len(set(cleaned)) != len(cleaned):
            raise ValueError(
                "coarse_payload_trajectory must not repeat payload part names"
            )
        return cleaned

    @model_validator(mode="after")
    def validate_contract(self) -> "CoarsePayloadTrajectory":
        if self.reference_frame != "world":
            raise ValueError("coarse_payload_trajectory.reference_frame must be world")

        if len(self.anchors) < 2:
            raise ValueError(
                "coarse_payload_trajectory must contain at least two anchors"
            )

        times = [anchor.t_s for anchor in self.anchors]
        if times != sorted(times):
            raise ValueError("coarse_payload_trajectory anchors must be ordered by t_s")
        if len(set(times)) != len(times):
            raise ValueError(
                "coarse_payload_trajectory anchors must not repeat t_s values"
            )

        first_anchor = self.anchors[0]
        last_anchor = self.anchors[-1]
        if not first_anchor.build_zone_valid:
            raise ValueError(
                "coarse_payload_trajectory first anchor must explicitly set "
                "build_zone_valid=true"
            )

        for anchor in self.anchors[:-1]:
            if anchor.goal_zone_contact or anchor.goal_zone_entry:
                raise ValueError(
                    "only the terminal coarse payload anchor may assert goal-zone "
                    "entry/contact"
                )

        terminal_assertion_count = 0
        if last_anchor.goal_zone_contact or last_anchor.goal_zone_entry:
            terminal_assertion_count += 1
        if self.terminal_event is not None:
            terminal_assertion_count += 1

        if terminal_assertion_count == 0:
            raise ValueError(
                "coarse_payload_trajectory must prove the terminal goal-zone "
                "entry/contact "
                "in the final anchor or via terminal_event"
            )
        if terminal_assertion_count > 1:
            raise ValueError(
                "coarse_payload_trajectory terminal proof must appear in the final anchor "
                "or terminal_event, not both"
            )

        return self


class PayloadTrajectoryPose(StrictContractModel):
    """Backend-specific initial pose for the engineer-owned payload trajectory."""

    reference_point: str
    pos_mm: CoercedTuple3D
    rot_deg: CoercedTuple3D

    @field_validator("reference_point")
    @classmethod
    def validate_reference_point(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("reference_point must be a non-empty string")
        return text


class PayloadTrajectoryDefinition(StrictContractModel):
    """Engineer-owned higher-resolution path/contact proof."""

    backend: SimulatorBackendType
    payload_part_names: list[str] = Field(
        default_factory=list,
    )
    initial_pose: PayloadTrajectoryPose
    sample_stride_s: float = Field(gt=0)
    anchors: list[PayloadTrajectoryAnchor] = Field(default_factory=list)
    terminal_event: PayloadTrajectoryTerminalEvent | None = None

    @field_validator("payload_part_names")
    @classmethod
    def validate_payload_part_names(cls, value: list[str]) -> list[str]:
        cleaned = [part_name.strip() for part_name in value if str(part_name).strip()]
        if not cleaned:
            raise ValueError(
                "payload_trajectory_definition must name at least one payload part"
            )
        if len(set(cleaned)) != len(cleaned):
            raise ValueError(
                "payload_trajectory_definition must not repeat payload part names"
            )
        return cleaned

    @model_validator(mode="after")
    def validate_contract(self) -> "PayloadTrajectoryDefinition":
        if len(self.anchors) < 1:
            raise ValueError(
                "payload_trajectory_definition must contain at least one anchor"
            )

        first_anchor = self.anchors[0]
        if not first_anchor.build_zone_valid:
            raise ValueError(
                "payload_trajectory_definition first anchor must explicitly set "
                "build_zone_valid=true"
            )

        if (
            self.initial_pose.reference_point != first_anchor.reference_point
            or self.initial_pose.pos_mm != first_anchor.pos_mm
            or self.initial_pose.rot_deg != first_anchor.rot_deg
        ):
            raise ValueError(
                "payload_trajectory_definition initial_pose must match the first "
                "anchor pose and reference_point"
            )

        for anchor in self.anchors[:-1]:
            if anchor.goal_zone_contact or anchor.goal_zone_entry:
                raise ValueError(
                    "payload_trajectory_definition only the terminal payload "
                    "anchor may assert goal-zone entry/contact"
                )

        terminal_assertion_count = 0
        last_anchor = self.anchors[-1]
        if last_anchor.goal_zone_contact or last_anchor.goal_zone_entry:
            terminal_assertion_count += 1
        if self.terminal_event is not None:
            terminal_assertion_count += 1

        if terminal_assertion_count == 0:
            raise ValueError(
                "payload_trajectory_definition must prove the terminal goal-zone "
                "entry/contact in the final anchor or via terminal_event"
            )
        if terminal_assertion_count > 1:
            raise ValueError(
                "payload_trajectory_definition terminal proof must appear in the "
                "final anchor or terminal_event, not both"
            )
        return self


class Constraints(StrictContractModel):
    """Cost and weight constraints for the engineer."""

    estimated_solution_cost_usd: float | None = None
    estimated_solution_weight_g: float | None = None
    max_unit_cost: float | None = None
    max_weight_g: float | None = None
    target_quantity: int | None = None

    @field_validator(
        "estimated_solution_cost_usd",
        "estimated_solution_weight_g",
        "max_unit_cost",
        "max_weight_g",
    )
    @classmethod
    def validate_positive(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value <= 0:
            raise ValueError("must be > 0")
        return value


class RandomizationMeta(StrictContractModel):
    """Metadata about randomization for reproducibility."""

    static_variation_id: str | None = None
    runtime_jitter_enabled: bool = True


# =============================================================================
# Simulation Scene Definition Models (Input)
# =============================================================================


class EntityDefinition(BaseModel):
    name: str
    type: str = "rigid"  # "rigid", "soft_mesh", "zone", etc.
    file: str | None = None
    pos: CoercedTuple3D = (0.0, 0.0, 0.0)
    euler: CoercedTuple3D = (0.0, 0.0, 0.0)
    material_id: MaterialId = "aluminum_6061"
    is_zone: bool = False

    # For zones
    min: CoercedTuple3D | None = None
    max: CoercedTuple3D | None = None
    size: CoercedTuple3D | None = None

    model_config = ConfigDict(extra="allow")


class CableDefinition(BaseModel):
    wire_id: str
    points: list[CoercedTuple3D]
    radius: float = 0.001
    material_id: MaterialId = "copper"

    model_config = ConfigDict(extra="allow")


class SceneDefinition(BaseModel):
    entities: list[EntityDefinition] = Field(default_factory=list)
    cables: list[CableDefinition] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


# =============================================================================
# WP2 Physics Configuration
# =============================================================================


class PhysicsConfig(StrictContractModel):
    """Configuration for the physics engine."""

    backend: SimulatorBackendType = Field(default_factory=get_default_simulator_backend)
    compute_target: str = "auto"  # "auto" | "cpu" | "gpu"


class BenchmarkPartMetadata(StrictContractModel):
    """Benchmark-owned metadata for environment and fixture parts."""

    fixed: bool = False
    material_id: OptionalMaterialId = None


class BenchmarkPartDefinition(StrictContractModel):
    """Metadata declaration for a benchmark-owned part or fixture."""

    part_id: str
    label: str
    metadata: BenchmarkPartMetadata


class BenchmarkDefinition(StrictContractModel):
    """
    The benchmark_definition.yaml schema - central benchmark exchange object.

    This file defines WHAT the engineer must achieve and the benchmark-owned
    environment metadata:
    - Guide the payload into the goal_zone
    - Stay WITHIN the build_zone
    - AVOID all forbid_zones
    - Respect runtime-derived max_unit_cost and max_weight constraints
      (from benchmark-estimated solution cost/weight)
    - Reference benchmark-owned part metadata for fixtures and environment parts
    """

    objectives: ObjectivesSection
    benchmark_parts: list[BenchmarkPartDefinition] = Field(default_factory=list)
    physics: PhysicsConfig = PhysicsConfig()
    simulation_bounds: BoundingBox
    payload: Payload
    constraints: Constraints
    randomization: RandomizationMeta = RandomizationMeta()
    assembly_totals: dict[str, float] | None = None

    @model_validator(mode="after")
    def validate_part_identity_uniqueness(self) -> "BenchmarkDefinition":
        part_ids = [part.part_id for part in self.benchmark_parts]
        labels = [part.label for part in self.benchmark_parts]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("benchmark_parts.part_id values must be unique")
        if len(labels) != len(set(labels)):
            raise ValueError("benchmark_parts.label values must be unique")
        return self


# =============================================================================
# CAD Metadata Models
# =============================================================================


class JointMetadata(BaseModel):
    """Metadata for physical joints attached to parts."""

    type: Literal["hinge", "slide"]
    axis: CoercedTuple3D
    range: CoercedTuple2D | None = None


class PartMetadata(BaseModel):
    """Metadata for individual parts in a CAD assembly."""

    material_id: OptionalMaterialId = None
    is_fixed: bool = Field(default=False, alias="fixed")
    manufacturing_method: ManufacturingMethod | None = None
    joint: JointMetadata | None = None

    model_config = ConfigDict(populate_by_name=True)


class CompoundMetadata(BaseModel):
    """Metadata for compounds (assemblies) in a CAD hierarchy."""

    is_fixed: bool = Field(default=False, alias="fixed")
    joint: JointMetadata | None = None

    model_config = ConfigDict(populate_by_name=True)


# =============================================================================
# Episode & Session Models
# =============================================================================


class EpisodeMetadata(BaseModel):
    """Structured metadata for episodes and benchmark sessions."""

    worker_session_id: str | None = None
    benchmark_id: str | None = None
    benchmark_family: str | None = None
    custom_objectives: CustomObjectives | None = None
    detailed_status: str | None = None  # Using str to avoid circular deps if needed
    episode_phase: EpisodePhase | None = None
    terminal_reason: TerminalReason | None = None
    failure_class: FailureClass | None = None
    error: str | None = None
    variant_id: str | None = None
    seed: int | None = None
    prior_episode_id: str | None = None
    is_optimality_check: bool | None = None
    fidelity_check: bool | None = None
    tolerance: float | None = None
    is_reused: bool | None = None
    episode_type: EpisodeType | None = None
    validation_logs: list[str] = Field(default_factory=list)
    prompt: str | None = None
    plan: dict[str, Any] | None = None
    cost: float | None = None
    weight: float | None = None
    seed_id: str | None = None
    seed_dataset: str | None = None
    seed_match_method: SeedMatchMethod | None = None
    generation_kind: GenerationKind | None = None
    parent_seed_id: str | None = None
    benchmark_family: str | None = None
    is_integration_test: bool | None = None
    integration_test_id: str | None = None
    disable_sidecars: bool | None = None
    additional_info: dict[str, Any] = Field(default_factory=dict)


class TraceMetadata(BaseModel):
    """Structured metadata for individual traces (tool calls, nodes, etc.)."""

    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    observation: str | None = None
    prediction: str | None = None
    error: str | None = None

    # Simulation specific
    simulation_run_id: str | None = None
    backend: SimulatorBackendType | None = None

    # Review specific
    review_id: str | None = None
    decision: ReviewDecision | None = None
    checklist: dict[str, str | float | bool] = Field(default_factory=dict)

    # Reasoning trace specific
    reasoning_step_index: int | None = None
    reasoning_source: str | None = None

    additional_info: dict[str, Any] = Field(default_factory=dict)


class PlannerSubmissionResult(BaseModel):
    """Typed result contract for explicit planner handoff submission."""

    ok: bool
    status: Literal["submitted", "rejected"]
    errors: list[str] = Field(default_factory=list)
    node_type: AgentName


class EntryValidationError(BaseModel):
    """Structured entry-validation error payload persisted in episode metadata."""

    code: str
    message: str
    source: str
    artifact_path: str | None = None


class EntryValidationContext(BaseModel):
    """Structured node-entry validation context persisted in episode metadata."""

    node: AgentName | None = None
    disposition: EntryFailureDisposition | None = None
    reason_code: str | None = None
    reroute_target: AgentName | None = None
    errors: list[EntryValidationError] = Field(default_factory=list)


class ReplayArtifactRecord(StrictContractModel):
    """A persisted artifact included in a replay bundle."""

    path: str
    sha256: str
    size_bytes: int
    asset_type: AssetType | None = None


class ReplayTraceIds(StrictContractModel):
    """Trace ID groups surfaced by the replay surface."""

    simulation_trace_ids: list[int] = Field(default_factory=list)
    review_trace_ids: list[int] = Field(default_factory=list)
    entry_validation_trace_ids: list[int] = Field(default_factory=list)


class ReplayFailureSignal(StrictContractModel):
    """Machine-readable replay diagnostic or failure signal."""

    kind: str
    message: str
    source: str
    artifact_path: str | None = None


class DatasetRowArtifactReference(StrictContractModel):
    """Reference to a persisted artifact included in a dataset row archive."""

    path: str
    family: str
    asset_type: AssetType | None = None
    source_surface: str
    sha256: str
    size_bytes: int | None = None


class DatasetRowBenchmarkAsset(StrictContractModel):
    """Snapshot of the benchmark asset surface used to materialize a dataset row."""

    benchmark_id: str
    mjcf_url: str
    build123d_url: str
    preview_bundle_url: str
    random_variants: list[str] = Field(default_factory=list)
    difficulty_score: float | None = None
    benchmark_metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetRowLineage(StrictContractModel):
    """Joinable lineage fields persisted with a dataset export row."""

    episode_id: str
    benchmark_id: str
    user_session_id: str | None = None
    worker_session_id: str | None = None
    episode_type: EpisodeType
    seed_id: str | None = None
    seed_dataset: str | None = None
    seed_match_method: SeedMatchMethod | None = None
    generation_kind: GenerationKind | None = None
    parent_seed_id: str | None = None
    is_integration_test: bool | None = None
    integration_test_id: str | None = None
    simulation_run_id: str | None = None
    review_id: str | None = None
    revision_hash: str
    artifact_hash: str


class DatasetRowArchiveManifest(StrictContractModel):
    """Strict manifest persisted alongside a dataset-row archive."""

    export_id: str
    created_at: datetime
    lineage: DatasetRowLineage
    source_benchmark_asset: DatasetRowBenchmarkAsset | None = None
    artifact_references: list[DatasetRowArtifactReference] = Field(default_factory=list)
    artifact_families: list[str] = Field(default_factory=list)
    validation_notes: list[str] = Field(default_factory=list)


class DatasetCurationCounts(StrictContractModel):
    """Aggregate counts for a curated dataset manifest."""

    accepted_before_pending_filter: int
    accepted_after_pending_filter: int
    dedup_identity_groups_with_drops: int
    rejected: int


class DatasetCurationRejectedRow(StrictContractModel):
    """A rejected row captured in a dataset curation manifest."""

    source_episode_id: str
    source_seed_id: str | None = None
    seed_dataset: str | None = None
    seed_match_method: SeedMatchMethod | None = None
    generation_kind: GenerationKind | None = None
    parent_seed_id: str | None = None
    source_family: str | None = None
    reasons: list[DatasetCurationReasonCode]

    @field_validator("source_episode_id")
    @classmethod
    def validate_source_episode_id(cls, value: str) -> str:
        episode_id = value.strip()
        if not episode_id:
            raise ValueError("source_episode_id must be a non-empty string")
        return episode_id

    @field_validator("reasons", mode="before")
    @classmethod
    def normalize_reasons(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("reasons must not be empty")

        if isinstance(value, (str, DatasetCurationReasonCode)):
            candidates = [value]
        else:
            candidates = list(value)

        normalized: list[str] = []
        for item in candidates:
            text = str(item).strip()
            if not text:
                raise ValueError("reasons must not contain empty values")
            text = text.splitlines()[0]
            text = text.split(":", 1)[0]
            text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
            if not text:
                raise ValueError("reasons must normalize to non-empty codes")
            normalized.append(text)

        # Preserve the first occurrence of each normalized code while collapsing
        # artifact-specific variants that map to the same machine-readable reason.
        return list(dict.fromkeys(normalized))


class DatasetCurationFamilyCoverage(StrictContractModel):
    """Coverage summary for a family within a curated dataset manifest."""

    accepted: int
    rejected: int
    ordered_source_episode_ids: list[str] = Field(default_factory=list)
    ordered_source_seed_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_coverage(self) -> "DatasetCurationFamilyCoverage":
        if self.accepted < 0 or self.rejected < 0:
            raise ValueError("family coverage counts must be non-negative")
        if len(self.ordered_source_episode_ids) != len(
            set(self.ordered_source_episode_ids)
        ):
            raise ValueError("ordered_source_episode_ids must not contain duplicates")
        if len(self.ordered_source_seed_ids) != len(set(self.ordered_source_seed_ids)):
            raise ValueError("ordered_source_seed_ids must not contain duplicates")
        return self


class DatasetCurationManifest(StrictContractModel):
    """Strict manifest persisted alongside a curated dataset family."""

    agent_target: str
    bucket_counts: dict[str, int] = Field(default_factory=dict)
    counts: DatasetCurationCounts
    dataset_version: str
    dropped_lineage: dict[str, list[str]] = Field(default_factory=dict)
    dry_run: bool = False
    family: str
    generated_at: datetime
    rejected: list[DatasetCurationRejectedRow] = Field(default_factory=list)
    coverage_by_family: dict[str, DatasetCurationFamilyCoverage] = Field(
        default_factory=dict
    )

    @field_validator("bucket_counts", mode="before")
    @classmethod
    def validate_bucket_counts(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("bucket_counts must be a mapping")
        normalized: dict[str, int] = {}
        for key, raw_count in value.items():
            name = str(key).strip()
            if not name:
                raise ValueError("bucket_counts keys must be non-empty")
            count = int(raw_count)
            if count < 0:
                raise ValueError("bucket_counts values must be non-negative")
            normalized[name] = count
        return normalized

    @field_validator("dropped_lineage", mode="before")
    @classmethod
    def validate_dropped_lineage(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("dropped_lineage must be a mapping")
        normalized: dict[str, list[str]] = {}
        for lineage_key, raw_episode_ids in value.items():
            key = str(lineage_key).strip()
            if not key:
                raise ValueError("dropped_lineage keys must be non-empty")
            if not isinstance(raw_episode_ids, list):
                raise ValueError(
                    "dropped_lineage values must be lists of episode identifiers"
                )
            ordered_episode_ids: list[str] = []
            for raw_episode_id in raw_episode_ids:
                episode_id = str(raw_episode_id).strip()
                if not episode_id:
                    raise ValueError(
                        "dropped_lineage episode identifiers must be non-empty"
                    )
                if episode_id not in ordered_episode_ids:
                    ordered_episode_ids.append(episode_id)
            normalized[key] = ordered_episode_ids
        return normalized

    @field_validator("coverage_by_family", mode="before")
    @classmethod
    def validate_coverage_by_family(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("coverage_by_family must be a mapping")
        return value

    @model_validator(mode="after")
    def validate_manifest(self) -> "DatasetCurationManifest":
        if not self.agent_target.strip():
            raise ValueError("agent_target must be a non-empty string")
        if not self.dataset_version.strip():
            raise ValueError("dataset_version must be a non-empty string")
        if not self.family.strip():
            raise ValueError("family must be a non-empty string")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        return self


# =============================================================================
# Review Frontmatter Schema
# =============================================================================


class ReviewResult(StrictContractModel):
    """Structured output for the reviewer."""

    decision: ReviewDecision
    reason: str
    required_fixes: list[str] = Field(default_factory=list)
    checklist: dict[str, str | float | bool] = Field(default_factory=dict)

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.upper()
        return v


class ReviewComments(StrictContractModel):
    """Persisted YAML comments file written alongside a review decision."""

    summary: str
    comments: list[str] = Field(default_factory=list)
    required_fixes: list[str] = Field(default_factory=list)
    checklist: dict[str, str | float | bool] = Field(default_factory=dict)


class ReviewFrontmatter(StrictContractModel):
    """
    YAML frontmatter schema for review documents.

    The decision field controls the agent handover flow:
    - approved: Accept the work, proceed to next stage
    - rejected: Send back for revision with comments
    - confirm_plan_refusal: Confirm CAD agent's refusal of an invalid plan
    - reject_plan_refusal: Override CAD agent's refusal, plan is valid
    """

    decision: ReviewDecision
    comments: list[str] = []
    evidence: dict[str, Any] | None = None

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator("comments", mode="before")
    @classmethod
    def coerce_comments(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("decision")
    @classmethod
    def validate_refusal_decisions(cls, v):
        """Refusal decisions are only valid when CAD agent refused the plan."""
        # Note: Context validation (whether CAD agent actually refused)
        # must be done at the call site, not in the schema
        return v


class PlanRefusalFrontmatter(StrictContractModel):
    """
    YAML frontmatter for plan_refusal.md.
    Refusal logic must be structured, role-specific, and machine-validated.
    """

    reasons: list[MechanicalRefusalReason | BenchmarkRefusalReason]
    role: AgentName

    @model_validator(mode="after")
    def validate_role_reasons(self) -> "PlanRefusalFrontmatter":
        """Validate that reasons match the role."""
        if self.role == AgentName.ENGINEER_CODER:
            if not all(
                isinstance(r, MechanicalRefusalReason)
                or str(r) in MechanicalRefusalReason.__members__
                for r in self.reasons
            ):
                raise ValueError(f"Invalid reasons for {self.role}")
        elif self.role == AgentName.BENCHMARK_CODER and not all(
            isinstance(r, BenchmarkRefusalReason)
            or str(r) in BenchmarkRefusalReason.__members__
            for r in self.reasons
        ):
            raise ValueError(f"Invalid reasons for {self.role}")
        return self


# =============================================================================
# assembly_definition.yaml Schema
# =============================================================================


class ManufacturedPartEstimate(StrictContractModel):
    """Assembly estimate for a manufactured part."""

    part_name: str
    part_id: str
    manufacturing_method: ManufacturingMethod
    material_id: MaterialId

    @field_validator("manufacturing_method", mode="before")
    @classmethod
    def normalize_method(cls, v: Any) -> Any:
        if isinstance(v, str):
            v_lower = v.lower()
            if v_lower in ["3d_printing", "3dprinting", "3dp"]:
                return ManufacturingMethod.THREE_DP
            if v_lower in ["injection_molding", "im"]:
                return ManufacturingMethod.INJECTION_MOLDING
            # Try to match enum values
            for m in ManufacturingMethod:
                if v_lower == m.value:
                    return m
        return v

    quantity: int
    part_volume_mm3: float
    wall_thickness_mm: float | None = None
    cooling_time_s_estimate: float | None = None
    stock_bbox_mm: dict[str, float]  # {x: float, y: float, z: float}
    stock_volume_mm3: float
    removed_volume_mm3: float
    estimated_unit_cost_usd: float
    pricing_notes: str | None = None
    dfm_suggestions: list[str] = Field(default_factory=list)

    @field_validator("part_name", "part_id")
    @classmethod
    def validate_non_empty_strings(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must be a non-empty string")
        return text


class AssemblyPartConfig(StrictContractModel):
    """Reserved per-part configuration container."""


class PartConfig(StrictContractModel):
    """Configuration for a part in an assembly."""

    name: str
    config: AssemblyPartConfig | None = None


class JointEstimate(StrictContractModel):
    """Estimate for a joint in the assembly."""

    joint_id: str
    parts: list[str]
    type: str


class SubassemblyEstimate(StrictContractModel):
    """Estimate for a subassembly within the final assembly."""

    subassembly_id: str
    parts: list[PartConfig]
    joints: list[JointEstimate] = []


class CostTotals(StrictContractModel):
    """Total estimation for the design."""

    estimated_unit_cost_usd: float
    estimated_weight_g: float
    estimate_confidence: Literal["low", "medium", "high"]


class AssemblyUnits(StrictContractModel):
    """Units used in the estimation file."""

    length: str = "mm"
    volume: str = "mm3"
    mass: str = "g"
    currency: str = "USD"


class AssemblyConstraints(StrictContractModel):
    """Planner target caps plus optional copied benchmark caps for legacy files."""

    benchmark_max_unit_cost_usd: float | None = None
    benchmark_max_weight_g: float | None = None
    planner_target_max_unit_cost_usd: float
    planner_target_max_weight_g: float

    @model_validator(mode="after")
    def validate_contract(self) -> "AssemblyConstraints":
        benchmark_caps_present = (
            self.benchmark_max_unit_cost_usd is not None
            or self.benchmark_max_weight_g is not None
        )
        if benchmark_caps_present and (
            self.benchmark_max_unit_cost_usd is None
            or self.benchmark_max_weight_g is None
        ):
            raise ValueError(
                "benchmark_max_unit_cost_usd and benchmark_max_weight_g must be "
                "provided together when copied benchmark caps are present"
            )

        for field_name, value in (
            ("benchmark_max_unit_cost_usd", self.benchmark_max_unit_cost_usd),
            ("benchmark_max_weight_g", self.benchmark_max_weight_g),
            (
                "planner_target_max_unit_cost_usd",
                self.planner_target_max_unit_cost_usd,
            ),
            ("planner_target_max_weight_g", self.planner_target_max_weight_g),
        ):
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be > 0")

        return self


class AssemblyDefinition(StrictContractModel):
    """
    Schema for assembly_definition.yaml.
    Output by the Engineering Planner to track cost risks.
    """

    version: str = "1.0"
    units: AssemblyUnits = AssemblyUnits()
    constraints: AssemblyConstraints
    manufactured_parts: list[ManufacturedPartEstimate] = []
    coarse_payload_trajectory: CoarsePayloadTrajectory | None = Field(
        default=None,
    )
    final_assembly: list[SubassemblyEstimate | PartConfig] = []
    totals: CostTotals
    dfm_suggestions: list[str] = Field(default_factory=list)

    @property
    def payload_parts(self) -> list[PayloadPart]:
        """Return coarse payload-trajectory part names when declared."""
        if self.coarse_payload_trajectory is None:
            return []
        return [
            PayloadPart(part_name=part_name)
            for part_name in self.coarse_payload_trajectory.payload_part_names
        ]

    @model_validator(mode="after")
    def validate_caps(self) -> "AssemblyDefinition":
        """Enforce planner target positivity and budget compliance."""

        # Enforce INT-010: Estimated totals must be within planner target caps
        if (
            self.totals.estimated_unit_cost_usd
            > self.constraints.planner_target_max_unit_cost_usd
        ):
            raise ValueError(
                f"Estimated unit cost "
                f"(${self.totals.estimated_unit_cost_usd}) "
                f"exceeds target limit "
                f"(${self.constraints.planner_target_max_unit_cost_usd})"
            )
        if (
            self.totals.estimated_weight_g
        ) > self.constraints.planner_target_max_weight_g:
            raise ValueError(
                f"Estimated weight ({self.totals.estimated_weight_g}g) "
                f"exceeds target limit "
                f"({self.constraints.planner_target_max_weight_g}g)"
            )

        return self
