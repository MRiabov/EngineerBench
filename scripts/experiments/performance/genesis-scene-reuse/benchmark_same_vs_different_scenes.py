#!/usr/bin/env python3
"""Measure same-scene vs different-scene build cost inside one warm process."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import trimesh


def _configure_env() -> None:
    cache_root = Path("/tmp/codex-genesis-scene-reuse")
    home_root = cache_root / "home"
    xdg_cache_root = cache_root / "xdg-cache"
    home_root.mkdir(parents=True, exist_ok=True)
    xdg_cache_root.mkdir(parents=True, exist_ok=True)

    os.environ["PYGLET_HEADLESS"] = "1"
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("HOME", str(home_root))
    os.environ.setdefault("XDG_CACHE_HOME", str(xdg_cache_root))


@dataclass
class SceneMeasurement:
    name: str
    scene_create_s: float
    scene_build_s: float
    scene_step_s: float


def _resolve_backend(gs: Any, backend_name: str):
    if backend_name == "cpu":
        return gs.cpu, "cpu"
    if backend_name == "gpu":
        return gs.gpu, "gpu"
    if backend_name != "auto":
        raise ValueError(f"Unsupported backend {backend_name}")

    import torch

    force_cpu = os.getenv("GENESIS_FORCE_CPU", "0") == "1"
    has_gpu = torch.cuda.is_available() and not force_cpu
    return (gs.gpu if has_gpu else gs.cpu), ("gpu" if has_gpu else "cpu")


def _build_scene(
    gs: Any, entity_factory: Callable[[Any], Any], name: str
) -> SceneMeasurement:
    create_t0 = time.perf_counter()
    scene = gs.Scene(show_viewer=False)
    scene.add_entity(gs.morphs.Plane())
    scene.add_entity(entity_factory(gs))
    scene_create_s = time.perf_counter() - create_t0

    build_t0 = time.perf_counter()
    scene.build()
    scene_build_s = time.perf_counter() - build_t0

    step_t0 = time.perf_counter()
    scene.step()
    scene_step_s = time.perf_counter() - step_t0

    return SceneMeasurement(
        name=name,
        scene_create_s=scene_create_s,
        scene_build_s=scene_build_s,
        scene_step_s=scene_step_s,
    )


def _make_mesh_assets(tmpdir: Path) -> dict[str, Path]:
    box_path = tmpdir / "box.obj"
    sphere_path = tmpdir / "sphere.obj"

    trimesh.creation.box(extents=(1.0, 1.0, 1.0)).export(box_path)
    trimesh.creation.icosphere(subdivisions=1, radius=0.75).export(sphere_path)

    return {
        "box": box_path,
        "sphere": sphere_path,
    }


def _diff_report(first: SceneMeasurement, second: SceneMeasurement) -> dict[str, float]:
    return {
        "build_delta_s": second.scene_build_s - first.scene_build_s,
        "build_ratio": second.scene_build_s / first.scene_build_s
        if first.scene_build_s > 0
        else 0.0,
        "create_delta_s": second.scene_create_s - first.scene_create_s,
        "create_ratio": second.scene_create_s / first.scene_create_s
        if first.scene_create_s > 0
        else 0.0,
    }


def run_experiment(backend_name: str) -> dict[str, Any]:
    _configure_env()

    import genesis as gs

    backend, resolved_backend = _resolve_backend(gs, backend_name)

    init_t0 = time.perf_counter()
    gs.init(backend=backend, logging_level="warning")
    init_s = time.perf_counter() - init_t0

    with tempfile.TemporaryDirectory(prefix="genesis-scene-reuse-") as tmp:
        assets = _make_mesh_assets(Path(tmp))

        primitive_box_1 = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Box(pos=(0, 0, 1), size=(1, 1, 1)),
            "primitive_box_1",
        )
        primitive_box_2_same = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Box(pos=(0, 0, 1), size=(1, 1, 1)),
            "primitive_box_2_same",
        )
        primitive_sphere_1_diff = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Sphere(pos=(0, 0, 1), radius=0.75),
            "primitive_sphere_1_diff",
        )
        primitive_box_3_after_sphere = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Box(pos=(0, 0, 1), size=(1, 1, 1)),
            "primitive_box_3_after_sphere",
        )

        mesh_box_1 = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Mesh(file=str(assets["box"]), pos=(0, 0, 1)),
            "mesh_box_1",
        )
        mesh_box_2_same = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Mesh(file=str(assets["box"]), pos=(0, 0, 1)),
            "mesh_box_2_same",
        )
        mesh_sphere_1_diff = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Mesh(
                file=str(assets["sphere"]), pos=(0, 0, 1)
            ),
            "mesh_sphere_1_diff",
        )
        mesh_box_3_after_sphere = _build_scene(
            gs,
            lambda gs_mod: gs_mod.morphs.Mesh(file=str(assets["box"]), pos=(0, 0, 1)),
            "mesh_box_3_after_sphere",
        )

    primitive_rows = [
        asdict(primitive_box_1),
        asdict(primitive_box_2_same),
        asdict(primitive_sphere_1_diff),
        asdict(primitive_box_3_after_sphere),
    ]
    mesh_rows = [
        asdict(mesh_box_1),
        asdict(mesh_box_2_same),
        asdict(mesh_sphere_1_diff),
        asdict(mesh_box_3_after_sphere),
    ]

    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "backend_request": backend_name,
        "resolved_backend": resolved_backend,
        "env": {
            "GENESIS_FORCE_CPU": os.getenv("GENESIS_FORCE_CPU", ""),
            "PYGLET_HEADLESS": os.getenv("PYGLET_HEADLESS", ""),
            "PYOPENGL_PLATFORM": os.getenv("PYOPENGL_PLATFORM", ""),
        },
        "init_s": init_s,
        "primitive_sequence": primitive_rows,
        "primitive_analysis": {
            "same_vs_first": _diff_report(primitive_box_1, primitive_box_2_same),
            "diff_vs_first": _diff_report(primitive_box_1, primitive_sphere_1_diff),
            "diff_vs_same": _diff_report(primitive_box_2_same, primitive_sphere_1_diff),
            "box_after_diff_vs_first": _diff_report(
                primitive_box_1, primitive_box_3_after_sphere
            ),
            "box_after_diff_vs_same": _diff_report(
                primitive_box_2_same, primitive_box_3_after_sphere
            ),
            "box_after_diff_vs_diff": _diff_report(
                primitive_sphere_1_diff, primitive_box_3_after_sphere
            ),
        },
        "mesh_sequence": mesh_rows,
        "mesh_analysis": {
            "same_vs_first": _diff_report(mesh_box_1, mesh_box_2_same),
            "diff_vs_first": _diff_report(mesh_box_1, mesh_sphere_1_diff),
            "diff_vs_same": _diff_report(mesh_box_2_same, mesh_sphere_1_diff),
            "box_after_diff_vs_first": _diff_report(
                mesh_box_1, mesh_box_3_after_sphere
            ),
            "box_after_diff_vs_same": _diff_report(
                mesh_box_2_same, mesh_box_3_after_sphere
            ),
            "box_after_diff_vs_diff": _diff_report(
                mesh_sphere_1_diff, mesh_box_3_after_sphere
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("auto", "cpu", "gpu"), default="cpu")
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    report = run_experiment(args.backend)

    output_path = args.output_json.strip()
    if not output_path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = (
            Path(__file__).resolve().parent / f"results-{timestamp}.json"
        ).as_posix()

    Path(output_path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
