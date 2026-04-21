from __future__ import annotations

from pathlib import Path
from typing import Literal

import structlog
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from shared.enums import AgentName

logger = structlog.get_logger(__name__)

ReasoningEffortLevel = Literal["low", "medium", "high", "xhigh"]
RenderBucketName = Literal[
    "benchmark_renders",
    "engineer_plan_renders",
    "final_solution_submission_renders",
]

RENDER_BUCKET_NAME_SEQUENCE: tuple[str, ...] = (
    "benchmark_renders",
    "engineer_plan_renders",
    "final_solution_submission_renders",
)


class PathPolicy(BaseModel):
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class FilesystemPermissions(BaseModel):
    read: PathPolicy = Field(default_factory=PathPolicy)
    write: PathPolicy = Field(default_factory=PathPolicy)


class VisualInspectionPolicy(BaseModel):
    required: bool = False
    min_images: int = Field(default=1, ge=1)
    reminder_interval: int = Field(default=2, ge=1)
    entry_expects_render_buckets: list[RenderBucketName] = Field(default_factory=list)

    @field_validator("entry_expects_render_buckets", mode="before")
    @classmethod
    def _normalize_entry_expects_render_buckets(
        cls, value: object
    ) -> list[str] | object:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return value

        seen: set[str] = set()
        for raw_bucket in value:
            bucket = str(raw_bucket).strip()
            if not bucket:
                continue
            if bucket not in RENDER_BUCKET_NAME_SEQUENCE:
                msg = (
                    f"Unknown render bucket '{bucket}'. Expected one of: "
                    f"{', '.join(RENDER_BUCKET_NAME_SEQUENCE)}"
                )
                raise ValueError(msg)
            seen.add(bucket)

        normalized: list[str] = []
        for bucket in RENDER_BUCKET_NAME_SEQUENCE:
            if bucket in seen:
                normalized.append(bucket)
        return normalized


class PayloadTrajectoryBudget(BaseModel):
    sample_stride_s: float = Field(default=0.5, gt=0)
    position_tolerance_mm: tuple[float, float, float] = Field(default=(1.2, 1.2, 1.2))
    rotation_tolerance_deg: tuple[float, float, float] = Field(default=(0.1, 0.1, 5.0))


class PayloadTrajectoryPolicy(BaseModel):
    benchmark_planner: PayloadTrajectoryBudget = Field(
        default_factory=lambda: PayloadTrajectoryBudget(
            sample_stride_s=2.0,
            position_tolerance_mm=(6.0, 6.0, 6.0),
            rotation_tolerance_deg=(0.1, 0.1, 15.0),
        )
    )
    engineer_planner: PayloadTrajectoryBudget = Field(
        default_factory=lambda: PayloadTrajectoryBudget(
            sample_stride_s=0.5,
            position_tolerance_mm=(1.2, 1.2, 1.2),
            rotation_tolerance_deg=(0.1, 0.1, 5.0),
        )
    )
    engineer_coder: PayloadTrajectoryBudget = Field(
        default_factory=lambda: PayloadTrajectoryBudget(
            sample_stride_s=0.3,
            position_tolerance_mm=(0.6, 0.6, 0.6),
            rotation_tolerance_deg=(0.1, 0.1, 2.0),
        )
    )


class PayloadTrajectoryClearanceBudget(BaseModel):
    enabled: bool = True
    max_orientation_cells: int = Field(default=96, ge=1)
    max_recursion_depth: int = Field(default=6, ge=0)
    max_exact_checks: int = Field(default=9, ge=1)
    leaf_span_deg: tuple[float, float, float] = Field(default=(2.0, 2.0, 2.0))


class PayloadTrajectoryMonitorPolicy(BaseModel):
    enabled: bool = True
    monitor_sample_stride_s: float = Field(default=0.3, gt=0)
    consecutive_miss_count: int = Field(default=2, ge=1)


class BenchmarkPayloadObservationPolicy(BaseModel):
    window_s: float = Field(default=1.5, gt=0)


