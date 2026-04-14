from __future__ import annotations

import os
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from shared.enums import FailureReason as SimulationFailureMode

if TYPE_CHECKING:
    from shared.runtime.headless import HeadlessGLBackend


class SimulatorBackendType(StrEnum):
    MUJOCO = "MUJOCO"  # Rigid-body only, fast
    GENESIS = "GENESIS"  # General-purpose physics backend

    def accepted_headless_gl_backends(self) -> tuple[HeadlessGLBackend, ...]:
        from shared.runtime.headless import HeadlessGLBackend

        if self is SimulatorBackendType.MUJOCO:
            return (HeadlessGLBackend.EGL,)
        if self is SimulatorBackendType.GENESIS:
            return (HeadlessGLBackend.EGL, HeadlessGLBackend.OSMESA)
        raise ValueError(f"Unknown physics backend type: {self}")

    def default_headless_gl_backend(self) -> HeadlessGLBackend:
        from shared.runtime.headless import HeadlessGLBackend

        if self is SimulatorBackendType.MUJOCO:
            return HeadlessGLBackend.EGL
        if self is SimulatorBackendType.GENESIS:
            return HeadlessGLBackend.OSMESA
        raise ValueError(f"Unknown physics backend type: {self}")


def get_default_simulator_backend() -> SimulatorBackendType:
    """Resolve default backend from environment.

    Empty values default to MuJoCo for rigid-body-only workflows. Invalid
    explicit values fail closed instead of silently falling back to a different
    backend.
    """
    raw_value = os.getenv("SIMULATION_DEFAULT_BACKEND", "").strip().upper()
    if not raw_value:
        return SimulatorBackendType.MUJOCO
    try:
        return SimulatorBackendType(raw_value)
    except ValueError:
        raise ValueError("SIMULATION_DEFAULT_BACKEND must be one of: MUJOCO, GENESIS")


class SimulationRequest(BaseModel):
    session_id: str
    mjcf_content: str | None = None
    compound_json: str | None = None
    backend: SimulatorBackendType = Field(default_factory=get_default_simulator_backend)
    dt: float = Field(default=0.01, gt=0)
    duration: float = Field(default=5.0, gt=0)
    randomize: bool = False


class BackendSimulationResult(BaseModel):
    success: bool
    failure_reason: SimulationFailureMode | None = None
    logs: list[str] = []
    metrics: dict[str, Any] = {}


class CustomObjectives(BaseModel):
    """User-defined objectives/constraints for the benchmark."""

    max_unit_cost: float | None = Field(default=None, gt=0)
    max_weight: float | None = Field(default=None, gt=0)
    target_quantity: int | None = Field(default=None, ge=1)
    additional_constraints: dict[str, Any] = Field(default_factory=dict)


class RandomizationStrategy(BaseModel):
    """Structured strategy for benchmark randomization."""

    theme: str
    target_object_properties: dict[str, Any] = Field(default_factory=dict)
    environment_perturbations: dict[str, Any] = Field(default_factory=dict)
    difficulty_score: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str | None = None


class ValidationResult(BaseModel):
    """Result of a benchmark validation/simulation run."""

    valid: bool
    cost: float = 0.0
    logs: list[str] = []
    render_paths: list[str] = []
    render_data: list[bytes] | None = None


class AssetMetadata(BaseModel):
    """Metadata for a benchmark asset."""

    theme: str | None = None
    complexity: str | None = None
    tags: list[str] = []
    additional_info: dict[str, Any] = {}
