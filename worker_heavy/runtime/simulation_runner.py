import asyncio
import gc
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import structlog

from shared.enums import FailureReason
from shared.models.simulation import SimulationFailure, SimulationResult
from worker_heavy.simulation.factory import close_all_session_backends
from worker_heavy.utils.validation import (
    save_simulation_result,
    simulate_subprocess,
    validate_subprocess,
)

logger = structlog.get_logger(__name__)

_SPAWN_CONTEXT = multiprocessing.get_context("spawn")
# Full simulation runs can include physics stepping, 24-view prerenders, and mp4
# encoding. Keep a stricter budget than the client timeout, but leave enough
# headroom for non-smoke artifact-producing runs.
_SIMULATION_WALL_CLOCK_TIMEOUT_SECONDS = 120.0


class SimulationExecutorOperationTimeoutError(RuntimeError):
    """Raised when the isolated simulation child exceeds its wall-clock budget."""

    def __init__(self, *, operation: str, timeout_seconds: float):
        self.operation = operation
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"{operation} child exceeded {timeout_seconds:.1f}s wall-clock timeout"
        )


@dataclass(frozen=True)
class SimulationExecutorCleanupResult:
    had_executor: bool
    child_closed_backends: int
    child_gc_collected: int
    executor_reset: bool


def cleanup_simulation_child_state() -> tuple[int, int]:
    """Clear child-local cached backends while keeping the warm process alive."""
    closed_backends = close_all_session_backends()
    gc_collected = gc.collect()
    return closed_backends, gc_collected


def _shutdown_broken_executor(
    executor: ProcessPoolExecutor,
    *,
    generation: int,
    operation: str,
    reason: str,
) -> None:
    """Best-effort teardown of a stuck/broken worker child."""
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.warning(
            "simulation_executor_shutdown_failed",
            generation=generation,
            operation=operation,
            reason=reason,
        )

    processes = getattr(executor, "_processes", None) or {}
    for process in list(processes.values()):
        if process is None or not process.is_alive():
            continue
        try:
            process.terminate()
        except Exception:
            logger.warning(
                "simulation_executor_terminate_failed",
                generation=generation,
                operation=operation,
                reason=reason,
                pid=getattr(process, "pid", None),
            )

    for process in list(processes.values()):
        if process is None:
            continue
        try:
            process.join(timeout=1.0)
        except Exception:
            logger.warning(
                "simulation_executor_join_failed",
                generation=generation,
                operation=operation,
                reason=reason,
                pid=getattr(process, "pid", None),
            )

    for process in list(processes.values()):
        if process is None or not process.is_alive():
            continue
        try:
            process.kill()
        except Exception:
            logger.warning(
                "simulation_executor_kill_failed",
                generation=generation,
                operation=operation,
                reason=reason,
                pid=getattr(process, "pid", None),
            )


