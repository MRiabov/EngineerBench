#!/usr/bin/env python3
"""
Benchmark /benchmark/validate and /benchmark/simulate cold-start timings with
GENESIS_COMPILE_KERNELS toggled on and off.

This script intentionally runs each sample in a fresh subprocess and can isolate
cache directories per run to keep measurements uncached/reproducible.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULT_PREFIX = "__EXPERIMENT_RESULT__="


@dataclass(frozen=True)
class Scenario:
    name: str
    script_content: str
    objectives: dict[str, Any]


SCENARIOS: dict[str, Scenario] = {
    "int101_like": Scenario(
        name="int101_like",
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
    "int133_like": Scenario(
        name="int133_like",
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


def _str_to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _write_session_files(session_root: Path, scenario: Scenario) -> None:
    (session_root / "script.py").write_text(
        scenario.script_content + "\n", encoding="utf-8"
    )
    (session_root / "objectives.yaml").write_text(
        yaml.safe_dump(scenario.objectives, sort_keys=False),
        encoding="utf-8",
    )


def _run_child_once(
    *,
    mode: str,
    session_root: Path,
    smoke_test_mode: bool,
    compile_kernels: bool,
) -> dict[str, Any]:
    from shared.simulation.schemas import SimulatorBackendType
    from worker_heavy.utils.validation import simulate_subprocess, validate_subprocess

    os.environ["GENESIS_COMPILE_KERNELS"] = "1" if compile_kernels else "0"

    start = time.perf_counter()
    try:
        if mode == "validate":
            success, message = validate_subprocess(
                script_path=session_root / "script.py",
                session_root=session_root,
                script_content=None,
                output_dir=session_root,
                smoke_test_mode=smoke_test_mode,
                session_id=f"exp-{uuid.uuid4().hex[:10]}",
                particle_budget=None,
            )
            elapsed = time.perf_counter() - start
            return {
                "mode": mode,
                "success": bool(success),
                "message": message,
                "elapsed_sec": elapsed,
            }

        result = simulate_subprocess(
            script_path=session_root / "script.py",
            session_root=session_root,
            script_content=None,
            output_dir=session_root,
            smoke_test_mode=smoke_test_mode,
            backend=SimulatorBackendType.GENESIS,
            session_id=f"exp-{uuid.uuid4().hex[:10]}",
            particle_budget=None,
        )
        elapsed = time.perf_counter() - start
        return {
            "mode": mode,
            "success": bool(result.success),
            "message": result.summary,
            "failure_reason": result.failure.reason.value if result.failure else None,
            "elapsed_sec": elapsed,
        }
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return {
            "mode": mode,
            "success": False,
            "elapsed_sec": elapsed,
            "runtime_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _run_child_command(args: argparse.Namespace) -> int:
    if not args.session_root:
        raise ValueError("--session-root is required in child mode")

    payload = _run_child_once(
        mode=args.mode,
        session_root=Path(args.session_root),
        smoke_test_mode=args.smoke_test_mode,
        compile_kernels=args.compile_kernels,
    )
    print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)
    return 0


def _extract_result_payload(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX) :])
    raise RuntimeError("Child process did not emit result payload")


def _run_parent(args: argparse.Namespace) -> int:
    if args.mode == "both":
        modes = ["validate", "simulate"]
    else:
        modes = [args.mode]

    selected_scenarios = (
        list(SCENARIOS.values())
        if args.scenario == "all"
        else [SCENARIOS[args.scenario]]
    )

    rows: list[dict[str, Any]] = []
    script_path = Path(__file__).resolve()

    for scenario in selected_scenarios:
        for compile_kernels in (False, True):
            for mode in modes:
                for rep in range(1, args.repetitions + 1):
                    with tempfile.TemporaryDirectory(
                        prefix=f"{scenario.name}-{mode}-"
                    ) as tmp:
                        session_root = Path(tmp) / "session"
                        session_root.mkdir(parents=True, exist_ok=True)
                        _write_session_files(session_root, scenario)

                        env = os.environ.copy()
                        env["PYGLET_HEADLESS"] = "1"
                        env.setdefault("PYOPENGL_PLATFORM", "egl")
                        if args.force_cpu:
                            env["GENESIS_FORCE_CPU"] = "1"
                        existing_pythonpath = env.get("PYTHONPATH", "").strip()
                        if existing_pythonpath:
                            env["PYTHONPATH"] = f"{REPO_ROOT}:{existing_pythonpath}"
                        else:
                            env["PYTHONPATH"] = str(REPO_ROOT)
                        if args.isolate_cache:
                            cache_home = Path(tmp) / "home"
                            xdg_cache = cache_home / ".cache"
                            xdg_cache.mkdir(parents=True, exist_ok=True)
                            env["HOME"] = str(cache_home)
                            env["XDG_CACHE_HOME"] = str(xdg_cache)
                            env["TAICHI_CACHE_DIR"] = str(xdg_cache / "taichi")
                            env["TI_CACHE_HOME"] = str(xdg_cache / "taichi")

                        cmd = [
                            sys.executable,
                            str(script_path),
                            "--child",
                            "--mode",
                            mode,
                            "--session-root",
                            str(session_root),
                            "--smoke-test-mode",
                            str(args.smoke_test_mode).lower(),
                            "--compile-kernels",
                            str(compile_kernels).lower(),
                        ]

                        start = time.perf_counter()
                        try:
                            proc = subprocess.run(
                                cmd,
                                cwd=str(REPO_ROOT),
                                env=env,
                                capture_output=True,
                                text=True,
                                timeout=args.timeout_sec,
                            )
                        except subprocess.TimeoutExpired as exc:
                            wall_elapsed = time.perf_counter() - start
                            rows.append(
                                {
                                    "scenario": scenario.name,
                                    "mode": mode,
                                    "compile_kernels": compile_kernels,
                                    "repetition": rep,
                                    "ok": False,
                                    "timed_out": True,
                                    "elapsed_sec": wall_elapsed,
                                    "error": (
                                        f"Child run timed out after {args.timeout_sec}s. "
                                        f"stdout_tail={(exc.stdout or '')[-800:]!r} "
                                        f"stderr_tail={(exc.stderr or '')[-800:]!r}"
                                    ),
                                }
                            )
                            continue
                        wall_elapsed = time.perf_counter() - start

                        if proc.returncode != 0:
                            stderr_tail = proc.stderr.strip()[-1000:]
                            stdout_tail = proc.stdout.strip()[-1000:]
                            rows.append(
                                {
                                    "scenario": scenario.name,
                                    "mode": mode,
                                    "compile_kernels": compile_kernels,
                                    "repetition": rep,
                                    "ok": False,
                                    "elapsed_sec": wall_elapsed,
                                    "error": (
                                        f"child_returncode={proc.returncode}; "
                                        f"stderr_tail={stderr_tail!r}; stdout_tail={stdout_tail!r}"
                                    ),
                                }
                            )
                            continue

                        child_payload = _extract_result_payload(proc.stdout)
                        rows.append(
                            {
                                "scenario": scenario.name,
                                "mode": mode,
                                "compile_kernels": compile_kernels,
                                "repetition": rep,
                                "ok": True,
                                "elapsed_sec": float(child_payload["elapsed_sec"]),
                                "parent_wall_sec": wall_elapsed,
                                "success": child_payload.get("success"),
                                "message": child_payload.get("message"),
                                "failure_reason": child_payload.get("failure_reason"),
                                "runtime_error": child_payload.get("runtime_error"),
                            }
                        )

    successful_rows = [r for r in rows if r.get("ok")]
    groups: dict[tuple[str, str, bool], list[float]] = {}
    for row in successful_rows:
        key = (row["scenario"], row["mode"], row["compile_kernels"])
        groups.setdefault(key, []).append(row["elapsed_sec"])

    summary: list[dict[str, Any]] = []
    for key, values in sorted(groups.items()):
        scenario, mode, compile_kernels = key
        summary.append(
            {
                "scenario": scenario,
                "mode": mode,
                "compile_kernels": compile_kernels,
                "runs": len(values),
                "mean_sec": statistics.mean(values),
                "median_sec": statistics.median(values),
                "min_sec": min(values),
                "max_sec": max(values),
                "stdev_sec": statistics.stdev(values) if len(values) > 1 else 0.0,
            }
        )

    for item in summary:
        print(
            f"[summary] scenario={item['scenario']} mode={item['mode']} "
            f"compile_kernels={item['compile_kernels']} runs={item['runs']} "
            f"mean={item['mean_sec']:.3f}s median={item['median_sec']:.3f}s "
            f"min={item['min_sec']:.3f}s max={item['max_sec']:.3f}s"
        )
    failed_rows = [r for r in rows if not r.get("ok")]
    timed_out_rows = [r for r in failed_rows if r.get("timed_out")]
    if failed_rows:
        print(
            f"[summary] failures={len(failed_rows)} timed_out={len(timed_out_rows)} "
            f"successful={len(successful_rows)} total={len(rows)}"
        )

    output = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "repo_root": str(REPO_ROOT),
        "args": vars(args),
        "summary": summary,
        "rows": rows,
    }

    output_path = (
        Path(args.output_json).resolve()
        if args.output_json
        else (
            Path(__file__).resolve().parent
            / f"results-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"[result] wrote {output_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure cold-start /validate and /simulate timings with "
            "GENESIS_COMPILE_KERNELS toggled."
        )
    )
    parser.add_argument(
        "--mode",
        choices=["validate", "simulate", "both"],
        default="both",
        help="Which heavy path to benchmark.",
    )
    parser.add_argument(
        "--scenario",
        choices=["all", *sorted(SCENARIOS.keys())],
        default="all",
        help="Scenario fixture to use.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Repetitions per (scenario, mode, compile_kernels) tuple.",
    )
    parser.add_argument(
        "--smoke-test-mode",
        type=_str_to_bool,
        default=False,
        help="Use heavy simulate smoke mode (true/false).",
    )
    parser.add_argument(
        "--isolate-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Isolate HOME/XDG cache per run for cold-start measurements.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional output path for raw result JSON.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=180,
        help="Timeout per child run.",
    )
    parser.add_argument(
        "--force-cpu",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Set GENESIS_FORCE_CPU=1 in each run (recommended on CPU-only machines).",
    )

    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--session-root", default="", help=argparse.SUPPRESS)
    parser.add_argument(
        "--compile-kernels", type=_str_to_bool, default=False, help=argparse.SUPPRESS
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.child:
        return _run_child_command(args)
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
