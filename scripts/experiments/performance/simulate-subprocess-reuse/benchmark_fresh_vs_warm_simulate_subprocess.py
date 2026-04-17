#!/usr/bin/env python3
"""Benchmark fresh-child versus warm-child simulate_subprocess execution."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULT_PREFIX = "__EXPERIMENT_RESULT__="
_SPAWN_CONTEXT = multiprocessing.get_context("spawn")


@dataclass(frozen=True)
class Scenario:
    name: str
    script_content: str
    objectives: dict[str, Any]


SCENARIOS: dict[str, Scenario] = {
    "bundle_a_int101_like": Scenario(
        name="bundle_a_int101_like",
        script_content="""
from build123d import *
from shared.models.schemas import PartMetadata


def build():
    p = Box(1, 1, 1)
    p.label = "test_part"
    p.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return p
""".strip(),
        objectives={
            "physics": {
                "backend": "GENESIS",
                "fem_enabled": False,
                "compute_target": "cpu",
            },
            "objectives": {
                "goal_zone": {"min": [5, 5, 5], "max": [7, 7, 7]},
                "build_zone": {"min": [-10, -10, -10], "max": [10, 10, 10]},
            },
            "simulation_bounds": {"min": [-10, -10, -10], "max": [10, 10, 10]},
            "payload": {
                "label": "test_obj",
                "shape": "sphere",
                "start_position": [0, 0, 5],
                "runtime_jitter": [0, 0, 0],
            },
            "constraints": {"max_unit_cost": 100.0, "max_weight_g": 10.0},
        },
    ),
    "bundle_b_int133_like": Scenario(
        name="bundle_b_int133_like",
        script_content="""
from build123d import *
from shared.models.schemas import PartMetadata


def build():
    obstacle = Box(30, 30, 30).move(Pos(0, 0, 15))
    obstacle.label = "obstacle"
    obstacle.metadata = PartMetadata(material_id="aluminum_6061")
    return obstacle
