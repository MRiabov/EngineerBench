from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class MilestoneConfig(BaseModel):
    """Configuration for a single reward milestone."""

    weight: float
    description: str
    partial: bool = False

    # Optional formulas for different evaluation types
    formula: str | None = None  # Generic formula
    penalty_formula: str | None = None  # Formula for calculating continuous penalty
    success_formula: str | None = None  # Formula for success case
    failure_formula: str | None = None  # Formula for failure case

    # Result mapping
    minimum_score: float | None = None
    binary: bool = False  # If True, only 0.0 or 1.0 (weighted by 'weight')

    # Feedback strings for GEPA optimization
    success_feedback: str | None = None
    failure_feedback: str | None = None


class JudgeEvaluationConfig(BaseModel):
    """Structured reward configuration for judge-based metrics."""

    metrics: dict[str, MilestoneConfig] = Field(default_factory=dict)
    checklist: dict[str, MilestoneConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_layout(cls, data):
        if data is None:
            return {}
        if isinstance(data, dict):
            metrics = data.get("metrics")
            checklist = data.get("checklist")
            if metrics is None:
                metrics = {
                    key: value for key, value in data.items() if key != "checklist"
                }
            return {
                "metrics": metrics or {},
                "checklist": checklist or {},
            }
        return data

    def all_milestones(self) -> dict[str, MilestoneConfig]:
        merged = dict(self.metrics)
        for checklist_key, milestone in self.checklist.items():
            merged[f"checklist.{checklist_key}"] = milestone
        return merged


class AgentRewardConfig(BaseModel):
    """Configuration for an agent's reward structure."""

    description: str
    milestones: dict[str, MilestoneConfig] = Field(default_factory=dict)
    hard_checks: dict[str, MilestoneConfig] = Field(default_factory=dict)
    judge_evaluation: JudgeEvaluationConfig = Field(
        default_factory=JudgeEvaluationConfig
    )

    @model_validator(mode="after")
    def validate_milestone_layout(self) -> "AgentRewardConfig":
        raw_milestones = self._raw_all_milestones()
        merged_keys = set(raw_milestones)
        total_count = len(raw_milestones)
        if not merged_keys:
            raise ValueError("AgentRewardConfig must define at least one milestone")
        if len(merged_keys) != total_count:
            raise ValueError(
                "Duplicate milestone names across milestones/hard_checks/judge_evaluation"
            )
        total_weight = sum(milestone.weight for milestone in raw_milestones.values())
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError(
                f"AgentRewardConfig weights must sum to 1.0, got {total_weight:.3f}"
            )
        return self

    def _raw_all_milestones(self) -> dict[str, MilestoneConfig]:
        merged: dict[str, MilestoneConfig] = {}
        merged.update(self.hard_checks)
        merged.update(self.judge_evaluation.all_milestones())
        merged.update(self.milestones)
        return merged

    def all_milestones(self) -> dict[str, MilestoneConfig]:
        return self._raw_all_milestones()


class RewardConfig(BaseModel):
    """Top-level reward configuration for DSPy optimization."""

    bootstrap_threshold: float
    benchmark: dict[str, AgentRewardConfig]
    engineer: dict[str, AgentRewardConfig]


def load_reward_config(config_path: Path | None = None) -> RewardConfig:
    """
    Loads and validates the reward configuration from a YAML file.

    Args:
        config_path: Path to the reward_config.yaml file.
                     Defaults to config/reward_config.yaml relative to project root.

    Returns:
        RewardConfig: Validated pydantic model.
    """
    if config_path is None:
        # Assuming we are running from project root or similar structure
        config_path = Path("config/reward_config.yaml")

    if not config_path.exists():
        # Fallback to absolute path search if relative fails in some contexts
        # (e.g. running from a subdirectory)
        root_path = Path(__file__).parent.parent.parent
        config_path = root_path / "config" / "reward_config.yaml"

    with config_path.open() as f:
        config_data = yaml.safe_load(f)

    return RewardConfig(**config_data)
