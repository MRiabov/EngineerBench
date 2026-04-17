"""Shared enum definitions for the Problemologist system.

All categorical data should use these enums instead of raw strings,
as mandated by the constitution's Type Safety & Schemas rules.
"""

from enum import StrEnum


class UppercaseStrEnum(StrEnum):
    """Uppercase enum values with backward-compatible case-insensitive matching."""

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            normalized = value.upper()
            for member in cls:
                if member.value == normalized:
                    return member
        return None

    def __eq__(self, other):
        if isinstance(other, str):
            return self.value.lower() == other.lower()
        return super().__eq__(other)

    __hash__ = str.__hash__


class EpisodeStatus(UppercaseStrEnum):
    """Status of an agent episode."""

    RUNNING = "RUNNING"
    PLANNED = "PLANNED"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EpisodePhase(UppercaseStrEnum):
    """Current workflow phase within an episode."""

    BENCHMARK_PLANNING = "BENCHMARK_PLANNING"
    BENCHMARK_PLAN_REVIEWING = "BENCHMARK_PLAN_REVIEWING"
    BENCHMARK_CODING = "BENCHMARK_CODING"
    BENCHMARK_REVIEWING = "BENCHMARK_REVIEWING"
    ENGINEERING_PLANNING = "ENGINEERING_PLANNING"
    ENGINEERING_CODING = "ENGINEERING_CODING"
    ENGINEERING_REVIEWING = "ENGINEERING_REVIEWING"


class TerminalReason(UppercaseStrEnum):
    """Reason why an episode ended in a terminal state."""

    APPROVED = "APPROVED"
    REJECTED_BY_REVIEW = "REJECTED_BY_REVIEW"
    HANDOFF_INVARIANT_VIOLATION = "HANDOFF_INVARIANT_VIOLATION"
    OUT_OF_TURN_BUDGET = "OUT_OF_TURN_BUDGET"
    OUT_OF_TOKEN_BUDGET = "OUT_OF_TOKEN_BUDGET"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SYSTEM_TOOL_RETRY_EXHAUSTED = "SYSTEM_TOOL_RETRY_EXHAUSTED"
    INFRA_ERROR = "INFRA_ERROR"
    USER_CANCELLED = "USER_CANCELLED"


class SessionStatus(UppercaseStrEnum):
    """Status of a benchmark generation session."""

    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class AssetType(UppercaseStrEnum):
    """Type of asset stored in S3."""

    VIDEO = "VIDEO"
    MJCF = "MJCF"
    IMAGE = "IMAGE"
    STEP = "STEP"
    STL = "STL"
    GLB = "GLB"
    PYTHON = "PYTHON"
    OTHER = "OTHER"
    TIMELINE = "TIMELINE"
    MARKDOWN = "MARKDOWN"
    LOG = "LOG"
    ERROR = "ERROR"


class ResponseStatus(UppercaseStrEnum):
    """Standard API response status values."""

    OK = "OK"
    HEALTHY = "HEALTHY"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class EntryFailureDisposition(StrEnum):
    """Routing policy for failed node-entry validation."""

    ALLOW = "allow"
    REROUTE_PREVIOUS = "reroute_previous"
    FAIL_FAST = "fail_fast"


class EntryValidationSource(StrEnum):
    """Primary source category for node-entry validation errors."""

    STATE = "state"
    ARTIFACT = "artifact"
    HANDOVER = "handover"
    POLICY = "policy"


class TraceType(StrEnum):
    """Type of observability trace."""

    TOOL_START = "TOOL_START"
    TOOL_END = "TOOL_END"
    LLM_START = "LLM_START"
    LLM_END = "LLM_END"
    LOG = "LOG"
    ERROR = "ERROR"
    EVENT = "EVENT"


class AgentName(StrEnum):
    """Canonical agent identifiers used across API, evals, and orchestration."""

    BENCHMARK_PLANNER = "benchmark_planner"
    BENCHMARK_PLAN_REVIEWER = "benchmark_plan_reviewer"
    BENCHMARK_CODER = "benchmark_coder"
    BENCHMARK_REVIEWER = "benchmark_reviewer"
    ENGINEER_PLANNER = "engineer_planner"
    ENGINEER_CODER = "engineer_coder"
    ENGINEER_PLAN_REVIEWER = "engineer_plan_reviewer"
    ENGINEER_EXECUTION_REVIEWER = "engineer_execution_reviewer"
    SKILL_AGENT = "skill_agent"
    GIT_AGENT = "git_agent"
    JOURNALLING_AGENT = "journalling_agent"


class EpisodeType(StrEnum):
    """High-level episode workflow family."""

    BENCHMARK = "benchmark"
    ENGINEER = "engineer"


class SeedMatchMethod(StrEnum):
    """How a seed linkage was determined for an episode/dataset row."""

    RUNTIME_EXPLICIT = "runtime_explicit"
    EXACT_TASK = "exact_task"
    NO_EXACT_TASK_MATCH = "no_exact_task_match"
    AMBIGUOUS_EXACT_TASK = "ambiguous_exact_task"


