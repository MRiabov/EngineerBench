#!/usr/bin/env python3
"""
Benchmark validate/prerender latency for MUJOCO vs GENESIS using the same
24-view static rendering path used by heavy-worker validation.

Design goals:
- Run each sample in a fresh subprocess (cold process behavior).
- Optionally isolate cache dirs per run to reduce cache pollution.
- Compare endpoint-equivalent `validate_subprocess` and direct prerender path.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
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
from build123d import Box
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
from build123d import Box, Pos
from shared.models.schemas import PartMetadata

def build():
    obstacle = Box(30, 30, 30).move(Pos(0, 0, 15))
    obstacle.label = "obstacle"
    obstacle.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
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
    "multi_part_like": Scenario(
        name="multi_part_like",
        script_content="""
from build123d import Box, Pos
from shared.models.schemas import PartMetadata

def build():
    p = Box(120, 80, 40).move(Pos(0, 0, 20))
    p.label = "large_obstacle"
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
                "goal_zone": {"min": [25, 8, 1], "max": [35, 18, 8]},
                "build_zone": {"min": [-120, -120, -20], "max": [120, 120, 120]},
            },
            "simulation_bounds": {"min": [-150, -150, -30], "max": [150, 150, 150]},
            "payload": {
                "label": "ball",
                "shape": "sphere",
                "start_position": [0, 0, 60],
                "runtime_jitter": [1, 1, 1],
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


def _count_render_files(session_root: Path) -> int:
    renders_dir = session_root / "renders"
    if not renders_dir.exists():
        return 0
    return len(list(renders_dir.glob("render_e*_a*.png")))


def _write_session_files(session_root: Path, scenario: Scenario, backend: str) -> None:
    objectives = copy.deepcopy(scenario.objectives)
    physics = objectives.setdefault("physics", {})
    physics["backend"] = backend
    physics.setdefault("fem_enabled", False)
    physics.setdefault("compute_target", "cpu")

    (session_root / "script.py").write_text(
        scenario.script_content + "\n", encoding="utf-8"
    )
    (session_root / "objectives.yaml").write_text(
        yaml.safe_dump(objectives, sort_keys=False),
        encoding="utf-8",
    )


def _run_child_once(
    *,
    mode: str,
    backend: str,
    session_root: Path,
    smoke_test_mode: bool,
) -> dict[str, Any]:
    from shared.simulation.schemas import SimulatorBackendType
    from shared.workers.loader import load_component_from_script
    from worker_heavy.utils.rendering import prerender_24_views
    from worker_heavy.utils.validation import validate_subprocess

    backend_type = SimulatorBackendType(backend)
    start = time.perf_counter()
    try:
        if mode == "validate":
            success, message = validate_subprocess(
                script_path=session_root / "script.py",
                session_root=session_root,
                script_content=None,
                output_dir=session_root,
                smoke_test_mode=smoke_test_mode,
                session_id=None,
                particle_budget=None,
            )
            elapsed = time.perf_counter() - start
            return {
                "mode": mode,
                "backend": backend,
                "success": bool(success),
                "message": message,
                "elapsed_sec": elapsed,
                "render_count": _count_render_files(session_root),
            }

        component = load_component_from_script(
            script_path=session_root / "script.py",
            session_root=session_root,
            script_content=None,
        )
        render_paths = prerender_24_views(
            component,
            output_dir=str(session_root / "renders"),
            backend_type=backend_type,
            session_id=None,
            smoke_test_mode=smoke_test_mode,
            particle_budget=None,
        )
        elapsed = time.perf_counter() - start
        return {
            "mode": mode,
            "backend": backend,
            "success": True,
            "message": "prerender_complete",
            "elapsed_sec": elapsed,
            "render_count": len(render_paths),
        }
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return {
            "mode": mode,
            "backend": backend,
            "success": False,
            "elapsed_sec": elapsed,
            "render_count": _count_render_files(session_root),
            "runtime_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _run_child_command(args: argparse.Namespace) -> int:
    payload = _run_child_once(
        mode=args.mode,
        backend=args.backend,
        session_root=Path(args.session_root),
        smoke_test_mode=args.smoke_test_mode,
    )
    print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)
    return 0


def _extract_result_payload(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX) :])
    raise RuntimeError("Child process did not emit result payload")


