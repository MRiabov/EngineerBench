#!/usr/bin/env python3
"""Probe eval workspace display handling for Codex-launched runs.

This experiment captures the root cause behind the recent Xvfb failures:

1. What does the eval workspace launcher export for `DISPLAY` and `XAUTHORITY`?
2. Does the worker-side headless display bootstrap still consider the ambient
   display usable?
3. What display-related environment reaches the spawned agent process?

The goal is to keep a small reproducible record of the environment behavior that
determines whether validation renders stay on the ambient display path or fall
back to private Xvfb.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from worker_heavy.utils.vtk_display import ensure_headless_vtk_display

from evals.logic.codex_workspace import build_codex_env
from shared.enums import AgentName


def _current_env_snapshot() -> dict[str, Any]:
    return {
        "DISPLAY": os.environ.get("DISPLAY"),
        "XAUTHORITY": os.environ.get("XAUTHORITY"),
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
        "GNOME_SETUP_DISPLAY": os.environ.get("GNOME_SETUP_DISPLAY"),
    }


def _codex_env_snapshot() -> dict[str, Any]:
    env = build_codex_env(
        task_id="syntax-display-probe",
        workspace_dir=Path(),
        codex_home_root=Path("/tmp/codex-home-syntax-display-probe"),
        agent_name=AgentName.ENGINEER_CODER,
    )
    return {
        "DISPLAY": env.get("DISPLAY"),
        "XAUTHORITY": env.get("XAUTHORITY"),
        "MUJOCO_GL": env.get("MUJOCO_GL"),
        "PYOPENGL_PLATFORM": env.get("PYOPENGL_PLATFORM"),
        "PYVISTA_OFF_SCREEN": env.get("PYVISTA_OFF_SCREEN"),
        "VTK_DEFAULT_OPENGL_WINDOW": env.get("VTK_DEFAULT_OPENGL_WINDOW"),
    }


def main() -> None:
    report = {
        "cwd": os.getcwd(),
        "current_env": _current_env_snapshot(),
        "codex_env": _codex_env_snapshot(),
        "ambient_vtk_display": None,
        "ambient_vtk_display_error": None,
    }

    try:
        report["ambient_vtk_display"] = ensure_headless_vtk_display()
    except Exception as exc:
        report["ambient_vtk_display_error"] = str(exc)

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