class GenerationKind(StrEnum):
    """Origin category for generated episodes/dataset rows."""

    SEEDED = "seeded"
    DERIVED = "derived"
    SEEDED_EVAL = "seeded_eval"
    INTEGRATION_TEST = "integration_test"
    SKILL_AGENT = "skill_agent"


class DatasetCurationReasonCode(StrEnum):
    """Stable machine-readable reason codes used by dataset curation."""

    INTEGRATION_TEST_ROW = "integration_test_row"
    INTEGRATION_TEST_GENERATION_KIND = "integration_test_generation_kind"
    CORRUPTED_WINDOW_PRE_2026_03_03_DUBLIN = "corrupted_window_pre_2026_03_03_dublin"
    MISSING_CREATED_AT = "missing_created_at"
    INVALID_CREATED_AT = "invalid_created_at"
    MISSING_SOURCE_EPISODE_ID = "missing_source_episode_id"
    MISSING_IDENTITY_HASH = "missing_identity_hash"
    MISSING_FAMILY = "missing_family"
    AMBIGUOUS_LINEAGE = "ambiguous_lineage"
    DUPLICATE_LINEAGE = "duplicate_lineage"
    MALFORMED_REASON_PAYLOAD = "malformed_reason_payload"
    MISSING_OR_EMPTY = "missing_or_empty"
    INVALID_OBJECTIVES_YAML = "invalid_objectives_yaml"
    MISSING_REQUIRED_TRACES = "missing_required_traces"
    WORKFLOW_NOT_COMPLETED = "workflow_not_completed"


class EvalMode(StrEnum):
    """Evaluation modes for run_evals.py."""

    BENCHMARK = "benchmark"
    AGENT = "agent"
    GIT = "git"


class EvalRunnerBackend(StrEnum):
    """Execution backend used by the eval runner."""

    CONTROLLER = "controller"
    CLI = "cli"
    CODEX = "cli"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str) and value.strip().lower() == "codex":
            return cls.CLI
        return None


class FailureReason(UppercaseStrEnum):
    """Unified failure modes for physics simulation and validation."""

    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    FORBID_ZONE_HIT = "FORBID_ZONE_HIT"
    STABILITY_ISSUE = "STABILITY_ISSUE"
    PHYSICS_INSTABILITY = "PHYSICS_INSTABILITY"
    PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION = "PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION"

    ASSET_GENERATION_FAILED = "ASSET_GENERATION_FAILED"

    # Validation failures
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MANUFACTURABILITY_FAILED = "MANUFACTURABILITY_FAILED"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"


# Alias for backward compatibility
SimulationFailureMode = FailureReason


class ManufacturingMethod(UppercaseStrEnum):
    """Supported manufacturing methods."""

    CNC = "CNC"
    THREE_DP = "3DP"
    INJECTION_MOLDING = "IM"


class SimulationConfidence(StrEnum):
    """Confidence levels surfaced by simulation and benchmark responses."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    APPROXIMATE = "approximate"


class ZoneType(StrEnum):
    """Logical zone types used across preview and simulation builders."""

    GOAL = "goal"
    BUILD = "build"
    FORBID = "forbid"


class ReviewDecision(UppercaseStrEnum):
    """Decision values for reviewer nodes."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REJECT_PLAN = "REJECT_PLAN"
    REJECT_CODE = "REJECT_CODE"
    CONFIRM_PLAN_REFUSAL = "CONFIRM_PLAN_REFUSAL"
    REJECT_PLAN_REFUSAL = "REJECT_PLAN_REFUSAL"


class MechanicalRefusalReason(UppercaseStrEnum):
    """Refusal reasons for engineer_coder."""

    PHYSICALLY_IMPOSSIBLE = "PHYSICALLY_IMPOSSIBLE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    WEIGHT_EXCEEDED = "WEIGHT_EXCEEDED"
    MISSING_COMPONENTS = "MISSING_COMPONENTS"
    UNSUPPORTED_MANUFACTURING = "UNSUPPORTED_MANUFACTURING"
    AMBIGUOUS_OBJECTIVES = "AMBIGUOUS_OBJECTIVES"
    COMPONENT_CONFLICT = "COMPONENT_CONFLICT"


class BenchmarkRefusalReason(UppercaseStrEnum):
    """Refusal reasons for benchmark_coder."""

    INVALID_OBJECTIVES = "INVALID_OBJECTIVES"
    CONTRADICTORY_CONSTRAINTS = "CONTRADICTORY_CONSTRAINTS"
    UNSOLVABLE_SCENARIO = "UNSOLVABLE_SCENARIO"
    AMBIGUOUS_TASK = "AMBIGUOUS_TASK"


class FailureClass(UppercaseStrEnum):
    """High-level failure ownership classification for terminal outcomes."""

    AGENT_QUALITY_FAILURE = "AGENT_QUALITY_FAILURE"
    AGENT_SEMANTIC_FAILURE = "AGENT_SEMANTIC_FAILURE"
    APPLICATION_LOGIC_FAILURE = "APPLICATION_LOGIC_FAILURE"
    INFRA_DEVOPS_FAILURE = "INFRA_DEVOPS_FAILURE"
