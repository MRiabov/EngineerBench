#!/usr/bin/env python3
"""Probe whether the current renderer stack can launch and complete Render().

The goal is to keep a tiny, reproducible record of the launch paths we tried
while debugging the VTK migration:

1. Does a minimal offscreen VTK render survive in a clean subprocess?
2. Does the build123d preview renderer survive with the same headless setup?
3. Which render window class is actually selected in each case?

Each scenario runs in its own subprocess so a segfault still leaves structured
evidence in the parent process.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


LATEST_JSON = Path(__file__).with_name("latest-render-launchability.json")


@dataclass(frozen=True)
class Scenario:
    name: str
    mode: str
    extra_env: dict[str, str]


CHILD_CODE = dedent(
    """
    from __future__ import annotations

    import faulthandler
    import json
    import os
    import tempfile
    from pathlib import Path

    faulthandler.enable()

    mode = os.environ["PROBE_MODE"]
    report: dict[str, object] = {
        "mode": mode,
        "cwd": os.getcwd(),
        "env": {
            "DISPLAY": os.environ.get("DISPLAY"),
            "XAUTHORITY": os.environ.get("XAUTHORITY"),
            "MUJOCO_GL": os.environ.get("MUJOCO_GL"),
            "PYOPENGL_PLATFORM": os.environ.get("PYOPENGL_PLATFORM"),
            "PYVISTA_OFF_SCREEN": os.environ.get("PYVISTA_OFF_SCREEN"),
            "VTK_DEFAULT_OPENGL_WINDOW": os.environ.get("VTK_DEFAULT_OPENGL_WINDOW"),
        },
        "window_class": None,
        "available_window_classes": {},
        "rendered": False,
        "output_path": None,
    }

    if mode == "vtk":
        from shared.rendering.headless import (
            configure_headless_vtk_egl,
            create_headless_vtk_render_window,
        )

        configure_headless_vtk_egl()

        import vtk
        from vtkmodules.vtkFiltersSources import vtkSphereSource
        from vtkmodules.vtkRenderingCore import (
            vtkActor,
            vtkPolyDataMapper,
            vtkRenderer,
        )

        try:
            from vtkmodules.vtkRenderingOpenGL2 import vtkEGLRenderWindow
        except Exception:
            vtkEGLRenderWindow = None
        try:
            from vtkmodules.vtkRenderingOpenGL2 import vtkOSOpenGLRenderWindow
        except Exception:
            vtkOSOpenGLRenderWindow = None
        report["available_window_classes"] = {
            "vtkRenderWindow": True,
            "vtkEGLRenderWindow": vtkEGLRenderWindow is not None,
            "vtkOSOpenGLRenderWindow": vtkOSOpenGLRenderWindow is not None,
        }

        renderer = vtkRenderer()
        window = create_headless_vtk_render_window()
        report["window_class"] = type(window).__name__
        window.AddRenderer(renderer)
        window.SetSize(128, 128)

        sphere = vtkSphereSource()
        sphere.SetRadius(0.5)
        sphere.SetThetaResolution(24)
        sphere.SetPhiResolution(24)
        sphere.Update()

        mapper = vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())

        actor = vtkActor()
        actor.SetMapper(mapper)
        renderer.AddActor(actor)
        renderer.ResetCamera()
        window.Render()
        report["rendered"] = True

    elif mode == "build123d":
        from build123d import Box
        from worker_renderer.utils.build123d_rendering import (
            PreviewEntity,
            PreviewScene,
            render_preview_scene,
        )

        box = Box(10, 10, 10)
        _ = box

        scene = PreviewScene(
            entities=[
                PreviewEntity(
                    label="box",
                    semantic_label="box",
                    instance_id="box",
                    instance_name="box",
                    object_type="part",
                    object_id=1,
                    pos=(0.0, 0.0, 0.0),
                    euler=(0.0, 0.0, 0.0),
                    box_size=(0.5, 0.5, 0.5),
                    segmentation_color_rgb=(255, 0, 0),
                )
            ],
            bounds_min=(-1.0, -1.0, -1.0),
            bounds_max=(1.0, 1.0, 1.0),
            center=(0.0, 0.0, 0.0),
            diagonal=3.4641016151377544,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            image_path = render_preview_scene(
                scene,
                output_dir=output_dir,
                width=128,
                height=128,
                include_axes=False,
                include_edges=False,
            )
            report["rendered"] = True
            report["output_path"] = str(image_path)

    else:
        raise ValueError(f"unknown mode: {mode}")

    print(json.dumps(report, sort_keys=True))
    """
)


def _tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONFAULTHANDLER", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _run_child(scenario: Scenario) -> dict[str, Any]:
    env = _base_env()
    env.update(scenario.extra_env)
    env["PROBE_MODE"] = scenario.mode

    completed = subprocess.run(
        [sys.executable, "-c", CHILD_CODE],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )

    parsed: dict[str, Any] | None = None
    stdout = completed.stdout.strip()
    if stdout:
        try:
            parsed = json.loads(stdout.splitlines()[-1])
        except Exception:
            parsed = None

    return {
        "scenario": scenario.name,
        "mode": scenario.mode,
        "returncode": completed.returncode,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
        "parsed_report": parsed,
    }


def run_probe() -> dict[str, Any]:
    scenarios = [
        Scenario(
            name="vtk_egl_default",
            mode="vtk",
            extra_env={
                "VTK_DEFAULT_OPENGL_WINDOW": "vtkEGLRenderWindow",
                "PYOPENGL_PLATFORM": "egl",
                "PYVISTA_OFF_SCREEN": "true",
                "MUJOCO_GL": "egl",
            },
        ),
        Scenario(
            name="vtk_osmesa",
            mode="vtk",
            extra_env={
                "VTK_DEFAULT_OPENGL_WINDOW": "vtkOSOpenGLRenderWindow",
                "PYOPENGL_PLATFORM": "osmesa",
                "PYVISTA_OFF_SCREEN": "true",
                "MUJOCO_GL": "egl",
                "LIBGL_ALWAYS_SOFTWARE": "1",
            },
        ),
        Scenario(
            name="build123d_egl_preview",
            mode="build123d",
            extra_env={
                "VTK_DEFAULT_OPENGL_WINDOW": "vtkEGLRenderWindow",
                "PYOPENGL_PLATFORM": "egl",
                "PYVISTA_OFF_SCREEN": "true",
                "MUJOCO_GL": "egl",
            },
        ),
    ]

    return {
        "probe_name": "renderer_launchability_probe",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "repo_root": str(REPO_ROOT),
        "scenarios": [_run_child(scenario) for scenario in scenarios],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-out",
        type=Path,
        default=LATEST_JSON,
        help="Where to write the JSON report.",
    )
    args = parser.parse_args()

    payload = run_probe()
    args.json_out.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