class BugReportsConfig(BaseModel):
    enabled: bool = False
    archive_root: Path = Field(default_factory=lambda: Path("logs/bug_reports"))


class AgentPolicy(BaseModel):
    filesystem_permissions: FilesystemPermissions = Field(
        default_factory=FilesystemPermissions
    )
    tools: list[str] | None = None
    reasoning_effort: ReasoningEffortLevel = "high"
    allowed_during_unit_eval: list[AgentName] = Field(default_factory=list)
    visual_inspection: VisualInspectionPolicy = Field(
        default_factory=VisualInspectionPolicy
    )

    @field_validator("allowed_during_unit_eval", mode="before")
    @classmethod
    def _normalize_allowed_during_unit_eval(
        cls, value: object
    ) -> list[AgentName] | object:
        if value is None:
            return []
        if isinstance(value, (str, AgentName)):
            value = [value]
        if not isinstance(value, list):
            return value

        normalized: list[AgentName] = []
        seen: set[str] = set()
        for raw_role in value:
            if isinstance(raw_role, AgentName):
                role = raw_role
            else:
                role_text = str(raw_role).strip()
                if not role_text:
                    continue
                role = AgentName(role_text)
            if role.value in seen:
                continue
            normalized.append(role)
            seen.add(role.value)
        return normalized

    @model_validator(mode="before")
    @classmethod
    def _normalize_filesystem_permissions(
        cls, value: object
    ) -> dict[str, object] | object:
        if not isinstance(value, dict):
            return value

        has_legacy = "read" in value or "write" in value
        has_new = "filesystem_permissions" in value
        if has_legacy and has_new:
            raise ValueError(
                "AgentPolicy cannot define both legacy read/write and "
                "filesystem_permissions keys."
            )

        if not has_legacy:
            return value

        normalized = dict(value)
        normalized["filesystem_permissions"] = {
            "read": normalized.pop("read", {}),
            "write": normalized.pop("write", {}),
        }
        return normalized

    @property
    def read(self) -> PathPolicy:
        return self.filesystem_permissions.read

    @property
    def write(self) -> PathPolicy:
        return self.filesystem_permissions.write


class LLMPolicyConfig(BaseModel):
    max_reasoning_tokens: int = 16384
    context_compaction_threshold_tokens: int = 225000
    requests_per_minute: int = Field(default=40, ge=1)
    multimodal_model: str | None = None
    reasoning_effort_enabled: bool = True


class RenderResolutionConfig(BaseModel):
    width_px: int = Field(default=1024, ge=1)
    height_px: int = Field(default=768, ge=1)

    @property
    def width(self) -> int:
        return self.width_px

    @property
    def height(self) -> int:
        return self.height_px


class RenderModalityConfig(BaseModel):
    enabled: bool = True
    axes: bool = True
    edges: bool = True


class RenderPayloadPathOverlayConfig(BaseModel):
    enabled: bool = True


