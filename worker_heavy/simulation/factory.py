from pathlib import Path

import structlog

from shared.simulation.backends import PhysicsBackend
from shared.simulation.schemas import (
    SimulatorBackendType,
    get_default_simulator_backend,
)

logger = structlog.get_logger(__name__)

# Global cache for session-isolated backends
# session_id -> backend_type -> PhysicsBackend
BACKEND_CACHE: dict[str, dict[SimulatorBackendType, PhysicsBackend]] = {}
MAX_ACTIVE_SESSIONS = 4


def get_physics_backend(
    backend_type: SimulatorBackendType,
    session_id: str | None = None,
    smoke_test_mode: bool | None = None,
    particle_budget: int | None = None,
) -> PhysicsBackend:
    """
    Returns a physics backend instance.
    If session_id is provided, it returns a cached instance for that session
    or creates a new one if not present (subject to MAX_ACTIVE_SESSIONS).
    """
    if not session_id:
        # Legacy behavior or one-off runs
        return _create_backend(
            backend_type,
            smoke_test_mode=smoke_test_mode,
            particle_budget=particle_budget,
            session_id=session_id,
        )

    from worker_heavy.config import settings

    if smoke_test_mode is None:
        smoke_test_mode = settings.smoke_test_mode

    session_cache = BACKEND_CACHE.get(session_id)
    if session_cache and backend_type in session_cache:
        logger.debug(
            "backend_cache_hit", session_id=session_id, backend_type=backend_type
        )
        backend = session_cache[backend_type]
        if hasattr(backend, "smoke_test_mode"):
            backend.smoke_test_mode = smoke_test_mode
        return backend

    # Enforce session limit
    if session_id not in BACKEND_CACHE and len(BACKEND_CACHE) >= MAX_ACTIVE_SESSIONS:
        # Evict oldest session (simple FIFO for now)
        oldest_sid = next(iter(BACKEND_CACHE))
        logger.info("evicting_oldest_session", session_id=oldest_sid)
        close_session_backend(oldest_sid)

    logger.info(
        "creating_new_session_backend", session_id=session_id, backend_type=backend_type
    )
    backend = _create_backend(
        backend_type,
        smoke_test_mode=smoke_test_mode,
        particle_budget=particle_budget,
        session_id=session_id,
    )
    session_cache = BACKEND_CACHE.setdefault(session_id, {})
    session_cache[backend_type] = backend
    return backend


def _create_backend(
    backend_type: SimulatorBackendType,
    smoke_test_mode: bool = False,
    particle_budget: int | None = None,
    session_id: str | None = None,
) -> PhysicsBackend:
    if backend_type == SimulatorBackendType.MUJOCO:
        from worker_heavy.simulation.mujoco_backend import MuJoCoBackend

        backend = MuJoCoBackend(session_id=session_id)
        backend.smoke_test_mode = smoke_test_mode
        return backend
    if backend_type == SimulatorBackendType.GENESIS:
        from worker_heavy.simulation.genesis_backend import GenesisBackend

        backend = GenesisBackend(session_id=session_id)
        backend.smoke_test_mode = smoke_test_mode
        # Trigger re-init if needed with correct mode
        if hasattr(backend, "_ensure_initialized"):
            backend._ensure_initialized()
        return backend
    raise ValueError(f"Unknown backend type: {backend_type}")


def get_simulation_builder(
    output_dir: Path,
    backend_type: SimulatorBackendType | None = None,
    use_vhacd: bool = False,
):
    from worker_heavy.simulation.builder import (
        GenesisSimulationBuilder,
        MuJoCoSimulationBuilder,
    )

    resolved_backend_type = backend_type or get_default_simulator_backend()
    if resolved_backend_type == SimulatorBackendType.MUJOCO:
        return MuJoCoSimulationBuilder(output_dir, use_vhacd)
    if resolved_backend_type == SimulatorBackendType.GENESIS:
        return GenesisSimulationBuilder(output_dir, use_vhacd)
    raise ValueError(f"Unknown backend type: {resolved_backend_type}")


def close_session_backend(session_id: str):
    """Explicitly close and remove a backend from cache."""
    session_cache = BACKEND_CACHE.pop(session_id, None)
    if session_cache:
        for backend_type, backend in session_cache.items():
            try:
                backend.close()
                logger.info(
                    "session_backend_closed",
                    session_id=session_id,
                    backend_type=backend_type,
                )
            except Exception as e:
                logger.warning(
                    "backend_close_failed",
                    session_id=session_id,
                    backend_type=backend_type,
                    error=str(e),
                )
        return


def close_all_session_backends() -> int:
    """Close and clear all cached session backends."""
    closed_count = 0
    for session_id in list(BACKEND_CACHE.keys()):
        session_cache = BACKEND_CACHE.pop(session_id)
        for backend_type, backend in session_cache.items():
            try:
                backend.close()
                closed_count += 1
                logger.info(
                    "session_backend_closed",
                    session_id=session_id,
                    backend_type=backend_type,
                )
            except Exception as e:
                logger.warning(
                    "backend_close_failed",
                    session_id=session_id,
                    backend_type=backend_type,
                    error=str(e),
                )
    return closed_count
