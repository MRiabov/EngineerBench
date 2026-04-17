#!/usr/bin/env python3
"""Benchmark worker-heavy HTTP simulate latency with worker restart vs reuse."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]


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
}


def _bundle_base64_for_scenario(scenario: Scenario) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        script_bytes = (scenario.script_content + "\n").encode("utf-8")
        script_info = tarfile.TarInfo("script.py")
        script_info.size = len(script_bytes)
        tar.addfile(script_info, io.BytesIO(script_bytes))

        objectives_bytes = yaml.safe_dump(
            scenario.objectives,
            sort_keys=False,
        ).encode("utf-8")
        objectives_info = tarfile.TarInfo("objectives.yaml")
        objectives_info.size = len(objectives_bytes)
        tar.addfile(objectives_info, io.BytesIO(objectives_bytes))

    return base64.b64encode(buf.getvalue()).decode("ascii")


def _worker_env(root: Path, force_cpu: bool) -> dict[str, str]:
    cache_root = root / "cache-root"
    home_root = cache_root / "home"
    xdg_cache_root = cache_root / "xdg-cache"
    taichi_root = xdg_cache_root / "taichi"
    temp_root = cache_root / "tmp"
    sessions_root = root / "sessions"
    log_root = root / "logs"

    for path in (
        home_root,
        xdg_cache_root,
        taichi_root,
        temp_root,
        sessions_root,
        log_root,
    ):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}:{existing_pythonpath}" if existing_pythonpath else str(REPO_ROOT)
    )
    env["IS_INTEGRATION_TEST"] = "true"
    env["HOME"] = str(home_root)
    env["XDG_CACHE_HOME"] = str(xdg_cache_root)
    env["TAICHI_CACHE_DIR"] = str(taichi_root)
    env["TI_CACHE_HOME"] = str(taichi_root)
    env["TMPDIR"] = str(temp_root)
    env["TEMP"] = str(temp_root)
    env["TMP"] = str(temp_root)
    env["WORKER_SESSIONS_DIR"] = str(sessions_root)
    env["PYGLET_HEADLESS"] = "1"
    env.setdefault("PYOPENGL_PLATFORM", "egl")
    env["WORKER_TYPE"] = "heavy"
    env["EXTRA_DEBUG_LOG"] = str(log_root / "worker_heavy_debug.log")
    env["EXTRA_ERROR_LOG"] = str(log_root / "worker_heavy_errors.log")
    env["EXTRA_ERROR_JSON_LOG"] = str(log_root / "worker_heavy_errors.json")
    if force_cpu:
        env["GENESIS_FORCE_CPU"] = "1"
    return env


def _wait_for_ready(
    base_url: str,
    *,
    process: subprocess.Popen[str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: float = 120.0,
) -> None:
    deadline = time.monotonic() + timeout_s
    with httpx.Client(timeout=2.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout = stdout_path.read_text(encoding="utf-8", errors="ignore")
                stderr = stderr_path.read_text(encoding="utf-8", errors="ignore")
                raise RuntimeError(
                    "worker-heavy exited before ready "
                    f"(returncode={process.returncode})\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            try:
                response = client.get(f"{base_url}/ready")
                if response.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.5)
    stdout = stdout_path.read_text(encoding="utf-8", errors="ignore")
    stderr = stderr_path.read_text(encoding="utf-8", errors="ignore")
    raise RuntimeError(
        "worker-heavy did not become ready "
        f"within {timeout_s}s\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
    )


def _start_worker(root: Path, force_cpu: bool, port: int) -> subprocess.Popen[str]:
    env = _worker_env(root, force_cpu=force_cpu)
    uvicorn_bin = REPO_ROOT / ".venv" / "bin" / "uvicorn"
    log_root = root / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    stdout_path = log_root / "server_stdout.log"
    stderr_path = log_root / "server_stderr.log"
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(uvicorn_bin),
            "worker_heavy.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    try:
        _wait_for_ready(
            f"http://127.0.0.1:{port}",
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    except Exception:
        _stop_worker(process)
        raise
    finally:
        stdout_handle.close()
        stderr_handle.close()
    return process


def _stop_worker(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_one_request(
    *,
    base_url: str,
    bundle_base64: str,
    session_id: str,
) -> dict[str, Any]:
    start = time.perf_counter()
    with httpx.Client(timeout=180.0, trust_env=False) as client:
        response = client.post(
            f"{base_url}/benchmark/simulate",
            headers={"X-Session-ID": session_id},
            json={
                "script_path": "script.py",
                "bundle_base64": bundle_base64,
                "backend": "GENESIS",
                "smoke_test_mode": True,
            },
        )
    elapsed = time.perf_counter() - start
    payload: dict[str, Any] = {
        "status_code": response.status_code,
        "elapsed_sec": elapsed,
    }
    try:
        body = response.json()
    except Exception:
        payload["body_text"] = response.text
        return payload

    payload["success"] = body.get("success")
    payload["message"] = body.get("message")
    artifacts = body.get("artifacts") or {}
    failure = artifacts.get("failure") or {}
    payload["failure_reason"] = failure.get("reason")
    return payload


def _run_reuse_worker_mode(
    *,
    scenario: Scenario,
    repetitions: int,
    root: Path,
    force_cpu: bool,
    port: int,
) -> list[dict[str, Any]]:
    base_url = f"http://127.0.0.1:{port}"
    bundle = _bundle_base64_for_scenario(scenario)
    process = _start_worker(root / "reuse-worker", force_cpu=force_cpu, port=port)
    rows: list[dict[str, Any]] = []
    try:
        for repetition in range(1, repetitions + 1):
            session_id = f"INT-101-{uuid.uuid4().hex[:8]}"
            row = _run_one_request(
                base_url=base_url,
                bundle_base64=bundle,
                session_id=session_id,
            )
            row.update(
                {
                    "mode": "reuse_worker_process",
                    "repetition": repetition,
                    "session_id": session_id,
                }
            )
            rows.append(row)
    finally:
        _stop_worker(process)
    return rows


def _run_restart_worker_mode(
    *,
    scenario: Scenario,
    repetitions: int,
    root: Path,
    force_cpu: bool,
    port: int,
) -> list[dict[str, Any]]:
    bundle = _bundle_base64_for_scenario(scenario)
    rows: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        repetition_port = port + repetition - 1
        base_url = f"http://127.0.0.1:{repetition_port}"
        process = _start_worker(
            root / "restart-worker" / f"rep-{repetition}",
            force_cpu=force_cpu,
            port=repetition_port,
        )
        try:
            session_id = f"INT-101-{uuid.uuid4().hex[:8]}"
            row = _run_one_request(
                base_url=base_url,
                bundle_base64=bundle,
                session_id=session_id,
            )
            row.update(
                {
                    "mode": "restart_worker_process_per_request",
                    "repetition": repetition,
                    "session_id": session_id,
                }
            )
            rows.append(row)
        finally:
            _stop_worker(process)
    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in {row["mode"] for row in rows}:
        mode_rows = sorted(
            [row for row in rows if row["mode"] == mode],
            key=lambda item: int(item["repetition"]),
        )
        elapsed = [float(row["elapsed_sec"]) for row in mode_rows]
        by_mode[mode] = {
            "runs": len(mode_rows),
            "first_elapsed_sec": elapsed[0],
            "last_elapsed_sec": elapsed[-1],
            "mean_elapsed_sec": sum(elapsed) / len(elapsed),
            "successes": sum(1 for row in mode_rows if row.get("success") is True),
            "failures": sum(1 for row in mode_rows if row.get("success") is not True),
        }
        if len(elapsed) > 1:
            by_mode[mode]["repeat_mean_elapsed_sec"] = sum(elapsed[1:]) / len(
                elapsed[1:]
            )

    summary: dict[str, Any] = {"by_mode": by_mode}
    restart = by_mode.get("restart_worker_process_per_request")
    reuse = by_mode.get("reuse_worker_process")
    if restart and reuse:
        restart_value = restart.get("last_elapsed_sec")
        reuse_value = reuse.get("last_elapsed_sec")
        if (
            isinstance(restart_value, (int, float))
            and isinstance(
                reuse_value,
                (int, float),
            )
            and reuse_value > 0
        ):
            summary["second_request_speedup_reuse_vs_restart"] = (
                restart_value / reuse_value
            )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark worker-heavy HTTP simulate latency when the worker process "
            "is reused versus restarted between requests."
        )
    )
    parser.add_argument(
        "--scenario",
        choices=tuple(SCENARIOS.keys()),
        default="int101_like",
    )
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--force-cpu", action="store_true")
    parser.add_argument("--port", type=int, default=18102)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = Path(tempfile.gettempdir()) / f"worker-heavy-http-reuse-{timestamp}"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    scenario = SCENARIOS[args.scenario]
    rows = []
    rows.extend(
        _run_restart_worker_mode(
            scenario=scenario,
            repetitions=args.repetitions,
            root=root,
            force_cpu=args.force_cpu,
            port=args.port,
        )
    )
    rows.extend(
        _run_reuse_worker_mode(
            scenario=scenario,
            repetitions=args.repetitions,
            root=root,
            force_cpu=args.force_cpu,
            port=args.port,
        )
    )

    result = {
        "experiment": "worker_heavy_http_reuse",
        "generated_at": datetime.now(UTC).isoformat(),
        "scenario": scenario.name,
        "force_cpu": args.force_cpu,
        "repetitions": args.repetitions,
        "root": str(root),
        "rows": rows,
        "summary": _summarize(rows),
    }

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else Path(__file__).resolve().parent / f"results-{timestamp}.json"
    )
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    print(f"Wrote results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