class RenderPolicyConfig(BaseModel):
    image_resolution: RenderResolutionConfig = Field(
        default_factory=lambda: RenderResolutionConfig(width_px=1024, height_px=768)
    )
    video_resolution: RenderResolutionConfig = Field(
        default_factory=lambda: RenderResolutionConfig(width_px=1280, height_px=960)
    )
    split_video_renders_to_images: bool = False
    video_frame_attachment_stride: int = Field(default=6, ge=1)
    video_frame_jpeg_quality_percent: int = Field(default=85, ge=1, le=100)
    rgb: RenderModalityConfig = Field(default_factory=RenderModalityConfig)
    depth: RenderModalityConfig = Field(default_factory=RenderModalityConfig)
    segmentation: RenderModalityConfig = Field(default_factory=RenderModalityConfig)
    handoff_rgb_payload_path_overlay: RenderPayloadPathOverlayConfig = Field(
        default_factory=RenderPayloadPathOverlayConfig
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_render_policy(
        cls, value: object
    ) -> dict[str, object] | object:
        if not isinstance(value, dict):
            return value

        normalized = dict(value)

        legacy_resolution = normalized.pop("resolution", None)
        if isinstance(legacy_resolution, dict):
            normalized.setdefault("image_resolution", legacy_resolution)
            normalized.setdefault("video_resolution", legacy_resolution)

        def _ensure_modality_config(modality: str) -> dict[str, object]:
            raw_modality = normalized.get(modality)
            if isinstance(raw_modality, dict):
                return dict(raw_modality)
            if isinstance(raw_modality, bool):
                return {"enabled": raw_modality}
            if raw_modality is None:
                return {}
            return dict(raw_modality)

        for legacy_key, (modality_key, field_name) in (
            ("rgb_axes", ("rgb", "axes")),
            ("rgb_edges", ("rgb", "edges")),
            ("depth_axes", ("depth", "axes")),
            ("depth_edges", ("depth", "edges")),
            ("segmentation_axes", ("segmentation", "axes")),
            ("segmentation_edges", ("segmentation", "edges")),
        ):
            if legacy_key not in normalized:
                continue
            modality_cfg = _ensure_modality_config(modality_key)
            modality_cfg[field_name] = normalized.pop(legacy_key)
            normalized[modality_key] = modality_cfg

        for modality_key in ("rgb", "depth", "segmentation"):
            raw_modality = normalized.get(modality_key)
            if isinstance(raw_modality, bool):
                normalized[modality_key] = {"enabled": raw_modality}

        return normalized


class AgentExecutionPolicy(BaseModel):
    timeout_seconds: int = Field(default=300, ge=1)
    max_turns: int = Field(default=150, ge=1)
    max_total_tokens: int = Field(default=400000, ge=1)
    native_tool_loop_max_iters: int = Field(default=8, ge=1)


class AgentExecutionConfig(BaseModel):
    defaults: AgentExecutionPolicy = Field(default_factory=AgentExecutionPolicy)
    agents: dict[str, AgentExecutionPolicy] = Field(default_factory=dict)

    @field_validator("agents", mode="before")
    @classmethod
    def _normalize_agent_keys(
        cls, value: object
    ) -> dict[str, AgentExecutionPolicy] | object:
        if not isinstance(value, dict):
            return value
        normalized: dict[str, AgentExecutionPolicy] = {}
        for raw_key, raw_policy in value.items():
            key = str(raw_key)
            try:
                key = AgentName(key).value
            except Exception:
                key = key.strip().lower()
            if isinstance(raw_policy, AgentExecutionPolicy):
                normalized[key] = raw_policy
            else:
                normalized[key] = AgentExecutionPolicy.model_validate(raw_policy)
        return normalized

    def get_policy(self, agent_role: AgentName | str) -> AgentExecutionPolicy:
        key = agent_role.value if isinstance(agent_role, AgentName) else str(agent_role)
        policy = self.agents.get(key)
        if policy:
            return policy
        return self.defaults


class AgentsConfig(BaseModel):
    llm: LLMPolicyConfig = Field(default_factory=LLMPolicyConfig)
    render: RenderPolicyConfig = Field(default_factory=RenderPolicyConfig)
    execution: AgentExecutionConfig = Field(default_factory=AgentExecutionConfig)
    bug_reports: BugReportsConfig = Field(default_factory=BugReportsConfig)
    coarse_payload_trajectory: PayloadTrajectoryPolicy = Field(
        default_factory=PayloadTrajectoryPolicy,
    )
    payload_trajectory_monitor: PayloadTrajectoryMonitorPolicy = Field(
        default_factory=PayloadTrajectoryMonitorPolicy
    )
    benchmark_payload_observation: BenchmarkPayloadObservationPolicy = Field(
        default_factory=BenchmarkPayloadObservationPolicy
    )
    payload_trajectory_clearance: PayloadTrajectoryClearanceBudget = Field(
        default_factory=PayloadTrajectoryClearanceBudget
    )
    defaults: AgentPolicy = Field(default_factory=AgentPolicy)
    agents: dict[str, AgentPolicy] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _require_visual_inspection_bucket_expectations(
        cls, value: object
    ) -> dict[str, object] | object:
        if not isinstance(value, dict):
            return value

        agents = value.get("agents")
        if not isinstance(agents, dict):
            return value

        missing_roles: list[str] = []
        for raw_role, raw_policy in agents.items():
            if not isinstance(raw_policy, dict):
                continue
            visual_inspection = raw_policy.get("visual_inspection")
            if isinstance(visual_inspection, dict) and (
                "entry_expects_render_buckets" not in visual_inspection
            ):
                missing_roles.append(str(raw_role))

        if missing_roles:
            roles = ", ".join(sorted(missing_roles))
            raise ValueError(
                "visual_inspection.entry_expects_render_buckets is required for "
                f"agents: {roles}"
            )

        return value

    def get_allowed_during_unit_eval(
        self, agent_role: AgentName | str
    ) -> tuple[AgentName, ...]:
        key = agent_role.value if isinstance(agent_role, AgentName) else str(agent_role)
        policy = self.agents.get(key)
        if policy is None:
            return ()
        return tuple(policy.allowed_during_unit_eval)

    def get_coarse_payload_trajectory_policy(
        self, planner_role: AgentName | str
    ) -> PayloadTrajectoryBudget:
        key = (
            planner_role.value
            if isinstance(planner_role, AgentName)
            else str(planner_role)
        )
        normalized = key.strip().lower()
        if normalized in {
            AgentName.BENCHMARK_PLANNER.value,
            AgentName.BENCHMARK_PLAN_REVIEWER.value,
            AgentName.BENCHMARK_CODER.value,
            AgentName.BENCHMARK_REVIEWER.value,
        }:
            return self.coarse_payload_trajectory.benchmark_planner
        if normalized in {
            AgentName.ENGINEER_PLANNER.value,
            AgentName.ENGINEER_PLAN_REVIEWER.value,
        }:
            return self.coarse_payload_trajectory.engineer_planner
        if normalized in {
            AgentName.ENGINEER_CODER.value,
            AgentName.ENGINEER_EXECUTION_REVIEWER.value,
        }:
            return self.coarse_payload_trajectory.engineer_coder
        return self.coarse_payload_trajectory.engineer_planner

    def get_reasoning_effort(
        self,
        agent_role: AgentName | str | None,
        *,
        requested_effort: ReasoningEffortLevel | None = None,
    ) -> ReasoningEffortLevel | None:
        if not self.llm.reasoning_effort_enabled:
            return None
        if requested_effort is not None:
            return requested_effort

        if agent_role is None:
            return self.defaults.reasoning_effort

        key = agent_role.value if isinstance(agent_role, AgentName) else str(agent_role)
        policy = self.agents.get(key)
        if policy is None:
            return self.defaults.reasoning_effort
        return policy.reasoning_effort


def get_render_resolution(config: AgentsConfig | None = None) -> tuple[int, int]:
    render_config = (config or load_agents_config()).render.image_resolution
    return render_config.width_px, render_config.height_px


def get_image_render_resolution(
    config: AgentsConfig | None = None,
) -> tuple[int, int]:
    render_config = (config or load_agents_config()).render.image_resolution
    return render_config.width_px, render_config.height_px


def get_video_render_resolution(
    config: AgentsConfig | None = None,
) -> tuple[int, int]:
    render_config = (config or load_agents_config()).render.video_resolution
    return render_config.width_px, render_config.height_px


def resolve_agents_config_path() -> Path | None:
    candidates = (
        Path("config/agents_config.yaml"),
        Path(__file__).parents[2] / "config" / "agents_config.yaml",
        Path("/app/config/agents_config.yaml"),
    )
    return next((p for p in candidates if p.exists()), None)


def load_agents_config(config_path: str | Path | None = None) -> AgentsConfig:
    resolved_path = (
        Path(config_path) if config_path is not None else resolve_agents_config_path()
    )
    if resolved_path is None:
        raise FileNotFoundError("Agents configuration file not found")

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle) or {}
        return AgentsConfig.model_validate(raw_data)
    except Exception as exc:
        logger.warning(
            "failed_to_load_agents_config",
            config_path=str(resolved_path),
            error=str(exc),
        )
        raise