class SimulationExecutorManager:
    """Own the long-lived spawned child used by simulate and validate."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._executor: ProcessPoolExecutor | None = None
        self._generation = 0
        self._recreate_after_crash = False

    def _get_or_create_executor_locked(
        self,
    ) -> tuple[ProcessPoolExecutor, int, bool, bool]:
        if self._executor is not None:
            return self._executor, self._generation, False, False

        self._generation += 1
        generation = self._generation
        self._executor = ProcessPoolExecutor(
            max_workers=1,
            mp_context=_SPAWN_CONTEXT,
        )
        recreated = self._recreate_after_crash
        self._recreate_after_crash = False
        return self._executor, generation, True, recreated

    def _mark_broken_locked(self) -> tuple[ProcessPoolExecutor | None, int]:
        executor = self._executor
        generation = self._generation
        self._executor = None
        self._recreate_after_crash = True
        return executor, generation

    async def submit(
        self,
        operation: str,
        crash_message: str,
        fn: Any,
        *args: Any,
        timeout_seconds: float | None = None,
    ) -> Any:
        loop = asyncio.get_running_loop()
        with self._lock:
            executor, generation, created, recreated = (
                self._get_or_create_executor_locked()
            )

        if created and recreated:
            logger.info(
                "simulation_executor_recreated",
                generation=generation,
                operation=operation,
            )
        elif created:
            logger.info(
                "simulation_executor_started",
                generation=generation,
                operation=operation,
            )
        else:
            logger.info(
                "simulation_executor_reused",
                generation=generation,
                operation=operation,
            )

        try:
            future = loop.run_in_executor(executor, fn, *args)
            if timeout_seconds is None:
                return await future
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as exc:
            with self._lock:
                broken_executor, broken_generation = self._mark_broken_locked()
            if broken_executor is not None:
                await asyncio.to_thread(
                    _shutdown_broken_executor,
                    broken_executor,
                    generation=broken_generation,
                    operation=operation,
                    reason="timeout",
                )
            logger.error(
                "simulation_executor_timeout",
                generation=broken_generation,
                operation=operation,
                timeout_seconds=timeout_seconds,
            )
            raise SimulationExecutorOperationTimeoutError(
                operation=operation,
                timeout_seconds=timeout_seconds,
            ) from exc
        except BrokenProcessPool as exc:
            with self._lock:
                broken_executor, broken_generation = self._mark_broken_locked()
            if broken_executor is not None:
                await asyncio.to_thread(
                    _shutdown_broken_executor,
                    broken_executor,
                    generation=broken_generation,
                    operation=operation,
                    reason="crash",
                )
            logger.error(
                "simulation_child_process_crashed",
                error=str(exc),
                generation=broken_generation,
                operation=operation,
            )
            logger.error(
                "simulation_executor_crashed",
                error=str(exc),
                generation=broken_generation,
                operation=operation,
            )
            raise RuntimeError(crash_message) from exc

    async def cleanup(self) -> SimulationExecutorCleanupResult:
        loop = asyncio.get_running_loop()
        with self._lock:
            executor = self._executor
            generation = self._generation

        if executor is None:
            return SimulationExecutorCleanupResult(
                had_executor=False,
                child_closed_backends=0,
                child_gc_collected=0,
                executor_reset=False,
            )

        try:
            closed_backends, gc_collected = await loop.run_in_executor(
                executor,
                cleanup_simulation_child_state,
            )
            logger.info(
                "simulation_executor_cleanup",
                generation=generation,
                child_closed_backends=closed_backends,
                child_gc_collected=gc_collected,
            )
            return SimulationExecutorCleanupResult(
                had_executor=True,
                child_closed_backends=closed_backends,
                child_gc_collected=gc_collected,
                executor_reset=False,
            )
        except BrokenProcessPool as exc:
            with self._lock:
                broken_executor, broken_generation = self._mark_broken_locked()
            if broken_executor is not None:
                try:
                    broken_executor.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    logger.warning(
                        "simulation_executor_shutdown_after_cleanup_crash_failed",
                        generation=broken_generation,
                    )
            logger.error(
                "simulation_executor_crashed",
                error=str(exc),
                generation=broken_generation,
                operation="cleanup",
            )
            return SimulationExecutorCleanupResult(
                had_executor=True,
                child_closed_backends=0,
                child_gc_collected=0,
                executor_reset=True,
            )

    async def shutdown(self) -> bool:
        with self._lock:
            executor = self._executor
            generation = self._generation
            self._executor = None

        if executor is None:
            return False

        logger.info("simulation_executor_shutdown", generation=generation)
        await asyncio.to_thread(
            lambda: executor.shutdown(wait=True, cancel_futures=True)
        )
        return True


_SIMULATION_EXECUTOR_MANAGER = SimulationExecutorManager()


async def cleanup_simulation_executor() -> SimulationExecutorCleanupResult:
    return await _SIMULATION_EXECUTOR_MANAGER.cleanup()


async def shutdown_simulation_executor() -> bool:
    return await _SIMULATION_EXECUTOR_MANAGER.shutdown()


async def run_simulation_in_isolated_process(
    *,
    script_path: str | Path,
    session_root: str | Path,
    script_content: str | None,
    output_dir: Path,
    smoke_test_mode: bool,
    backend: Any,
    session_id: str,
    episode_id: str | None,
    stream_render_frames: bool,
    skip_preview_rendering: bool = False,
    particle_budget: int | None,
) -> SimulationResult:
    """
    Run one simulation task in the persistent spawned child process.

    The parent process remains isolated from heavy physics calls, while the
    child process stays warm across requests until crash or shutdown.
    """
    try:
        return await _SIMULATION_EXECUTOR_MANAGER.submit(
            "simulate",
            "SIMULATION_CHILD_PROCESS_CRASHED",
            simulate_subprocess,
            script_path,
            session_root,
            script_content,
            output_dir,
            smoke_test_mode,
            backend,
            session_id,
            episode_id,
            stream_render_frames,
            skip_preview_rendering,
            particle_budget,
            timeout_seconds=_SIMULATION_WALL_CLOCK_TIMEOUT_SECONDS,
        )
    except SimulationExecutorOperationTimeoutError:
        timeout_result = SimulationResult(
            success=False,
            summary=(
                "Simulation timed out after "
                f"{_SIMULATION_WALL_CLOCK_TIMEOUT_SECONDS:.0f}s wall-clock."
            ),
            failure=SimulationFailure(
                reason=FailureReason.TIMEOUT,
                detail=(
                    "simulate child exceeded "
                    f"{_SIMULATION_WALL_CLOCK_TIMEOUT_SECONDS:.0f}s wall-clock "
                    "timeout"
                ),
            ),
        )
        try:
            save_simulation_result(
                timeout_result, output_dir / "simulation_result.json"
            )
        except Exception as exc:
            logger.error(
                "failed_to_save_timeout_simulation_result",
                error=str(exc),
                session_id=session_id,
            )
        return timeout_result


async def run_validation_in_isolated_process(
    *,
    script_path: str | Path,
    session_root: str | Path,
    script_content: str | None,
    output_dir: Path,
    smoke_test_mode: bool,
    session_id: str,
    skip_preview_rendering: bool = False,
    particle_budget: int | None,
) -> tuple[bool, str | None]:
    """
    Run one validation task in the persistent spawned child process.

    Validation shares the same warm child/runtime path as simulation while
    preserving parent-process crash containment.
    """
    return await _SIMULATION_EXECUTOR_MANAGER.submit(
        "validate",
        "VALIDATION_CHILD_PROCESS_CRASHED",
        validate_subprocess,
        script_path,
        session_root,
        script_content,
        output_dir,
        smoke_test_mode,
        session_id,
        particle_budget,
    )
