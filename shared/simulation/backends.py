from typing import Any, Protocol, runtime_checkable

import numpy as np
from pydantic import BaseModel, Field, model_validator

from shared.models.simulation import (
    RendererCapabilities,
    SimulationFailure,
)
from shared.workers.schema import RenderBundleObjectPoseRecord


class BodyState(BaseModel):
    pos: tuple[float, float, float]
    quat: tuple[float, float, float, float]
    vel: tuple[float, float, float]
    angvel: tuple[float, float, float]


class ContactForce(BaseModel):
    body1: str
    body2: str
    force: tuple[float, float, float]
    position: tuple[float, float, float]


class ActuatorState(BaseModel):
    force: float
    velocity: float
    ctrl: float
    forcerange: tuple[float, float]


class SiteState(BaseModel):
    pos: tuple[float, float, float]
    quat: tuple[float, float, float, float]
    size: tuple[float, float, float]


class StepResult(BaseModel):
    time: float
    success: bool
    failure: SimulationFailure | None = None

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_failure_reason(cls, data: Any) -> Any:
        if (
            isinstance(data, dict)
            and "failure_reason" in data
            and "failure" not in data
        ):
            reason_str = data.pop("failure_reason")
            if reason_str:
                from shared.enums import FailureReason

                # Try to parse legacy string format
                parts = reason_str.split(":", 1)
                try:
                    reason_enum = FailureReason(parts[0].upper())
                    detail = parts[1] if len(parts) > 1 else None
                    data["failure"] = SimulationFailure(
                        reason=reason_enum, detail=detail
                    )
                except ValueError:
                    # If it's not a valid enum member, treat whole string as detail
                    data["failure"] = SimulationFailure(
                        reason=FailureReason.STABILITY_ISSUE, detail=reason_str
                    )
        return data

    @property
    def failure_reason(self) -> str | None:
        """Legacy access to stringified failure reason."""
        return str(self.failure) if self.failure else None


class SceneConfig(BaseModel):
    """Configuration for the simulation scene."""

    particle_budget: int = 100000
    model_config = {"extra": "allow"}


class SceneAssets(BaseModel):
    """Assets associated with a simulation scene."""

    gs_scene: Any | None = None
    entities: list[dict[str, Any]] = []
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}


class SimulationScene(BaseModel):
    """Container for scene definition.
    For MuJoCo, this might be the XML path.
    For Genesis, it might be a list of morphs/assets.
    """

    scene_path: str | None = None
    assets: SceneAssets = Field(default_factory=SceneAssets)
    config: SceneConfig = Field(default_factory=SceneConfig)


@runtime_checkable
class RendererBackend(Protocol):
    """Common interface for offscreen scene renderers."""

    smoke_test_mode: bool = False

    def load_scene(self, scene: Any, render_only: bool = False) -> None: ...

    def render(self) -> np.ndarray: ...
    def render_camera(
        self, camera_name: str, width: int, height: int
    ) -> np.ndarray: ...
    def get_render_capabilities(self) -> RendererCapabilities: ...

    def get_particle_positions(self) -> np.ndarray | None: ...
    def set_camera(
        self,
        camera_name: str,
        pos: tuple[float, float, float] | None = None,
        lookat: tuple[float, float, float] | None = None,
        up: tuple[float, float, float] | None = None,
        fov: float | None = None,
    ) -> None: ...

    def get_all_camera_names(self) -> list[str]: ...
    def close(self) -> None: ...


@runtime_checkable
class PhysicsBackend(Protocol):
    """Interface for physics simulators."""

    smoke_test_mode: bool = False

    def load_scene(self, scene: Any, render_only: bool = False) -> None: ...

    def step(self, dt: float) -> StepResult: ...
    def get_time(self) -> float: ...
    def get_body_state(self, body_id: str) -> BodyState: ...
    def get_state(self) -> dict[str, Any]: ...
    def get_particle_positions(self) -> np.ndarray | None: ...
    def get_camera_matrix(self, camera_name: str) -> np.ndarray: ...
    def set_site_pos(self, site_name: str, pos: np.ndarray) -> None: ...
    def get_site_state(self, site_name: str) -> SiteState: ...
    def get_actuator_state(self, actuator_name: str) -> ActuatorState: ...
    def apply_control(self, control_inputs: dict[str, float]) -> None: ...
    def get_contact_forces(self) -> list[ContactForce]: ...

    def get_all_body_names(self) -> list[str]: ...
    def get_all_actuator_names(self) -> list[str]: ...
    def get_all_site_names(self) -> list[str]: ...
    def get_all_tendon_names(self) -> list[str]: ...
    def get_all_camera_names(self) -> list[str]: ...
    def export_object_pose_records(
        self,
        *,
        body_names: list[str] | None = None,
        frame_index: int | None = None,
    ) -> list[RenderBundleObjectPoseRecord]: ...

    def check_collision(self, body_name: str, site_name: str) -> bool: ...
    def get_tendon_tension(self, tendon_name: str) -> float: ...

    def apply_jitter(
        self, body_name: str, jitter: tuple[float, float, float]
    ) -> None: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


def _normalize_pose_body_names(body_names: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in body_names:
        name = str(raw_name).strip()
        if not name:
            continue
        if name in {"world", "0", "mjcf_scene"}:
            continue
        if name.startswith("zone_"):
            continue
        if name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def _quaternion_wxyz_to_euler_xyz_deg(
    quat: tuple[float, float, float, float] | list[float] | np.ndarray,
) -> tuple[float, float, float] | None:
    try:
        quat_array = np.asarray(quat, dtype=float)
    except Exception:
        return None

    if quat_array.shape != (4,) or not np.all(np.isfinite(quat_array)):
        return None

    try:
        from scipy.spatial.transform import Rotation as SciPyRotation

        euler = SciPyRotation.from_quat(
            [quat_array[1], quat_array[2], quat_array[3], quat_array[0]]
        ).as_euler("xyz", degrees=True)
    except Exception:
        return None

    return tuple(float(value) for value in euler.tolist())


def build_render_bundle_object_pose_records(
    backend: PhysicsBackend,
    *,
    body_names: list[str] | None = None,
    frame_index: int | None = None,
) -> list[RenderBundleObjectPoseRecord]:
    """Materialize a bundle-local snapshot of backend object poses."""
    records: list[RenderBundleObjectPoseRecord] = []
    if body_names is None:
        body_names = backend.get_all_body_names()
    body_names = _normalize_pose_body_names(body_names)

    for object_id, body_name in enumerate(body_names):
        try:
            state = backend.get_body_state(body_name)
        except Exception:
            continue

        records.append(
            RenderBundleObjectPoseRecord(
                frame_index=frame_index,
                object_id=object_id,
                object_type="body",
                label=body_name,
                instance_id=body_name,
                instance_name=body_name,
                semantic_label=body_name,
                body_name=body_name,
                geom_name=None,
                position=state.pos,
                orientation=_quaternion_wxyz_to_euler_xyz_deg(state.quat),
            )
        )

    return records


@runtime_checkable
class PhysicsRendererBackend(PhysicsBackend, RendererBackend, Protocol):
    """Backend that exposes both physics simulation and rendering."""


# Backward compatibility for older imports while the codebase migrates to the
# clearer renderer terminology.
ViewerBackend = RendererBackend