def _run_parent(args: argparse.Namespace) -> int:
    modes = ["validate", "prerender"] if args.mode == "both" else [args.mode]
    backends = ["MUJOCO", "GENESIS"] if args.backend == "all" else [args.backend]
    selected_scenarios = (
        list(SCENARIOS.values())
        if args.scenario == "all"
        else [SCENARIOS[args.scenario]]
    )

    rows: list[dict[str, Any]] = []
    script_path = Path(__file__).resolve()

    for scenario in selected_scenarios:
        for backend in backends:
            for mode in modes:
                for rep in range(1, args.repetitions + 1):
                    with tempfile.TemporaryDirectory(
                        prefix=f"{scenario.name}-{backend.lower()}-{mode}-"
                    ) as tmp:
                        session_root = Path(tmp) / "session"
                        session_root.mkdir(parents=True, exist_ok=True)
                        _write_session_files(session_root, scenario, backend)

                        env = os.environ.copy()
                        env["PYGLET_HEADLESS"] = "1"
                        env["PYOPENGL_PLATFORM"] = "egl"
                        if backend == "MUJOCO" and args.mujoco_gl:
                            env["MUJOCO_GL"] = args.mujoco_gl
                            if args.mujoco_gl.lower() == "osmesa":
                                env["PYOPENGL_PLATFORM"] = "osmesa"
                        else:
                            env.pop("MUJOCO_GL", None)
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
                            "--backend",
                            backend,
                            "--session-root",
                            str(session_root),
                            "--smoke-test-mode",
                            str(args.smoke_test_mode).lower(),
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
                            rows.append(
                                {
                                    "scenario": scenario.name,
                                    "backend": backend,
                                    "mode": mode,
                                    "repetition": rep,
                                    "ok": False,
                                    "timed_out": True,
                                    "elapsed_sec": time.perf_counter() - start,
                                    "error": (
                                        f"child_timeout_{args.timeout_sec}s "
                                        f"stdout_tail={(exc.stdout or '')[-1000:]!r} "
                                        f"stderr_tail={(exc.stderr or '')[-1000:]!r}"
                                    ),
                                }
                            )
                            continue

                        if proc.returncode != 0:
                            rows.append(
                                {
                                    "scenario": scenario.name,
                                    "backend": backend,
                                    "mode": mode,
                                    "repetition": rep,
                                    "ok": False,
                                    "elapsed_sec": time.perf_counter() - start,
                                    "error": (
                                        f"child_returncode={proc.returncode} "
                                        f"stdout_tail={proc.stdout[-1000:]!r} "
                                        f"stderr_tail={proc.stderr[-1000:]!r}"
                                    ),
                                }
                            )
                            continue

                        child_payload = _extract_result_payload(proc.stdout)
                        rows.append(
                            {
                                "scenario": scenario.name,
                                "backend": backend,
                                "mode": mode,
                                "repetition": rep,
                                "ok": True,
                                "elapsed_sec": float(child_payload["elapsed_sec"]),
                                "parent_wall_sec": time.perf_counter() - start,
                                "success": bool(child_payload.get("success")),
                                "render_count": int(
                                    child_payload.get("render_count", 0)
                                ),
                                "message": child_payload.get("message"),
                                "runtime_error": child_payload.get("runtime_error"),
                            }
                        )

    summary: list[dict[str, Any]] = []
    grouped_keys = sorted({(r["scenario"], r["mode"], r["backend"]) for r in rows})
    for scenario, mode, backend in grouped_keys:
        group_rows = [
            r
            for r in rows
            if r["scenario"] == scenario
            and r["mode"] == mode
            and r["backend"] == backend
        ]
        ok_rows = [r for r in group_rows if r.get("ok")]
        success_rows = [r for r in ok_rows if r.get("success")]
        usable_rows = [r for r in success_rows if r.get("render_count", 0) > 0]

        success_values = [r["elapsed_sec"] for r in success_rows]
        usable_values = [r["elapsed_sec"] for r in usable_rows]

        summary.append(
            {
                "scenario": scenario,
                "mode": mode,
                "backend": backend,
                "runs_total": len(group_rows),
                "runs_ok": len(ok_rows),
                "runs_success": len(success_rows),
                "runs_usable": len(usable_rows),
                "mean_sec_success": (
                    statistics.mean(success_values) if success_values else None
                ),
                "mean_sec_usable": (
                    statistics.mean(usable_values) if usable_values else None
                ),
                "median_sec_usable": (
                    statistics.median(usable_values) if usable_values else None
                ),
                "min_sec_usable": (min(usable_values) if usable_values else None),
                "max_sec_usable": (max(usable_values) if usable_values else None),
            }
        )

    summary_by_key = {(s["scenario"], s["mode"], s["backend"]): s for s in summary}
    speedups: list[dict[str, Any]] = []
    scenario_mode_pairs = sorted({(s["scenario"], s["mode"]) for s in summary})
    for scenario, mode in scenario_mode_pairs:
        mj = summary_by_key.get((scenario, mode, "MUJOCO"))
        gs = summary_by_key.get((scenario, mode, "GENESIS"))
        if not mj or not gs:
            continue
        mj_mean = mj["mean_sec_usable"] or mj["mean_sec_success"]
        gs_mean = gs["mean_sec_usable"] or gs["mean_sec_success"]
        if not mj_mean or not gs_mean:
            continue
        speedups.append(
            {
                "scenario": scenario,
                "mode": mode,
                "mujoco_mean_sec": mj_mean,
                "genesis_mean_sec": gs_mean,
                "mujoco_speedup_over_genesis": (
                    gs_mean / mj_mean if mj_mean > 0 else None
                ),
            }
        )

    for item in summary:
        print(
            f"[summary] scenario={item['scenario']} mode={item['mode']} backend={item['backend']} "
            f"ok={item['runs_ok']}/{item['runs_total']} success={item['runs_success']} usable={item['runs_usable']} "
            f"mean_usable={item['mean_sec_usable']}"
        )
    for item in speedups:
        print(
            f"[speedup] scenario={item['scenario']} mode={item['mode']} "
            f"genesis_mean={item['genesis_mean_sec']:.3f}s mujoco_mean={item['mujoco_mean_sec']:.3f}s "
            f"mujoco_x_faster={item['mujoco_speedup_over_genesis']:.2f}"
        )

    output = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "repo_root": str(REPO_ROOT),
        "args": vars(args),
        "summary": summary,
        "speedups": speedups,
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
            "Benchmark MUJOCO vs GENESIS 24-view static prerender and validate path."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("validate", "prerender", "both"),
        default="both",
        help="Benchmark endpoint-equivalent validate path, prerender-only path, or both.",
    )
    parser.add_argument(
        "--scenario",
        choices=("all", *sorted(SCENARIOS.keys())),
        default="all",
        help="Which fixture scenario to benchmark.",
    )
    parser.add_argument(
        "--backend",
        choices=("all", "MUJOCO", "GENESIS"),
        default="all",
        help="Which backend(s) to benchmark.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Repetitions per (scenario, backend, mode) tuple.",
    )
    parser.add_argument(
        "--smoke-test-mode",
        type=_str_to_bool,
        default=False,
        help="Enable smoke mode (reduces render views to 1).",
    )
    parser.add_argument(
        "--isolate-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Isolate HOME/XDG cache per run for colder measurements.",
    )
    parser.add_argument(
        "--force-cpu",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Set GENESIS_FORCE_CPU=1 in each run.",
    )
    parser.add_argument(
        "--mujoco-gl",
        default="egl",
        help="MUJOCO_GL value to export for child runs (default: egl).",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=300,
        help="Timeout per child run.",
    )
    parser.add_argument(
        "--output-json",
        default="",
        help="Optional output path for result JSON.",
    )

    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--session-root", default="", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.child:
        return _run_child_command(args)
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
