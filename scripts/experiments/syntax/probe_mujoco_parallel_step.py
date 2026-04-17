#!/usr/bin/env python3
"""Probe how MuJoCo parallel stepping is actually exposed.

This experiment keeps the question narrow:

1. Does the installed MuJoCo wheel accept `mj_step(..., nstep=...)`?
2. Does `mujoco.rollout` expose the official batched parallel rollout path?
3. Does the rollout API reuse an internal thread pool when requested?

The goal is to separate three different costs:

1. Python-loop overhead for a single trajectory.
2. Python-loop overhead for a batch of independent trajectories.
3. Batch rollout throughput with and without MuJoCo-managed pool reuse.
"""

from __future__ import annotations

import argparse
import inspect
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import mujoco


DEFAULT_MODEL_PATH = Path("tests/worker/minimal.xml")
LATEST_JSON = Path(__file__).with_name("latest-mujoco-parallel-step.json")


@dataclass(frozen=True)
class TimingSummary:
    name: str
    repetitions: int
    values_s: list[float]
    mean_s: float
    median_s: float
    min_s: float
    max_s: float


def _summary(name: str, values: list[float]) -> TimingSummary:
    return TimingSummary(
        name=name,
        repetitions=len(values),
        values_s=values,
        mean_s=statistics.mean(values),
        median_s=statistics.median(values),
        min_s=min(values),
        max_s=max(values),
    )


def _reset_data(model: mujoco.MjModel) -> mujoco.MjData:
    data = mujoco.MjData(model)
    mujoco.mj_resetData(model, data)
    mujoco.mj_forward(model, data)
    return data


def _state_vector(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    nstate = mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_FULLPHYSICS.value)
    state = np.empty(nstate, dtype=np.float64)
    mujoco.mj_getState(model, data, state, mujoco.mjtState.mjSTATE_FULLPHYSICS.value)
    return state


def _load_model(model_path: Path) -> mujoco.MjModel:
    if not model_path.exists():
        raise FileNotFoundError(model_path)
    return mujoco.MjModel.from_xml_path(str(model_path))


def _measure(
    name: str, values_fn: Callable[[], float], repetitions: int
) -> TimingSummary:
    values: list[float] = []
    for _ in range(repetitions):
        t0 = time.perf_counter()
        values_fn()
        values.append(time.perf_counter() - t0)
    return _summary(name, values)


def _run_single_scene_loop(model: mujoco.MjModel, steps: int) -> float:
    data = _reset_data(model)
    for _ in range(steps):
        mujoco.mj_step(model, data)
    return float(data.time)


def _run_single_scene_nstep(model: mujoco.MjModel, steps: int) -> float:
    data = _reset_data(model)
    mujoco.mj_step(model, data, nstep=steps)
    return float(data.time)


def _batch_initial_state(model: mujoco.MjModel, batch_size: int) -> np.ndarray:
    base_state = _state_vector(model, _reset_data(model))
    return np.repeat(base_state[None, :], batch_size, axis=0)


def _run_batched_python_loop(model: mujoco.MjModel, batch_size: int, steps: int) -> float:
    datas = [_reset_data(model) for _ in range(batch_size)]
    for _ in range(steps):
        for data in datas:
            mujoco.mj_step(model, data)
    return float(datas[-1].time)


def _run_batched_rollout(
    model: mujoco.MjModel,
    batch_size: int,
    nthread: int,
    steps: int,
    *,
    persistent_pool: bool,
) -> dict[str, Any]:
    import mujoco.rollout as rollout_module

    datas = [_reset_data(model) for _ in range(nthread)]
    initial_state = _batch_initial_state(model, batch_size)
    state, sensordata = rollout_module.rollout(
        model,
        datas,
        initial_state,
        nstep=steps,
        persistent_pool=persistent_pool,
    )

    return {
        "state_shape": list(state.shape),
        "sensordata_shape": list(sensordata.shape),
        "final_time": float(state[0, -1, 0]) if state.size else None,
    }


def _run_batched_rollout_object(
    model: mujoco.MjModel, batch_size: int, nthread: int, steps: int
) -> dict[str, Any]:
    import mujoco.rollout as rollout_module

    datas = [_reset_data(model) for _ in range(nthread)]
    initial_state = _batch_initial_state(model, batch_size)

    with rollout_module.Rollout(nthread=nthread) as rollout:
        state, sensordata = rollout.rollout(model, datas, initial_state, nstep=steps)

    return {
        "state_shape": list(state.shape),
        "sensordata_shape": list(sensordata.shape),
        "final_time": float(state[0, -1, 0]) if state.size else None,
    }


def inspect_runtime(model: mujoco.MjModel, model_path: Path) -> dict[str, Any]:
    api_probe: dict[str, Any] = {
        "mujoco_version": getattr(mujoco, "__version__", "unknown"),
        "model_path": str(model_path),
        "mj_step_supports_nstep": False,
        "mj_step_nstep_probe_error": None,
        "rollout_module_available": False,
        "rollout_signature": None,
        "rollout_class_signature": None,
    }

    single_data = _reset_data(model)
    try:
        mujoco.mj_step(model, single_data, nstep=1)
        api_probe["mj_step_supports_nstep"] = True
    except Exception as exc:  # pragma: no cover - runtime feature probe
        api_probe["mj_step_nstep_probe_error"] = f"{type(exc).__name__}: {exc}"

    try:
        import mujoco.rollout as rollout_module

        api_probe["rollout_module_available"] = True
        api_probe["rollout_signature"] = str(inspect.signature(rollout_module.rollout))
        api_probe["rollout_class_signature"] = str(
            inspect.signature(rollout_module.Rollout)
        )
    except Exception as exc:  # pragma: no cover - runtime feature probe
        api_probe["rollout_module_error"] = f"{type(exc).__name__}: {exc}"

    nstate = mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_FULLPHYSICS.value)
    api_probe["fullphysics_state_size"] = int(nstate)
    api_probe["nq"] = int(model.nq)
    api_probe["nv"] = int(model.nv)
    api_probe["nbody"] = int(model.nbody)
    api_probe["ngeom"] = int(model.ngeom)

    return api_probe


