import numpy as np
import structlog

from shared.enums import FailureReason as SimulationFailureMode
from shared.models.schemas import BoundingBox

logger = structlog.get_logger(__name__)


class SuccessEvaluator:
    """Evaluates simulation success or failure conditions."""

    def __init__(
        self,
        max_simulation_time: float,
        simulation_bounds: BoundingBox | None = None,
        session_id: str | None = None,
    ):
        self.max_simulation_time = max_simulation_time
        self.simulation_bounds = simulation_bounds
        self.session_id = session_id

    def check_failure(
        self,
        total_time: float,
        qpos: np.ndarray,
        qvel: np.ndarray,
        contacts: list | None = None,
    ) -> SimulationFailureMode | None:
        """
        Check for various failure modes.
        Returns failure reason or None if still running.
        """
        # 1. Timeout
        if total_time >= self.max_simulation_time:
            logger.info(
                "timeout_triggered",
                total_time=total_time,
                max_simulation_time=self.max_simulation_time,
                session_id=self.session_id,
            )
            return SimulationFailureMode.TIMEOUT

        # 2. Physics Instability (NaNs or extreme values)
        if qpos is not None:
            if np.any(np.isnan(qpos)) or (qvel is not None and np.any(np.isnan(qvel))):
                return SimulationFailureMode.PHYSICS_INSTABILITY

            # Extreme values (explosion)
            if np.any(np.abs(qpos) > 10000.0):
                logger.error(
                    "physics_explosion_detected",
                    pos=list(qpos),
                    session_id=self.session_id,
                )
                return SimulationFailureMode.PHYSICS_INSTABILITY

        # 3. Fell off world / Out of Bounds
        if qpos is not None and len(qpos) >= 3:
            # Always prioritize simulation_bounds if provided
            if self.simulation_bounds:
                b_min = np.array(self.simulation_bounds.min_mm)
                b_max = np.array(self.simulation_bounds.max_mm)
                if np.any(qpos < b_min) or np.any(qpos > b_max):
                    return SimulationFailureMode.OUT_OF_BOUNDS
            else:
                # Default safety bounds if none specified (prevents infinite falls)
                # We use a broad range but catch anything falling significantly below floor (z=0)
                if qpos[2] < -5.0 or np.any(np.abs(qpos[:2]) > 500.0):
                    return SimulationFailureMode.OUT_OF_BOUNDS

        return None

    def is_in_zone(
        self, pos: np.ndarray, zone_pos: np.ndarray, zone_size: np.ndarray
    ) -> bool:
        """Check if a position is within a box zone."""
        return np.all(np.abs(pos - zone_pos) <= zone_size)
