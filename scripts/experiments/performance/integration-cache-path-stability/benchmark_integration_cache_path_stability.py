#!/usr/bin/env python3
"""Benchmark cache reuse sensitivity to integration session/workspace stability."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
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

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULT_PREFIX = "__EXPERIMENT_RESULT__="


@dataclass(frozen=True)
class Scenario:
    name: str
    int_prefix: str
    script_content: str
    objectives: dict[str, Any]


SCENARIOS: dict[str, Scenario] = {
    "int101_like": Scenario(
        name="int101_like",
        int_prefix="INT-101",
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
        int_prefix="INT-133",
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
}

MODES = (
    "random_workspace_random_session",
    "stable_workspace_random_session",
    "random_workspace_stable_session",
    "stable_workspace_stable_session",
)


def _str_to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _configure_env(cache_root: Path, force_cpu: bool) -> None:
    home_root = cache_root / "home"
    xdg_cache_root = cache_root / "xdg-cache"
    taichi_root = xdg_cache_root / "taichi"
    temp_root = cache_root / "tmp"

    home_root.mkdir(parents=True, exist_ok=True)
    xdg_cache_root.mkdir(parents=True, exist_ok=True)
    taichi_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    os.environ["PYGLET_HEADLESS"] = "1"
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ["HOME"] = str(home_root)
    os.environ["XDG_CACHE_HOME"] = str(xdg_cache_root)
    os.environ["TAICHI_CACHE_DIR"] = str(taichi_root)
    os.environ["TI_CACHE_HOME"] = str(taichi_root)
    os.environ["TMPDIR"] = str(temp_root)
    os.environ["TEMP"] = str(temp_root)
    os.environ["TMP"] = str(temp_root)
    if force_cpu:
        os.environ["GENESIS_FORCE_CPU"] = "1"
    os.environ["IS_INTEGRATION_TEST"] = "true"


def _session_id_for_mode(scenario: Scenario, mode: str, repetition: int) -> str:
    if "stable_session" in mode:
        return scenario.int_prefix
    return f"{scenario.int_prefix}-{uuid.uuid4().hex[:8]}"


def _workspace_root_for_mode(
    *,
    scenario: Scenario,
    mode: str,
    repetition: int,
    root_base: Path,
) -> Path:
    if "stable_workspace" in mode:
        return root_base / "stable-workspaces" / scenario.int_prefix.lower()
    unique = f"{scenario.int_prefix.lower()}-rep{repetition}-{uuid.uuid4().hex[:8]}"
    return root_base / "random-workspaces" / unique


def _reset_workspace(session_root: Path) -> None:
    if session_root.exists():
        shutil.rmtree(session_root)
    session_root.mkdir(parents=True, exist_ok=True)


def _write_session_files(
    session_root: Path,
    scenario: Scenario,
    backend: str,
) -> None:
    objectives = copy.deepcopy(scenario.objectives)
    physics = objectives.setdefault("physics", {})
    physics["backend"] = backend
    physics.setdefault("fem_enabled", False)
    physics.setdefault("compute_target", "cpu")

    (session_root / "script.py").write_text(
        scenario.script_content + "\n",
        encoding="utf-8",
    )
    (session_root / "objectives.yaml").write_text(
        yaml.safe_dump(objectives, sort_keys=False),
        encoding="utf-8",
    )


def _run_child_once(
    *,
    session_root: Path,
    session_id: str,
    backend: str,
    smoke_test_mode: bool,
    particle_budget: int | None,
) -> dict[str, Any]:
    from shared.simulation.schemas import SimulatorBackendType
    from worker_heavy.utils.validation import simulate_subprocess

    backend_type = SimulatorBackendType(backend)
    start = time.perf_counter()
    try:
        result = simulate_subprocess(
            script_path=session_root / "script.py",
            session_root=session_root,
            script_content=None,
            output_dir=session_root,
            smoke_test_mode=smoke_test_mode,
            backend=backend_type,
            session_id=session_id,
            particle_budget=particle_budget,
        )
        elapsed = time.perf_counter() - start
        return {
            "success": bool(result.success),
            "summary": result.summary,
            "failure_reason": result.failure.reason.value if result.failure else None,
            "elapsed_sec": elapsed,
            "session_root": str(session_root),
            "session_id": session_id,
        }
    except Exception as exc:
        elapsed = time.perf_counter() - start
        return {
            "success": False,
            "elapsed_sec": elapsed,
            "session_root": str(session_root),
            "session_id": session_id,
            "runtime_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _run_child_command(args: argparse.Namespace) -> int:
    payload = _run_child_once(
        session_root=Path(args.session_root),
        session_id=args.session_id,
        backend=args.backend,
        smoke_test_mode=args.smoke_test_mode,
        particle_budget=args.particle_budget,
    )
    print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}", flush=True)
    return 0


def _extract_result_payload(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX) :])
    raise RuntimeError("Child process did not emit result payload")


def _run_one_repetition(
    *,
    mode: str,
    scenario: Scenario,
    repetition: int,
    backend: str,
    smoke_test_mode: bool,
    particle_budget: int | None,
    workspace_root_base: Path,
    cache_root: Path,
    script_path: Path,
) -> dict[str, Any]:
    session_root = _workspace_root_for_mode(
        scenario=scenario,
        mode=mode,
        repetition=repetition,
        root_base=workspace_root_base,
    )
    session_id = _session_id_for_mode(scenario, mode, repetition)
    _reset_workspace(session_root)
    _write_session_files(session_root, scenario, backend)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}:{existing_pythonpath}" if existing_pythonpath else str(REPO_ROOT)
    )
    env["PYGLET_HEADLESS"] = "1"
    env.setdefault("PYOPENGL_PLATFORM", "egl")
    env["HOME"] = str(cache_root / "home")
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg-cache")
    env["TAICHI_CACHE_DIR"] = str(cache_root / "xdg-cache" / "taichi")
    env["TI_CACHE_HOME"] = str(cache_root / "xdg-cache" / "taichi")
    env["TMPDIR"] = str(cache_root / "tmp")
    env["TEMP"] = str(cache_root / "tmp")
    env["TMP"] = str(cache_root / "tmp")
    env["IS_INTEGRATION_TEST"] = "true"
    if os.environ.get("GENESIS_FORCE_CPU") == "1":
        env["GENESIS_FORCE_CPU"] = "1"

    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--child",
            "--session-root",
            str(session_root),
            "--session-id",
            session_id,
            "--backend",
            backend,
            "--smoke-test-mode",
            "true" if smoke_test_mode else "false",
            "--particle-budget",
            str(particle_budget) if particle_budget is not None else "none",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = {
        "mode": mode,
        "scenario": scenario.name,
        "int_prefix": scenario.int_prefix,
        "repetition": repetition,
        "workspace_strategy": (
            "stable_workspace" if "stable_workspace" in mode else "random_workspace"
        ),
        "session_strategy": (
            "stable_session" if "stable_session" in mode else "random_session"
        ),
        "child_returncode": proc.returncode,
    }
    if proc.returncode != 0:
        payload["success"] = False
        payload["runtime_error"] = "Child process exited non-zero"
        payload["stdout"] = proc.stdout
        payload["stderr"] = proc.stderr
        return payload

    child_payload = _extract_result_payload(proc.stdout)
    payload.update(child_payload)
    return payload


def _elapsed_values(rows: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for row in rows:
        elapsed = row.get("elapsed_sec")
        if isinstance(elapsed, (int, float)):
            values.append(float(elapsed))
    return values


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = _elapsed_values(rows)
    summary: dict[str, Any] = {
        "runs": len(rows),
        "successes": sum(1 for row in rows if row.get("success") is True),
        "failures": sum(1 for row in rows if row.get("success") is False),
    }
    if not elapsed:
        return summary

    summary.update(
        {
            "first_elapsed_sec": elapsed[0],
            "last_elapsed_sec": elapsed[-1],
            "mean_elapsed_sec": statistics.mean(elapsed),
            "median_elapsed_sec": statistics.median(elapsed),
            "min_elapsed_sec": min(elapsed),
            "max_elapsed_sec": max(elapsed),
        }
    )
    if len(elapsed) > 1:
        summary["repeat_mean_elapsed_sec"] = statistics.mean(elapsed[1:])
        summary["repeat_last_elapsed_sec"] = elapsed[-1]
    return summary


def _build_comparison_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["scenario"], row["mode"]), []).append(row)

    summary: dict[str, Any] = {"by_scenario_mode": {}, "speedups_vs_current_like": {}}
    per_scenario: dict[str, dict[str, dict[str, Any]]] = {}

    for (scenario_name, mode), group_rows in grouped.items():
        group_rows = sorted(group_rows, key=lambda item: int(item["repetition"]))
        per_scenario.setdefault(scenario_name, {})[mode] = _summarize_rows(group_rows)

    for scenario_name, mode_map in per_scenario.items():
        summary["by_scenario_mode"][scenario_name] = mode_map
        baseline = mode_map.get("random_workspace_random_session")
        if not baseline:
            continue
        baseline_value = baseline.get("repeat_mean_elapsed_sec") or baseline.get(
            "mean_elapsed_sec"
        )
        if not isinstance(baseline_value, (int, float)) or baseline_value <= 0:
            continue

        scenario_speedups: dict[str, float] = {}
        for mode, mode_summary in mode_map.items():
            mode_value = mode_summary.get(
                "repeat_mean_elapsed_sec"
            ) or mode_summary.get("mean_elapsed_sec")
            if isinstance(mode_value, (int, float)) and mode_value > 0:
                scenario_speedups[mode] = baseline_value / mode_value
        summary["speedups_vs_current_like"][scenario_name] = scenario_speedups

    return summary


def _run_parent(args: argparse.Namespace) -> int:
    script_path = Path(__file__).resolve()
    modes = list(MODES) if args.mode == "all" else [args.mode]
    scenarios = (
        list(SCENARIOS.values())
        if args.scenario == "all"
        else [SCENARIOS[args.scenario]]
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base_root = (
        Path(args.shared_root).expanduser().resolve()
        if args.shared_root
        else (Path(tempfile.gettempdir()) / "problemologist-cache-path-stability")
    )
    run_root = base_root / f"run-{timestamp}"
    run_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        for mode in modes:
            cache_root = run_root / "cache-roots" / scenario.name / mode
            workspace_root_base = run_root / "workspaces" / scenario.name / mode
            _configure_env(cache_root, force_cpu=args.force_cpu)
            for repetition in range(1, args.repetitions + 1):
                row = _run_one_repetition(
                    mode=mode,
                    scenario=scenario,
                    repetition=repetition,
                    backend=args.backend,
                    smoke_test_mode=args.smoke_test_mode,
                    particle_budget=args.particle_budget,
                    workspace_root_base=workspace_root_base,
                    cache_root=cache_root,
                    script_path=script_path,
                )
                rows.append(row)
                status = "ok" if row.get("success") else "failed"
                elapsed = row.get("elapsed_sec")
                elapsed_text = (
                    f"{elapsed:.3f}s" if isinstance(elapsed, (int, float)) else "n/a"
                )
                print(
                    f"[cache-path-stability] scenario={scenario.name} mode={mode} "
                    f"rep={repetition} status={status} elapsed={elapsed_text}",
                    flush=True,
                )

    summary = _build_comparison_summary(rows)
    result_payload = {
        "experiment": "integration_cache_path_stability",
        "generated_at": datetime.now(UTC).isoformat(),
        "backend": args.backend,
        "smoke_test_mode": args.smoke_test_mode,
        "force_cpu": args.force_cpu,
        "repetitions": args.repetitions,
        "base_root": str(base_root),
        "run_root": str(run_root),
        "modes": modes,
        "scenarios": [scenario.name for scenario in scenarios],
        "rows": rows,
        "summary": summary,
    }

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else (
            Path(__file__).resolve().parent
            / f"results-cache-path-stability-{timestamp}.json"
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"Wrote results to {output_path}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark repeated fresh-child simulate_subprocess runs while varying "
            "workspace-path stability and INT session-id stability."
        )
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--scenario",
        choices=("all", *SCENARIOS.keys()),
        default="all",
        help="Scenario to benchmark.",
    )
    parser.add_argument(
        "--mode",
        choices=("all", *MODES),
        default="all",
        help="Stability mode to benchmark.",
    )
    parser.add_argument(
        "--backend",
        choices=("GENESIS", "MUJOCO"),
        default="GENESIS",
        help="Simulation backend to use.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Number of fresh-child repetitions per scenario/mode.",
    )
    parser.add_argument(
        "--smoke-test-mode",
        type=_str_to_bool,
        default=True,
        help="Whether to run the simulation path in smoke-test mode.",
    )
    parser.add_argument(
        "--force-cpu",
        action="store_true",
        help="Set GENESIS_FORCE_CPU=1 for parent and child runs.",
    )
    parser.add_argument(
        "--particle-budget",
        type=str,
        default="none",
        help="Optional particle budget override; use 'none' to disable.",
    )
    parser.add_argument(
        "--shared-root",
        type=str,
        default=None,
        help="Optional parent directory for experiment work and cache roots.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional explicit JSON output path.",
    )
    parser.add_argument(
        "--session-root", type=str, default=None, help=argparse.SUPPRESS
    )
    parser.add_argument("--session-id", type=str, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.particle_budget == "none":
        args.particle_budget = None
    else:
        args.particle_budget = int(args.particle_budget)
    return args


def main() -> int:
    args = _parse_args()
    if args.force_cpu:
        os.environ["GENESIS_FORCE_CPU"] = "1"
    if args.child:
        if not args.session_root or not args.session_id:
            raise SystemExit("--child requires --session-root and --session-id")
        return _run_child_command(args)
    return _run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())