def run_experiment(
    model_path: Path,
    batch_size: int,
    steps: int,
    repetitions: int,
    workers: int,
) -> dict[str, Any]:
    model = _load_model(model_path)

    nthread = max(1, min(workers, batch_size))

    single_loop = _measure(
        "single_scene_loop",
        lambda: _run_single_scene_loop(model, steps),
        repetitions,
    )

    single_nstep = _measure(
        "single_scene_nstep",
        lambda: _run_single_scene_nstep(model, steps),
        repetitions,
    )

    batched_python_loop = _measure(
        "batched_python_loop",
        lambda: _run_batched_python_loop(model, batch_size, steps),
        repetitions,
    )

    rollout_fresh_pool: TimingSummary | None = None
    rollout_fresh_pool_probe: dict[str, Any] | None = None
    rollout_persistent_pool: TimingSummary | None = None
    rollout_persistent_pool_probe: dict[str, Any] | None = None
    rollout_object: TimingSummary | None = None
    rollout_object_probe: dict[str, Any] | None = None

    try:
        rollout_fresh_pool = _measure(
            "rollout_fresh_pool",
            lambda: _run_batched_rollout(
                model,
                batch_size,
                nthread,
                steps,
                persistent_pool=False,
            ),
            repetitions,
        )
        rollout_fresh_pool_probe = _run_batched_rollout(
            model,
            batch_size,
            nthread,
            steps,
            persistent_pool=False,
        )
    except Exception as exc:  # pragma: no cover - runtime feature probe
        rollout_fresh_pool_probe = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        rollout_persistent_pool = _measure(
            "rollout_persistent_pool",
            lambda: _run_batched_rollout(
                model,
                batch_size,
                nthread,
                steps,
                persistent_pool=True,
            ),
            repetitions,
        )
        rollout_persistent_pool_probe = _run_batched_rollout(
            model,
            batch_size,
            nthread,
            steps,
            persistent_pool=True,
        )
    except Exception as exc:  # pragma: no cover - runtime feature probe
        rollout_persistent_pool_probe = {
            "error": f"{type(exc).__name__}: {exc}"
        }

    try:
        rollout_object = _measure(
            "rollout_object",
            lambda: _run_batched_rollout_object(model, batch_size, nthread, steps),
            repetitions,
        )
        rollout_object_probe = _run_batched_rollout_object(
            model,
            batch_size,
            nthread,
            steps,
        )
    except Exception as exc:  # pragma: no cover - runtime feature probe
        rollout_object_probe = {"error": f"{type(exc).__name__}: {exc}"}

    summary = {
        "single_scene_speedup_nstep_vs_loop": (
            single_loop.mean_s / single_nstep.mean_s if single_nstep.mean_s else None
        ),
        "rollout_fresh_pool_speedup_vs_python_loop": (
            batched_python_loop.mean_s / rollout_fresh_pool.mean_s
            if rollout_fresh_pool and rollout_fresh_pool.mean_s
            else None
        ),
        "rollout_persistent_pool_speedup_vs_python_loop": (
            batched_python_loop.mean_s / rollout_persistent_pool.mean_s
            if rollout_persistent_pool and rollout_persistent_pool.mean_s
            else None
        ),
        "rollout_object_speedup_vs_python_loop": (
            batched_python_loop.mean_s / rollout_object.mean_s
            if rollout_object and rollout_object.mean_s
            else None
        ),
    }

    return {
        "probe_name": "mujoco_parallel_step_probe",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model_path": str(model_path),
        "batch_size": batch_size,
        "steps": steps,
        "nthread": nthread,
        "api_probe": inspect_runtime(model, model_path),
        "timings": {
            "single_scene_loop": single_loop.__dict__,
            "single_scene_nstep": single_nstep.__dict__,
            "batched_python_loop": batched_python_loop.__dict__,
            "rollout_fresh_pool": rollout_fresh_pool.__dict__
            if rollout_fresh_pool
            else None,
            "rollout_persistent_pool": rollout_persistent_pool.__dict__
            if rollout_persistent_pool
            else None,
            "rollout_object": rollout_object.__dict__ if rollout_object else None,
        },
        "rollout_probe": {
            "fresh_pool": rollout_fresh_pool_probe,
            "persistent_pool": rollout_persistent_pool_probe,
            "object": rollout_object_probe,
        },
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-path",
        default=str(DEFAULT_MODEL_PATH),
        help="MuJoCo XML model to load for the probe.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Number of independent trajectories in the batch.",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=2000,
        help="Number of MuJoCo steps per repetition.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Number of timing repetitions per mode.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Thread pool width for the threaded and rollout probes.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional output path for the JSON report.",
    )
    args = parser.parse_args()

    report = run_experiment(
        model_path=Path(args.model_path),
        batch_size=args.batch_size,
        steps=args.steps,
        repetitions=args.repetitions,
        workers=args.workers,
    )

    output_path = args.output_json.strip()
    if not output_path:
        output_path = LATEST_JSON.as_posix()

    Path(output_path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
