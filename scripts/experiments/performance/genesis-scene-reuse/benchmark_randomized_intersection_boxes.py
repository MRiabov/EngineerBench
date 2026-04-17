#!/usr/bin/env python3
"""Benchmark warm-process scene build cost using unique randomized intersected boxes."""

from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import trimesh
from build123d import Box, Pos, export_stl


@dataclass
class GeometrySpec:
    name: str
    box1_dims: tuple[float, float, float]
    box2_dims: tuple[float, float, float]
    offset: tuple[float, float, float]
    box1_volume: float
    box2_volume: float
    intersection_volume: float
    intersection_strictly_smaller_than_each_input: bool
    solids_count: int
    obj_path: str


@dataclass
class SceneMeasurement:
    name: str
    scene_create_s: float
    scene_build_s: float
    scene_step_s: float
    geometry: GeometrySpec


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


def _configure_env(cache_root: Path) -> None:
    home_root = cache_root / "home"
    xdg_cache_root = cache_root / "xdg-cache"
    home_root.mkdir(parents=True, exist_ok=True)
    xdg_cache_root.mkdir(parents=True, exist_ok=True)

    os.environ["PYGLET_HEADLESS"] = "1"
    os.environ["PYOPENGL_PLATFORM"] = "egl"
    os.environ["HOME"] = str(home_root)
    os.environ["XDG_CACHE_HOME"] = str(xdg_cache_root)


def _random_dims(rng: random.Random) -> tuple[float, float, float]:
    return (
        round(rng.uniform(0.8, 1.7), 4),
        round(rng.uniform(0.8, 1.7), 4),
        round(rng.uniform(0.8, 1.7), 4),
    )


def _make_intersection_geometry(
    *,
    name: str,
    assets_dir: Path,
    rng: random.Random,
) -> GeometrySpec:
    for _ in range(100):
        box1_dims = _random_dims(rng)
        box2_dims = _random_dims(rng)

        min_dim_x = min(box1_dims[0], box2_dims[0])
        max_containment_offset_x = abs(box1_dims[0] - box2_dims[0]) / 2.0
        half_sum_x = (box1_dims[0] + box2_dims[0]) / 2.0

        # Force partial overlap on X so the intersection is strictly smaller
        # than both original boxes while remaining a single convex body.
        partial_low = max_containment_offset_x + max(0.05, 0.12 * min_dim_x)
        partial_high = half_sum_x - max(0.05, 0.12 * min_dim_x)
        if partial_low >= partial_high:
            continue

        sign = -1.0 if rng.random() < 0.5 else 1.0
        offset_x = sign * rng.uniform(partial_low, partial_high)
        offset_y = rng.uniform(
            -0.15 * min(box1_dims[1], box2_dims[1]),
            0.15 * min(box1_dims[1], box2_dims[1]),
        )
        offset_z = rng.uniform(
            -0.15 * min(box1_dims[2], box2_dims[2]),
            0.15 * min(box1_dims[2], box2_dims[2]),
        )

        box1 = Box(*box1_dims)
        box2 = Box(*box2_dims).move(Pos(offset_x, offset_y, offset_z))
        intersection = box1 & box2

        if len(intersection.solids()) != 1:
            continue

        box1_volume = float(box1.volume)
        box2_volume = float(box2.volume)
        intersection_volume = float(intersection.volume)
        strictly_smaller = (
            intersection_volume < box1_volume - 1e-9
            and intersection_volume < box2_volume - 1e-9
        )
        if not strictly_smaller:
            continue

        stl_path = assets_dir / f"{name}.stl"
        obj_path = assets_dir / f"{name}.obj"
        export_stl(intersection, stl_path)
        trimesh.load(stl_path).export(obj_path)

        return GeometrySpec(
            name=name,
            box1_dims=box1_dims,
            box2_dims=box2_dims,
            offset=(round(offset_x, 4), round(offset_y, 4), round(offset_z, 4)),
            box1_volume=box1_volume,
            box2_volume=box2_volume,
            intersection_volume=intersection_volume,
            intersection_strictly_smaller_than_each_input=strictly_smaller,
            solids_count=len(intersection.solids()),
            obj_path=str(obj_path),
        )

    raise RuntimeError(f"Failed to generate valid intersected geometry for {name}")


