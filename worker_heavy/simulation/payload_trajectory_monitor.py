from __future__ import annotations

from bisect import bisect_right
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import yaml

from shared.agents.config import PayloadTrajectoryMonitorPolicy, load_agents_config
from shared.enums import FailureReason
from shared.models.schemas import (
    PayloadTrajectoryAnchor,
    PayloadTrajectoryDefinition,
)
from shared.models.simulation import (
    PayloadTrajectoryMonitorState,
    SimulationFailure,
)
from shared.simulation.backends import (
    PhysicsBackend,
    _quaternion_wxyz_to_euler_xyz_deg,
)


def load_payload_trajectory_definition(
    workspace_root: Path,
) -> PayloadTrajectoryDefinition | None:
    """Load the engineer-owned payload trajectory artifact if it exists."""
    payload_path = Path(workspace_root) / "payload_trajectory_definition.yaml"
    if not payload_path.exists():
        return None

    raw = yaml.safe_load(payload_path.read_text(encoding="utf-8")) or {}
    return PayloadTrajectoryDefinition.model_validate(raw)


def _wrap_degrees(delta: float) -> float:
    return ((delta + 180.0) % 360.0) - 180.0


def _resolve_body_names(
    backend: PhysicsBackend,
    names: Sequence[str],
) -> list[str]:
    available = set(backend.get_all_body_names())
    resolved: list[str] = []
    for raw_name in names:
        name = str(raw_name).strip()
        if not name:
            continue
        if name in available:
            resolved.append(name)
            continue
        candidate = f"benchmark_moved_object__{name}"
        if candidate in available:
            resolved.append(candidate)
            continue
        raise ValueError(
            f"payload_trajectory_definition moving_part_name '{name}' was not "
            "found in the simulation body list"
        )
    if not resolved:
        raise ValueError(
            "payload_trajectory_definition must resolve at least one moving body"
        )
    return resolved


