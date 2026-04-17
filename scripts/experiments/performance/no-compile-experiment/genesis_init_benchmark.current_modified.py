#!/usr/bin/env python3
"""Benchmark Genesis initialization and reuse semantics.

This script answers two practical questions:
1. What is the cost of paying Genesis init on every spawned process?
2. Can one Genesis init be reused within a single process across threads?

The benchmark keeps the workload tiny on purpose so the timings are dominated
by process startup, Genesis init, and first scene build.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from typing import Any


def _configure_headless_env() -> None:
    cache_root = "/tmp/codex-genesis-benchmark"
    home_root = os.path.join(cache_root, "home")
    xdg_cache_root = os.path.join(cache_root, "xdg-cache")
    os.makedirs(home_root, exist_ok=True)
    os.makedirs(xdg_cache_root, exist_ok=True)

    os.environ["PYGLET_HEADLESS"] = "1"
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("HOME", home_root)
    os.environ.setdefault("XDG_CACHE_HOME", xdg_cache_root)


@dataclass
class Measurement:
    name: str
    rounds: int
    values_s: list[float]
    mean_s: float
    median_s: float
    min_s: float
    max_s: float


def _summary(name: str, values: list[float]) -> Measurement:
    return Measurement(
        name=name,
        rounds=len(values),
        values_s=values,
        mean_s=statistics.mean(values),
        median_s=statistics.median(values),
        min_s=min(values),
        max_s=max(values),
    )


def _resolve_backend(gs: Any, backend_name: str):
    if backend_name == "cpu":
        return gs.cpu, "cpu"
    if backend_name == "gpu":
        return gs.gpu, "gpu"
    if backend_name != "auto":
        raise ValueError(f"Unsupported backend: {backend_name}")

    import torch

    force_cpu = os.getenv("GENESIS_FORCE_CPU", "0") == "1"
    has_gpu = torch.cuda.is_available() and not force_cpu
    return (gs.gpu if has_gpu else gs.cpu), ("gpu" if has_gpu else "cpu")


def _tiny_scene_round(gs: Any) -> dict[str, float]:
    scene_create_t0 = time.perf_counter()
    scene = gs.Scene(show_viewer=False)
    scene.add_entity(gs.morphs.Plane())
    scene_create_s = time.perf_counter() - scene_create_t0

    build_t0 = time.perf_counter()
    compile_kernels = os.getenv("GENESIS_BENCH_COMPILE_KERNELS", "").strip().lower()
    build_kwargs: dict[str, bool] = {}
    if compile_kernels in {"true", "false"}:
        sig = inspect.signature(scene.build)
        if "compile_kernels" in sig.parameters:
            build_kwargs["compile_kernels"] = compile_kernels == "true"
    scene.build(**build_kwargs)
    build_s = time.perf_counter() - build_t0

    step_t0 = time.perf_counter()
    scene.step()
    step_s = time.perf_counter() - step_t0

    return {
        "scene_create_s": scene_create_s,
        "scene_build_s": build_s,
        "scene_step_s": step_s,
    }


def _child_measure(backend_name: str, include_scene: bool) -> dict[str, Any]:
    _configure_headless_env()
    started_at = time.perf_counter()
    try:
        import genesis as gs

        backend, resolved_backend = _resolve_backend(gs, backend_name)

        init_t0 = time.perf_counter()
        gs.init(backend=backend, logging_level="warning")
        init_s = time.perf_counter() - init_t0

        payload = {
            "ok": True,
            "backend": resolved_backend,
            "init_s": init_s,
            "process_work_s": time.perf_counter() - started_at,
        }
        if include_scene:
            payload.update(_tiny_scene_round(gs))
            payload["process_work_s"] = time.perf_counter() - started_at
        return payload
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "process_work_s": time.perf_counter() - started_at,
        }


def _run_child_subprocess(
    *,
    child_mode: str,
    backend_name: str,
    include_scene: bool = False,
    rounds: int | None = None,
    compile_kernels: str = "auto",
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="genesis-bench-",
        dir="/tmp",
        delete=False,
    ) as tmp:
        output_path = tmp.name

    cmd = [
        sys.executable,
        __file__,
        "--child-mode",
        child_mode,
        "--backend",
        backend_name,
        "--output-json",
        output_path,
        "--compile-kernels",
        compile_kernels,
    ]
    if include_scene:
        cmd.append("--include-scene")
    if rounds is not None:
        cmd.extend(["--rounds", str(rounds)])

    child_env = os.environ.copy()
    if compile_kernels in {"true", "false"}:
        child_env["GENESIS_BENCH_COMPILE_KERNELS"] = compile_kernels
    else:
        child_env.pop("GENESIS_BENCH_COMPILE_KERNELS", None)

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=child_env,
    )
    try:
        with open(output_path, encoding="utf-8") as fh:
            payload = json.load(fh)
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass

    if proc.returncode != 0:
        raise RuntimeError(
            "Child subprocess failed "
            f"(returncode={proc.returncode}). stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
    return payload


def _run_spawned_rounds(
    rounds: int, backend_name: str, include_scene: bool, compile_kernels: str = "auto"
) -> dict[str, Any]:
    wall_times: list[float] = []
    init_times: list[float] = []
    process_work_times: list[float] = []
    build_times: list[float] = []
    create_times: list[float] = []
    step_times: list[float] = []
    resolved_backend = None

    for index in range(rounds):
        wall_t0 = time.perf_counter()
        payload = _run_child_subprocess(
            child_mode="spawned",
            backend_name=backend_name,
            include_scene=include_scene,
            compile_kernels=compile_kernels,
        )
        wall_s = time.perf_counter() - wall_t0
        wall_times.append(wall_s)
        if not payload.get("ok"):
            raise RuntimeError(
                f"Child round {index} failed: {payload['error']}\n{payload['traceback']}"
            )

        resolved_backend = payload["backend"]
        init_times.append(payload["init_s"])
        process_work_times.append(payload["process_work_s"])
        if include_scene:
            create_times.append(payload["scene_create_s"])
            build_times.append(payload["scene_build_s"])
            step_times.append(payload["scene_step_s"])

    result = {
        "resolved_backend": resolved_backend,
        "wall_process_roundtrip": asdict(
            _summary("wall_process_roundtrip", wall_times)
        ),
        "child_init_only": asdict(_summary("child_init_only", init_times)),
        "child_total_work": asdict(_summary("child_total_work", process_work_times)),
    }
    if include_scene:
        result["child_scene_create"] = asdict(
            _summary("child_scene_create", create_times)
        )
        result["child_scene_build"] = asdict(_summary("child_scene_build", build_times))
        result["child_scene_step"] = asdict(_summary("child_scene_step", step_times))
    return result


def _same_process_reuse_child(rounds: int, backend_name: str) -> dict[str, Any]:
    _configure_headless_env()
    import genesis as gs

    backend, resolved_backend = _resolve_backend(gs, backend_name)

    init_t0 = time.perf_counter()
    gs.init(backend=backend, logging_level="warning")
    init_s = time.perf_counter() - init_t0

    scene_create_times: list[float] = []
    scene_build_times: list[float] = []
    scene_step_times: list[float] = []
    second_init_s: float | None = None
    second_init_error: str | None = None

    for _ in range(rounds):
        timings = _tiny_scene_round(gs)
        scene_create_times.append(timings["scene_create_s"])
        scene_build_times.append(timings["scene_build_s"])
        scene_step_times.append(timings["scene_step_s"])

    second_init_t0 = time.perf_counter()
    try:
        gs.init(backend=backend, logging_level="warning")
        second_init_s = time.perf_counter() - second_init_t0
    except Exception as exc:
        second_init_error = f"{type(exc).__name__}: {exc}"

    return {
        "resolved_backend": resolved_backend,
        "first_init_s": init_s,
        "reuse_scene_create": asdict(
            _summary("reuse_scene_create", scene_create_times)
        ),
        "reuse_scene_build": asdict(_summary("reuse_scene_build", scene_build_times)),
        "reuse_scene_step": asdict(_summary("reuse_scene_step", scene_step_times)),
        "second_init_s": second_init_s,
        "second_init_error": second_init_error,
        "gs_initialized_flag": bool(getattr(gs, "_initialized", False)),
    }


def _thread_scene_worker(
    result: dict[str, Any], backend_name: str, do_init: bool, compile_kernels: str
) -> None:
    try:
        _configure_headless_env()
        import genesis as gs

        if compile_kernels in {"true", "false"}:
            os.environ["GENESIS_BENCH_COMPILE_KERNELS"] = compile_kernels
        else:
            os.environ.pop("GENESIS_BENCH_COMPILE_KERNELS", None)

        if do_init:
            backend, resolved_backend = _resolve_backend(gs, backend_name)
            t0 = time.perf_counter()
            gs.init(backend=backend, logging_level="warning")
            result["thread_init_s"] = time.perf_counter() - t0
            result["thread_backend"] = resolved_backend

        result.update(_tiny_scene_round(gs))
        result["ok"] = True
    except Exception as exc:
        result["ok"] = False
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()


def _thread_reuse_probe_child(
    backend_name: str, compile_kernels: str
) -> dict[str, Any]:
    _configure_headless_env()
    import genesis as gs

    backend, resolved_backend = _resolve_backend(gs, backend_name)

    main_init_t0 = time.perf_counter()
    gs.init(backend=backend, logging_level="warning")
    main_init_s = time.perf_counter() - main_init_t0

    after_main_init: dict[str, Any] = {}
    t = threading.Thread(
        target=_thread_scene_worker,
        args=(after_main_init, backend_name, False, compile_kernels),
        name="genesis-scene-after-main-init",
    )
    t.start()
    t.join(timeout=180)
    if t.is_alive():
        raise RuntimeError("Thread reuse probe timed out after main-thread init")

    thread_init_first: dict[str, Any] = {}
    proc_result = _run_spawned_thread_init_probe(backend_name, compile_kernels)
    thread_init_first.update(proc_result)

    return {
        "resolved_backend": resolved_backend,
        "main_thread_init_s": main_init_s,
        "scene_in_worker_thread_after_main_init": after_main_init,
        "init_inside_worker_thread_fresh_process": thread_init_first,
    }


def _thread_init_probe_child(backend_name: str, compile_kernels: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    worker = threading.Thread(
        target=_thread_scene_worker,
        args=(result, backend_name, True, compile_kernels),
        name="genesis-thread-init-probe",
    )
    worker.start()
    worker.join(timeout=180)
    if worker.is_alive():
        return {
            "ok": False,
            "error": "thread_init_probe_timeout",
        }
    return result


def _run_spawned_thread_init_probe(
    backend_name: str, compile_kernels: str
) -> dict[str, Any]:
    return _run_child_subprocess(
        child_mode="thread-init",
        backend_name=backend_name,
        compile_kernels=compile_kernels,
    )


def _run_same_process_reuse(
    rounds: int, backend_name: str, compile_kernels: str
) -> dict[str, Any]:
    return _run_child_subprocess(
        child_mode="same-process-reuse",
        backend_name=backend_name,
        rounds=rounds,
        compile_kernels=compile_kernels,
    )


def _run_thread_reuse_probe(backend_name: str, compile_kernels: str) -> dict[str, Any]:
    return _run_child_subprocess(
        child_mode="thread-reuse",
        backend_name=backend_name,
        compile_kernels=compile_kernels,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=("auto", "cpu", "gpu"),
        default="auto",
        help="Genesis backend selection. 'auto' matches runtime logic.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="Number of repeated rounds for spawned and same-process benchmarks.",
    )
    parser.add_argument(
        "--child-mode",
        choices=("spawned", "thread-init", "same-process-reuse", "thread-reuse"),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--include-scene",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--compile-kernels",
        choices=("auto", "true", "false"),
        default="auto",
        help="Pass compile_kernels flag to scene.build when supported.",
    )
    args = parser.parse_args()

    if args.child_mode:
        if not args.output_json:
            raise SystemExit("--output-json is required in child mode")
        if args.child_mode == "spawned":
            payload = _child_measure(args.backend, args.include_scene)
        elif args.child_mode == "thread-init":
            payload = _thread_init_probe_child(args.backend, args.compile_kernels)
        elif args.child_mode == "same-process-reuse":
            payload = _same_process_reuse_child(args.rounds, args.backend)
        else:
            payload = _thread_reuse_probe_child(args.backend, args.compile_kernels)
        with open(args.output_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return

    report = {
        "backend_request": args.backend,
        "compile_kernels_request": args.compile_kernels,
        "env": {
            "GENESIS_FORCE_CPU": os.getenv("GENESIS_FORCE_CPU", ""),
            "PYGLET_HEADLESS": os.getenv("PYGLET_HEADLESS", ""),
            "PYOPENGL_PLATFORM": os.getenv("PYOPENGL_PLATFORM", ""),
        },
        "spawned_init_only": _run_spawned_rounds(
            rounds=args.rounds,
            backend_name=args.backend,
            include_scene=False,
            compile_kernels=args.compile_kernels,
        ),
        "spawned_init_plus_tiny_scene": _run_spawned_rounds(
            rounds=args.rounds,
            backend_name=args.backend,
            include_scene=True,
            compile_kernels=args.compile_kernels,
        ),
        "same_process_reuse": _run_same_process_reuse(
            rounds=args.rounds,
            backend_name=args.backend,
            compile_kernels=args.compile_kernels,
        ),
        "thread_reuse_probe": _run_thread_reuse_probe(
            args.backend, args.compile_kernels
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