def _build_scene(gs: Any, geometry: GeometrySpec) -> SceneMeasurement:
    create_t0 = time.perf_counter()
    scene = gs.Scene(show_viewer=False)
    scene.add_entity(gs.morphs.Plane())
    scene.add_entity(gs.morphs.Mesh(file=geometry.obj_path, pos=(0, 0, 1)))
    scene_create_s = time.perf_counter() - create_t0

    build_t0 = time.perf_counter()
    scene.build()
    scene_build_s = time.perf_counter() - build_t0

    step_t0 = time.perf_counter()
    scene.step()
    scene_step_s = time.perf_counter() - step_t0

    return SceneMeasurement(
        name=geometry.name,
        scene_create_s=scene_create_s,
        scene_build_s=scene_build_s,
        scene_step_s=scene_step_s,
        geometry=geometry,
    )


def _ratio(a: float, b: float) -> float:
    return a / b if b > 0 else 0.0


def run_experiment(backend_name: str, seed: int, case_count: int) -> dict[str, Any]:
    rng = random.Random(seed)

    with tempfile.TemporaryDirectory(
        prefix="genesis-randomized-intersection-boxes-"
    ) as tmp:
        temp_root = Path(tmp)
        _configure_env(temp_root / "cache-root")

        import genesis as gs

        backend, resolved_backend = _resolve_backend(gs, backend_name)

        init_t0 = time.perf_counter()
        gs.init(backend=backend, logging_level="warning")
        init_s = time.perf_counter() - init_t0

        assets_dir = temp_root / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        measurements: list[SceneMeasurement] = []
        for idx in range(case_count):
            geometry = _make_intersection_geometry(
                name=f"random_intersection_box_{idx + 1}",
                assets_dir=assets_dir,
                rng=rng,
            )
            measurements.append(_build_scene(gs, geometry))

    rows = [asdict(row) for row in measurements]
    first = measurements[0]

    per_case_analysis: dict[str, dict[str, float]] = {}
    for row in measurements[1:]:
        per_case_analysis[row.name] = {
            "build_ratio_vs_first": _ratio(row.scene_build_s, first.scene_build_s),
            "build_delta_vs_first_s": row.scene_build_s - first.scene_build_s,
            "create_ratio_vs_first": _ratio(row.scene_create_s, first.scene_create_s),
            "create_delta_vs_first_s": row.scene_create_s - first.scene_create_s,
        }

    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "backend_request": backend_name,
        "resolved_backend": resolved_backend,
        "seed": seed,
        "case_count": case_count,
        "env": {
            "GENESIS_FORCE_CPU": os.getenv("GENESIS_FORCE_CPU", ""),
            "PYGLET_HEADLESS": os.getenv("PYGLET_HEADLESS", ""),
            "PYOPENGL_PLATFORM": os.getenv("PYOPENGL_PLATFORM", ""),
        },
        "init_s": init_s,
        "sequence": rows,
        "analysis": {
            "first_case_name": first.name,
            "first_case_build_s": first.scene_build_s,
            "first_case_create_s": first.scene_create_s,
            "unique_geometry_count": len({row.geometry.name for row in measurements}),
            "all_intersections_valid": all(
                row.geometry.intersection_strictly_smaller_than_each_input
                and row.geometry.solids_count == 1
                for row in measurements
            ),
            "per_case_vs_first": per_case_analysis,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("auto", "cpu", "gpu"), default="cpu")
    parser.add_argument("--seed", type=int, default=20260309)
    parser.add_argument("--case-count", type=int, default=4)
    parser.add_argument("--output-json", default="")
    args = parser.parse_args()

    report = run_experiment(
        backend_name=args.backend,
        seed=args.seed,
        case_count=args.case_count,
    )

    output_path = args.output_json.strip()
    if not output_path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_path = (
            Path(__file__).resolve().parent
            / f"results-randomized-boxes-{timestamp}.json"
        ).as_posix()

    Path(output_path).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