def _flatten_first_contacts(
    anchors: Sequence[PayloadTrajectoryAnchor],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for anchor in anchors:
        for contact in sorted(anchor.first_contacts, key=lambda item: item.order):
            surface = contact.surface.strip()
            if not surface or surface in seen:
                continue
            ordered.append(surface)
            seen.add(surface)
    return ordered


class PayloadTrajectoryMonitor:
    """Fail-fast monitor for engineer-owned payload trajectory compliance."""

    def __init__(
        self,
        *,
        payload_definition: PayloadTrajectoryDefinition,
        backend: PhysicsBackend,
        backend_type: Any | None = None,
        goal_sites: list[str] | None = None,
        target_body_name: str | None = None,
        policy: PayloadTrajectoryMonitorPolicy | None = None,
        session_id: str | None = None,
    ) -> None:
        self.payload_definition = payload_definition
        self.backend = backend
        self.backend_type = backend_type
        self.goal_sites = list(goal_sites or [])
        self.target_body_name = target_body_name
        self.session_id = session_id
        self.policy = policy or load_agents_config().payload_trajectory_monitor

        self.tracked_body_names: list[str] = []
        self._anchor_times_s: list[float] = [
            float(anchor.t_s) for anchor in payload_definition.anchors
        ]
        self._required_first_contacts = _flatten_first_contacts(
            payload_definition.anchors
        )
        self._observed_first_contacts: list[str] = []
        self._seen_first_contacts: set[str] = set()
        self._next_check_time_s = 0.0
        self._last_checked_anchor_index: int | None = None
        self._terminal_goal_zone_proven = False
        self._last_state = PayloadTrajectoryMonitorState(
            monitor_sample_stride_s=None,
            configured_consecutive_miss_count=None,
        )

        if not self.policy.enabled:
            self._monitor_sample_stride_s = float(payload_definition.sample_stride_s)
            self._configured_consecutive_miss_count = int(
                self.policy.consecutive_miss_count
            )
            self._last_state = self._build_state()
            return

        backend_type_text = getattr(self.backend_type, "value", self.backend_type)
        payload_backend_text = getattr(
            self.payload_definition.backend, "value", self.payload_definition.backend
        )
        if backend_type_text is not None and str(backend_type_text) != str(
            payload_backend_text
        ):
            raise ValueError(
                "payload_trajectory_definition backend does not match the active "
                "simulation backend"
            )

        self._monitor_sample_stride_s = min(
            float(self.policy.monitor_sample_stride_s),
            float(self.payload_definition.sample_stride_s),
        )
        self._configured_consecutive_miss_count = int(
            self.policy.consecutive_miss_count
        )
        self.tracked_body_names = _resolve_body_names(
            self.backend, self.payload_definition.payload_part_names
        )
        self._last_state = self._build_state()

    def reset(self) -> None:
        self._observed_first_contacts = []
        self._seen_first_contacts = set()
        self._next_check_time_s = 0.0
        self._last_checked_anchor_index = None
        self._terminal_goal_zone_proven = False
        self._last_state = self._build_state(consecutive_miss_count=0)

    @property
    def state(self) -> PayloadTrajectoryMonitorState:
        return self._last_state

    def _sample_reference_pose(
        self,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float] | None]:
        states = [self.backend.get_body_state(name) for name in self.tracked_body_names]
        if not states:
            raise ValueError("payload trajectory monitor could not sample body state")

        # Use the tracked moving bodies' centroid as the runtime reference point.
        positions = np.array([state.pos for state in states], dtype=float)
        position = tuple(float(value) for value in positions.mean(axis=0).tolist())
        rotation = _quaternion_wxyz_to_euler_xyz_deg(states[0].quat)
        return position, rotation

    def _current_contact_names(self) -> list[str]:
        contacts: list[str] = []
        for contact in self.backend.get_contact_forces():
            for body_name in (contact.body1, contact.body2):
                body_name = str(body_name).strip()
                if body_name:
                    contacts.append(body_name)
        return contacts

    def _anchor_is_within_tolerance(
        self,
        anchor: PayloadTrajectoryAnchor,
        observed_pos_mm: tuple[float, float, float],
        observed_rot_deg: tuple[float, float, float] | None,
    ) -> tuple[bool, tuple[float, float, float], tuple[float, float, float] | None]:
        expected_pos = tuple(float(value) for value in anchor.pos_mm)
        pos_error = tuple(
            float(observed_pos_mm[index] - expected_pos[index]) for index in range(3)
        )
        within_pos = all(
            abs(pos_error[index]) <= float(anchor.position_tolerance_mm[index])
            for index in range(3)
        )

        rot_error: tuple[float, float, float] | None = None
        within_rot = True
        if observed_rot_deg is not None:
            rot_error = tuple(
                _wrap_degrees(
                    float(observed_rot_deg[index]) - float(anchor.rot_deg[index])
                )
                for index in range(3)
            )
            if anchor.rotation_tolerance_deg is None:
                within_rot = all(abs(rot_error[index]) <= 1e-6 for index in range(3))
            else:
                within_rot = all(
                    abs(rot_error[index]) <= float(anchor.rotation_tolerance_deg[index])
                    for index in range(3)
                )
        elif anchor.rotation_tolerance_deg is None:
            within_rot = False

        return within_pos and within_rot, pos_error, rot_error

    def _expected_anchor_index(self, current_time_s: float) -> int:
        if not self._anchor_times_s:
            return 0
        return max(0, bisect_right(self._anchor_times_s, current_time_s) - 1)

    def _check_first_contact_order(
        self, current_contacts: Sequence[str], current_time_s: float
    ) -> tuple[bool, str | None]:
        if not self._required_first_contacts:
            return True, None

        for contact_name in current_contacts:
            if contact_name in self._seen_first_contacts:
                continue
            if contact_name not in self._required_first_contacts:
                continue

            expected_index = len(self._observed_first_contacts)
            if expected_index >= len(self._required_first_contacts):
                break

            expected = self._required_first_contacts[expected_index]
            if contact_name != expected:
                return (
                    False,
                    "payload trajectory first-contact order violated: "
                    f"expected {expected!r} before {contact_name!r}",
                )

            self._observed_first_contacts.append(contact_name)
            self._seen_first_contacts.add(contact_name)

        expected_index = len(self._observed_first_contacts)
        if expected_index >= len(self._required_first_contacts):
            return True, None

        expected_contact = self._required_first_contacts[expected_index]
        anchor_index = self._last_checked_anchor_index
        if anchor_index is None:
            anchor_index = 0
        anchor_time = self._anchor_times_s[
            min(anchor_index, len(self._anchor_times_s) - 1)
        ]
        if current_time_s > anchor_time + self._monitor_sample_stride_s:
            return (
                False,
                "payload trajectory required first-contact order is no longer "
                f"reachable: missing {expected_contact!r}",
            )

        return True, None

    def _build_state(
        self,
        *,
        consecutive_miss_count: int | None = None,
        observed_pos_mm: tuple[float, float, float] | None = None,
        observed_rot_deg: tuple[float, float, float] | None = None,
        position_error_mm: tuple[float, float, float] | None = None,
        rotation_error_deg: tuple[float, float, float] | None = None,
    ) -> PayloadTrajectoryMonitorState:
        return PayloadTrajectoryMonitorState(
            tracked_body_names=list(self.tracked_body_names),
            last_checked_anchor_index=self._last_checked_anchor_index,
            last_checked_anchor_t_s=(
                self._anchor_times_s[self._last_checked_anchor_index]
                if self._last_checked_anchor_index is not None and self._anchor_times_s
                else None
            ),
            monitor_sample_stride_s=self._monitor_sample_stride_s,
            configured_consecutive_miss_count=self._configured_consecutive_miss_count,
            consecutive_miss_count=(
                consecutive_miss_count
                if consecutive_miss_count is not None
                else self._last_state.consecutive_miss_count
            ),
            observed_position_mm=observed_pos_mm,
            observed_rotation_deg=observed_rot_deg,
            position_error_mm=position_error_mm,
            rotation_error_deg=rotation_error_deg,
            required_first_contacts=list(self._required_first_contacts),
            observed_first_contacts=list(self._observed_first_contacts),
            terminal_goal_zone_proven=self._terminal_goal_zone_proven,
        )

    def check(self, current_time_s: float) -> SimulationFailure | None:
        if not self.policy.enabled:
            return None
        if current_time_s + 1e-9 < self._next_check_time_s:
            return None

        self._next_check_time_s = current_time_s + self._monitor_sample_stride_s

        anchor_index = self._expected_anchor_index(current_time_s)
        anchor = self.payload_definition.anchors[anchor_index]
        self._last_checked_anchor_index = anchor_index

        observed_pos_mm, observed_rot_deg = self._sample_reference_pose()
        within_tolerance, pos_error_mm, rot_error_deg = (
            self._anchor_is_within_tolerance(
                anchor,
                observed_pos_mm,
                observed_rot_deg,
            )
        )

        current_contacts = self._current_contact_names()
        contact_ok, contact_failure = self._check_first_contact_order(
            current_contacts, current_time_s
        )

        goal_zone_required = anchor_index == len(
            self.payload_definition.anchors
        ) - 1 and (
            anchor.goal_zone_contact
            or anchor.goal_zone_entry
            or self.payload_definition.terminal_event is not None
        )
        goal_zone_proven = not goal_zone_required
        if goal_zone_required:
            candidate_bodies = self.tracked_body_names or (
                [self.target_body_name] if self.target_body_name else []
            )
            if self.goal_sites and candidate_bodies:
                goal_zone_proven = any(
                    self.backend.check_collision(body_name, goal_site)
                    for body_name in candidate_bodies
                    for goal_site in self.goal_sites
                )
            else:
                goal_zone_proven = False
        self._terminal_goal_zone_proven = bool(goal_zone_proven)

        miss_count = self._last_state.consecutive_miss_count
        if not within_tolerance:
            miss_count += 1
        else:
            miss_count = 0

        self._last_state = self._build_state(
            consecutive_miss_count=miss_count,
            observed_pos_mm=observed_pos_mm,
            observed_rot_deg=observed_rot_deg,
            position_error_mm=pos_error_mm,
            rotation_error_deg=rot_error_deg,
        )

        if not contact_ok:
            detail = contact_failure or "payload trajectory contact order violated"
            self._last_state.failure_detail = detail
            return SimulationFailure(
                reason=FailureReason.PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION,
                detail=detail,
                payload_trajectory_monitor=self._last_state,
            )

        if (
            not within_tolerance
            and miss_count >= self._configured_consecutive_miss_count
        ):
            detail = (
                "payload trajectory anchor deviation exceeded consecutive miss "
                f"threshold at anchor index {anchor_index}"
            )
            self._last_state.failure_detail = detail
            return SimulationFailure(
                reason=FailureReason.PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION,
                detail=detail,
                payload_trajectory_monitor=self._last_state,
            )

        if goal_zone_required and not goal_zone_proven:
            detail = (
                "payload trajectory terminal goal-zone state is no longer "
                "reachable from the current simulation state"
            )
            self._last_state.failure_detail = detail
            return SimulationFailure(
                reason=FailureReason.PAYLOAD_TRAJECTORY_CONTRACT_VIOLATION,
                detail=detail,
                payload_trajectory_monitor=self._last_state,
            )

        self._last_state.failure_detail = None
        return None