""".strip(),
        objectives={
            "physics": {
                "backend": "GENESIS",
                "fem_enabled": False,
                "compute_target": "cpu",
            },
            "objectives": {
                "goal_zone": {"min": [5, 5, 5], "max": [7, 7, 7]},
                "build_zone": {"min": [-100, -100, -10], "max": [100, 100, 100]},
            },
            "simulation_bounds": {"min": [-120, -120, -20], "max": [120, 120, 120]},
            "payload": {
                "label": "obj",
                "shape": "sphere",
                "start_position": [0, 0, 0],
                "runtime_jitter": [0, 0, 0],
            },
            "constraints": {"max_unit_cost": 1000.0, "max_weight_g": 5000.0},
        },
    ),
}

ORDER_MAP: dict[str, tuple[str, str]] = {
    "A_then_B": ("bundle_a_int101_like", "bundle_b_int133_like"),
    "B_then_A": ("bundle_b_int133_like", "bundle_a_int101_like"),
}


def _write_session_files(session_root: Path, scenario: Scenario) -> None:
    session_root.mkdir(parents=True, exist_ok=True)
    (session_root / "script.py").write_text(
        scenario.script_content + "\n",
        encoding="utf-8",
    )
    (session_root / "objectives.yaml").write_text(
        yaml.safe_dump(scenario.objectives, sort_keys=False),
        encoding="utf-8",
    )


def _configure_env(cache_root: Path, force_cpu: bool) -> None:
    home_root = cache_root / "home"
    xdg_cache_root = cache_root / "xdg-cache"
    taichi_root = xdg_cache_root / "taichi"
    home_root.mkdir(parents=True, exist_ok=True)
    xdg_cache_root.mkdir(parents=True, exist_ok=True)
    taichi_root.mkdir(parents=True, exist_ok=True)

    os.environ["PYGLET_HEADLESS"] = "1"
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ["HOME"] = str(home_root)
    os.environ["XDG_CACHE_HOME"] = str(xdg_cache_root)
    os.environ["TAICHI_CACHE_DIR"] = str(taichi_root)
    os.environ["TI_CACHE_HOME"] = str(taichi_root)
    if force_cpu:
        os.environ["GENESIS_FORCE_CPU"] = "1"


def _run_simulation_task(
    *,
    session_root: Path,
    session_id: str,
) -> dict[str, Any]:
    from shared.simulation.schemas import SimulatorBackendType
    from worker_heavy.utils.validation import simulate_subprocess

    start = time.perf_counter()
    result = simulate_subprocess(
        script_path=session_root / "script.py",
        session_root=session_root,
        script_content=None,
        output_dir=session_root,
        smoke_test_mode=True,
        backend=SimulatorBackendType.GENESIS,
        session_id=session_id,
        particle_budget=None,
    )
    elapsed = time.perf_counter() - start
    return {
        "success": bool(result.success),
        "summary": result.summary,
        "failure_reason": result.failure.reason.value if result.failure else None,
        "elapsed_sec": elapsed,
    }


def _run_order_with_fresh_child(
    scenario_order: tuple[str, str],
    session_roots: dict[str, Path],
) -> list[dict[str, Any]]:
    from worker_heavy.runtime.simulation_runner import init_genesis_worker

    rows: list[dict[str, Any]] = []
    for position, scenario_name in enumerate(scenario_order, start=1):
        session_id = f"fresh-{scenario_name}-{uuid.uuid4().hex[:8]}"
        start = time.perf_counter()
        with ProcessPoolExecutor(
            max_workers=1,
            max_tasks_per_child=1,
            mp_context=_SPAWN_CONTEXT,
            initializer=init_genesis_worker,
        ) as executor:
            payload = executor.submit(
                _run_simulation_task,
                session_root=session_roots[scenario_name],
                session_id=session_id,
            ).result()
        wall_clock_elapsed = time.perf_counter() - start
        rows.append(
            {
                "position": position,
                "scenario": scenario_name,
                "session_id": session_id,
                "wall_clock_elapsed_sec": wall_clock_elapsed,
                **payload,
            }
        )
    return rows


def _run_order_with_reused_child(
    scenario_order: tuple[str, str],
    session_roots: dict[str, Path],
) -> list[dict[str, Any]]:
    from worker_heavy.runtime.simulation_runner import init_genesis_worker

    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=1,
        mp_context=_SPAWN_CONTEXT,
        initializer=init_genesis_worker,
    ) as executor:
        for position, scenario_name in enumerate(scenario_order, start=1):
            session_id = f"warm-{scenario_name}-{uuid.uuid4().hex[:8]}"
            start = time.perf_counter()
            payload = executor.submit(
                _run_simulation_task,
                session_root=session_roots[scenario_name],
                session_id=session_id,
            ).result()
            wall_clock_elapsed = time.perf_counter() - start
            rows.append(
                {
                    "position": position,
                    "scenario": scenario_name,
                    "session_id": session_id,
                    "wall_clock_elapsed_sec": wall_clock_elapsed,
                    **payload,
                }
            )
    return rows


def _run_child_command(args: argparse.Namespace) -> int:
    order = ORDER_MAP[args.order]
    mode = args.mode

    with tempfile.TemporaryDirectory(
        prefix=f"simulate-subprocess-{mode}-{args.order}-"
    ) as tmp:
        temp_root = Path(tmp)
        _configure_env(temp_root / "cache-root", force_cpu=args.force_cpu)

        session_roots: dict[str, Path] = {}
        for scenario_name in order:
            session_root = temp_root / scenario_name
            _write_session_files(session_root, SCENARIOS[scenario_name])
            session_roots[scenario_name] = session_root

        start = time.perf_counter()
        try:
            if mode == "fresh_child_per_task":
                rows = _run_order_with_fresh_child(order, session_roots)
            elif mode == "reused_child":
                rows = _run_order_with_reused_child(order, session_roots)
            else:
                raise ValueError(f"Unsupported mode: {mode}")
        except Exception as exc:
            payload = {
                "mode": mode,
                "order": args.order,
                "success": False,
                "runtime_error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)
            return 0

        total_elapsed = time.perf_counter() - start
        payload = {
            "mode": mode,
            "order": args.order,
            "success": all(row["success"] for row in rows),
            "total_wall_clock_elapsed_sec": total_elapsed,
            "rows": rows,
            "env": {
                "GENESIS_FORCE_CPU": os.getenv("GENESIS_FORCE_CPU", ""),
                "PYGLET_HEADLESS": os.getenv("PYGLET_HEADLESS", ""),
                "PYOPENGL_PLATFORM": os.getenv("PYOPENGL_PLATFORM", ""),
                "HOME": os.getenv("HOME", ""),
                "XDG_CACHE_HOME": os.getenv("XDG_CACHE_HOME", ""),
            },
        }
        print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)
    return 0


def _extract_result_payload(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX) :])
    raise RuntimeError("Child process did not emit result payload")


def _run_parent(args: argparse.Namespace) -> int:
    rows: list[dict[str, Any]] = []
    script_path = Path(__file__).resolve()

    for repetition in range(1, args.repetitions + 1):
        for order in ORDER_MAP:
            for mode in ("fresh_child_per_task", "reused_child"):
                env = os.environ.copy()
                env["PYTHONPATH"] = (
                    f"{REPO_ROOT}:{env['PYTHONPATH']}"
                    if env.get("PYTHONPATH")
                    else str(REPO_ROOT)
                )
                cmd = [
                    sys.executable,
                    str(script_path),
                    "--child",
                    "--mode",
                    mode,
                    "--order",
                    order,
                ]
                if args.force_cpu:
                    cmd.append("--force-cpu")

                started_at = time.perf_counter()
                proc = subprocess.run(
                    cmd,
                    cwd=str(REPO_ROOT),
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=args.timeout_sec,
                )
                launcher_elapsed = time.perf_counter() - started_at

                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
                payload = _extract_result_payload(stdout)
                payload.update(
                    {
                        "repetition": repetition,
                        "parent_return_code": proc.returncode,
                        "parent_wall_clock_elapsed_sec": launcher_elapsed,
                    }
                )
                if proc.returncode != 0:
                    payload["success"] = False
                    payload["runtime_error"] = (
                        payload.get("runtime_error")
                        or f"Child process exited with code {proc.returncode}"
                    )
                if stderr.strip():
                    payload["captured_stderr_tail"] = stderr.strip().splitlines()[-20:]
                rows.append(payload)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['mode']}::{row['order']}"
        grouped.setdefault(key, []).append(row)

    summary: dict[str, dict[str, Any]] = {}
    for key, group_rows in grouped.items():
        first_task_avg = sum(
            r["rows"][0]["wall_clock_elapsed_sec"] for r in group_rows
        ) / len(group_rows)
        second_task_avg = sum(
            r["rows"][1]["wall_clock_elapsed_sec"] for r in group_rows
        ) / len(group_rows)
        total_avg = sum(r["total_wall_clock_elapsed_sec"] for r in group_rows) / len(
            group_rows
        )
        summary[key] = {
            "runs": len(group_rows),
            "all_success": all(bool(r.get("success")) for r in group_rows),
            "avg_total_wall_clock_elapsed_sec": total_avg,
            "avg_first_task_wall_clock_elapsed_sec": first_task_avg,
            "avg_second_task_wall_clock_elapsed_sec": second_task_avg,
        }

    comparisons: dict[str, Any] = {}
    for order in ORDER_MAP:
        fresh_key = f"fresh_child_per_task::{order}"
        warm_key = f"reused_child::{order}"
        if fresh_key in summary and warm_key in summary:
            fresh = summary[fresh_key]
            warm = summary[warm_key]
            comparisons[order] = {
                "fresh_avg_total_sec": fresh["avg_total_wall_clock_elapsed_sec"],
                "warm_avg_total_sec": warm["avg_total_wall_clock_elapsed_sec"],
                "total_speedup_ratio": (
                    fresh["avg_total_wall_clock_elapsed_sec"]
                    / warm["avg_total_wall_clock_elapsed_sec"]
                    if warm["avg_total_wall_clock_elapsed_sec"] > 0
                    else None
                ),
                "second_task_speedup_ratio": (
                    fresh["avg_second_task_wall_clock_elapsed_sec"]
                    / warm["avg_second_task_wall_clock_elapsed_sec"]
                    if warm["avg_second_task_wall_clock_elapsed_sec"] > 0
                    else None
                ),
                "fresh_second_task_sec": fresh[
                    "avg_second_task_wall_clock_elapsed_sec"
                ],
                "warm_second_task_sec": warm["avg_second_task_wall_clock_elapsed_sec"],
            }

    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "repetitions": args.repetitions,
        "force_cpu": args.force_cpu,
        "orders": list(ORDER_MAP.keys()),
        "scenarios": {
            name: {"name": scenario.name} for name, scenario in SCENARIOS.items()
        },
        "summary": summary,
        "comparisons": comparisons,
        "runs": rows,
    }

    output_path = args.output_json.strip()
    if not output_path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = (
            Path(__file__).resolve().parent
            / f"results-fresh-vs-warm-simulate-subprocess-{timestamp}.json"
        ).as_posix()

    Path(output_path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output_path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("fresh_child_per_task", "reused_child"),
        default="fresh_child_per_task",
    )
    parser.add_argument("--order", choices=tuple(ORDER_MAP.keys()), default="A_then_B")
    parser.add_argument("--force-cpu", action="store_true")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--timeout-sec", type=int, default=900)
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    if args.child:
        return _run_child_command(args)
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
