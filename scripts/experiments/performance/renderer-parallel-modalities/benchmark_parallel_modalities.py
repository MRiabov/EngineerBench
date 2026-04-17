#!/usr/bin/env python3
"""Benchmark preview modality rendering.

This experiment isolates the code path in
``render_preview_scene_bundle(...)``. Parallel modality rendering is only
supported in smoke-test mode; non-smoke runs stay sequential and fail closed if
parallel mode is requested.

It uses a synthetic scene so the benchmark can run without worker HTTP or
seed-bundle staging. That keeps the measurement focused on render-loop
behavior rather than admission, serialization, or retry noise.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics
import sys
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.agents.config import load_agents_config
from worker_renderer.utils.build123d_rendering import (
    PreviewEntity,
    PreviewScene,
    _PreviewModalityRenderResult,
    _render_preview_modality_bundle,
    render_preview_scene_bundle,
)

RESULT_PREFIX = "__EXPERIMENT_RESULT__="


@dataclass(frozen=True)
class RunRecord:
    mode: str
    repetition: int
    order_index: int
    warmup: bool
    parallel_modalities: bool
    elapsed_sec: float
    render_count: int
    success: bool
    error: str | None = None
    traceback: str | None = None


@dataclass(frozen=True)
class ModeSummary:
    count: int
    mean_sec: float | None
    median_sec: float | None
    min_sec: float | None
    max_sec: float | None
    stdev_sec: float | None
    mean_render_count: float | None


@dataclass(frozen=True)
class ExperimentSummary:
    parallel: ModeSummary
    sequential: ModeSummary
    parallel_minus_sequential_sec: float | None
    parallel_to_sequential_ratio: float | None
    parallel_slower: bool | None


def _str_to_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


@contextlib.contextmanager
def _temporary_env(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def _make_palette() -> list[tuple[float, float, float]]:
    return [
        (0.90, 0.35, 0.28),
        (0.27, 0.60, 0.88),
        (0.34, 0.73, 0.41),
        (0.86, 0.66, 0.24),
        (0.68, 0.42, 0.88),
        (0.27, 0.78, 0.72),
        (0.92, 0.48, 0.60),
        (0.46, 0.52, 0.90),
    ]


def _build_probe_scene() -> tuple[PreviewScene, list[tuple[float, float, float]]]:
    palette = _make_palette()
    entities: list[PreviewEntity] = []
    index = 0

    grid_positions = [
        (-210.0, -120.0, 24.0),
        (-70.0, -120.0, 24.0),
        (70.0, -120.0, 24.0),
        (210.0, -120.0, 24.0),
        (-210.0, 0.0, 40.0),
        (-70.0, 0.0, 40.0),
        (70.0, 0.0, 40.0),
        (210.0, 0.0, 40.0),
        (-210.0, 120.0, 56.0),
        (-70.0, 120.0, 56.0),
        (70.0, 120.0, 56.0),
        (210.0, 120.0, 56.0),
        (-140.0, -40.0, 84.0),
        (0.0, -40.0, 92.0),
        (140.0, -40.0, 84.0),
        (-140.0, 80.0, 120.0),
        (0.0, 80.0, 128.0),
        (140.0, 80.0, 120.0),
    ]

    for pos_index, pos in enumerate(grid_positions):
        palette_index = pos_index % len(palette)
        box_size = (
            26.0 + (pos_index % 3) * 3.0,
            18.0 + (pos_index % 2) * 2.0,
            16.0 + (pos_index % 4) * 2.0,
        )
        entities.append(
            PreviewEntity(
                label=f"probe_box_{pos_index}",
                semantic_label=f"probe_box_{pos_index}",
                instance_id=f"probe_box_{pos_index}",
                instance_name=f"probe_box_{pos_index}",
                object_type="part",
                object_id=index,
                pos=pos,
                euler=(0.0, 0.0, float((pos_index * 17) % 90)),
                mesh_paths=[],
                box_size=box_size,
                material_id=None,
                body_name=f"probe_box_{pos_index}",
                geom_name=None,
                color_rgba=(*palette[palette_index], 1.0),
                segmentation_color_rgb=(
                    70 + (pos_index * 17) % 170,
                    80 + (pos_index * 29) % 150,
                    90 + (pos_index * 41) % 140,
                ),
                include_in_segmentation=True,
            )
        )
        index += 1

    zone_specs = [
        (
            "zone_goal",
            "goal",
            (250.0, 0.0, 70.0),
            (52.0, 58.0, 48.0),
            (0.20, 0.72, 0.34, 0.22),
        ),
        (
            "zone_build",
            "build",
            (0.0, 0.0, 80.0),
            (380.0, 240.0, 180.0),
            (0.55, 0.55, 0.55, 0.14),
        ),
        (
            "zone_forbid_0",
            "forbid",
            (-150.0, 140.0, 80.0),
            (90.0, 60.0, 60.0),
            (0.83, 0.20, 0.20, 0.20),
        ),
    ]
    for label, zone_type, pos, box_size, color_rgba in zone_specs:
        entities.append(
            PreviewEntity(
                label=label,
                semantic_label=label,
                instance_id=label,
                instance_name=label,
                object_type="zone",
                object_id=index,
                pos=pos,
                euler=(0.0, 0.0, 0.0),
                mesh_paths=[],
                box_size=box_size,
                material_id=None,
                body_name=None,
                geom_name=None,
                zone_type=zone_type,
                color_rgba=color_rgba,
                segmentation_color_rgb=(
                    210 + (index * 13) % 40,
                    150 + (index * 7) % 60,
                    60 + (index * 11) % 80,
                ),
                include_in_segmentation=False,
            )
        )
        index += 1

    bounds_min = (-420.0, -260.0, -80.0)
    bounds_max = (420.0, 260.0, 220.0)
    center = tuple((bounds_min[i] + bounds_max[i]) / 2.0 for i in range(3))
    diagonal = sum((bounds_max[i] - bounds_min[i]) ** 2 for i in range(3)) ** 0.5
    scene = PreviewScene(
        component_label="parallel_modality_probe",
        entities=entities,
        bounds_min=bounds_min,
        bounds_max=bounds_max,
        center=center,
        diagonal=max(diagonal, 1e-6),
    )

    payload_path_points = [
        (-310.0, -150.0, 10.0),
        (-180.0, -60.0, 18.0),
        (-40.0, 0.0, 36.0),
        (90.0, 60.0, 72.0),
        (220.0, 110.0, 116.0),
        (320.0, 150.0, 144.0),
    ]
    return scene, payload_path_points


def _render_once(
    *,
    scene: PreviewScene,
    payload_path_points: list[tuple[float, float, float]],
    parallel_modalities: bool,
    smoke_test_mode: bool,
) -> RunRecord:
    render_policy = load_agents_config().render
    with tempfile.TemporaryDirectory(prefix="renderer-parallel-modalities-") as tmpdir:
        output_root = Path(tmpdir)
        output_dir = output_root / "renders" / "parallel_modalities_probe"
        output_dir.mkdir(parents=True, exist_ok=True)

        if parallel_modalities and not smoke_test_mode:
            raise NotImplementedError(
                "Parallel modality rendering is only supported in smoke-test "
                "mode. Run with --smoke-test-mode true to exercise it."
            )

        modality_jobs: list[str] = []
        if render_policy.rgb.enabled:
            modality_jobs.append("rgb")
        if render_policy.depth.enabled:
            modality_jobs.append("depth")
        if render_policy.segmentation.enabled:
            modality_jobs.append("segmentation")

        def _run_sequential_modalities() -> dict[str, _PreviewModalityRenderResult]:
            center = scene.center
            distance = (
                sum((scene.bounds_max[i] - scene.bounds_min[i]) ** 2 for i in range(3))
            ) ** 0.5
            # Reuse the same camera spacing helper as the production renderer.
            from worker_renderer.utils.build123d_rendering import (
                _preview_camera_distance,
            )

            distance = _preview_camera_distance(
                scene,
                width=render_policy.image_resolution.width,
                height=render_policy.image_resolution.height,
            )
            angles = [0, 45, 90, 135, 180, 225, 270, 315]
            elevations = [-15, -45, -75]
            view_specs = [
                (elevation, angle) for elevation in elevations for angle in angles
            ]
            if smoke_test_mode:
                view_specs = [(-45.0, 45.0)]

            render_results: dict[str, _PreviewModalityRenderResult] = {}
            for modality in modality_jobs:
                render_results[modality] = _render_preview_modality_bundle(
                    scene,
                    output_dir=output_dir,
                    workspace_root=output_root,
                    center=center,
                    distance=distance,
                    width=render_policy.image_resolution.width,
                    height=render_policy.image_resolution.height,
                    preview_label="parallel_modality_probe",
                    view_specs=view_specs,
                    include_payload_path_overlay=render_policy.handoff_rgb_payload_path_overlay.enabled,
                    payload_path_points=payload_path_points,
                    modality=modality,
                    rgb_axes=render_policy.rgb.axes,
                    rgb_edges=render_policy.rgb.edges,
                    depth_axes=render_policy.depth.axes,
                    depth_edges=render_policy.depth.edges,
                    segmentation_axes=render_policy.segmentation.axes,
                    segmentation_edges=render_policy.segmentation.edges,
                )
            return render_results

        start = time.perf_counter()
        try:
            if parallel_modalities and smoke_test_mode:
                with _temporary_env(
                    "PROBLEMOLOGIST_RENDER_PARALLEL_MODALITIES",
                    "true",
                ):
                    render_result = render_preview_scene_bundle(
                        scene.model_copy(deep=True),
                        output_dir=output_dir,
                        workspace_root=output_root,
                        smoke_test_mode=smoke_test_mode,
                        include_rgb=render_policy.rgb.enabled,
                        include_depth=render_policy.depth.enabled,
                        include_segmentation=render_policy.segmentation.enabled,
                        rgb_axes=render_policy.rgb.axes,
                        rgb_edges=render_policy.rgb.edges,
                        depth_axes=render_policy.depth.axes,
                        depth_edges=render_policy.depth.edges,
                        segmentation_axes=render_policy.segmentation.axes,
                        segmentation_edges=render_policy.segmentation.edges,
                        payload_path_points=payload_path_points,
                        include_payload_path_overlay=render_policy.handoff_rgb_payload_path_overlay.enabled,
                    )
                render_count = len(render_result.saved_paths)
            else:
                render_results = _run_sequential_modalities()
                render_count = sum(
                    len(result.saved_paths) for result in render_results.values()
                )
                render_result = None
            elapsed_sec = time.perf_counter() - start
            return RunRecord(
                mode="parallel" if parallel_modalities else "sequential",
                repetition=0,
                order_index=0,
                warmup=False,
                parallel_modalities=parallel_modalities,
                elapsed_sec=elapsed_sec,
                render_count=render_count,
                success=True,
            )
        except Exception as exc:
            elapsed_sec = time.perf_counter() - start
            return RunRecord(
                mode="parallel" if parallel_modalities else "sequential",
                repetition=0,
                order_index=0,
                warmup=False,
                parallel_modalities=parallel_modalities,
                elapsed_sec=elapsed_sec,
                render_count=0,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )


def _summarize(records: list[RunRecord], *, mode: str) -> ModeSummary:
    mode_records = [
        record for record in records if record.mode == mode and record.success
    ]
    if not mode_records:
        return ModeSummary(
            count=0,
            mean_sec=None,
            median_sec=None,
            min_sec=None,
            max_sec=None,
            stdev_sec=None,
            mean_render_count=None,
        )

    elapsed = [record.elapsed_sec for record in mode_records]
    render_counts = [record.render_count for record in mode_records]
    return ModeSummary(
        count=len(mode_records),
        mean_sec=statistics.mean(elapsed),
        median_sec=statistics.median(elapsed),
        min_sec=min(elapsed),
        max_sec=max(elapsed),
        stdev_sec=statistics.stdev(elapsed) if len(elapsed) > 1 else None,
        mean_render_count=statistics.mean(render_counts),
    )


def _summarize_experiment(records: list[RunRecord]) -> ExperimentSummary:
    parallel = _summarize(records, mode="parallel")
    sequential = _summarize(records, mode="sequential")

    if parallel.mean_sec is None or sequential.mean_sec is None:
        return ExperimentSummary(
            parallel=parallel,
            sequential=sequential,
            parallel_minus_sequential_sec=None,
            parallel_to_sequential_ratio=None,
            parallel_slower=None,
        )

    return ExperimentSummary(
        parallel=parallel,
        sequential=sequential,
        parallel_minus_sequential_sec=parallel.mean_sec - sequential.mean_sec,
        parallel_to_sequential_ratio=parallel.mean_sec / sequential.mean_sec,
        parallel_slower=parallel.mean_sec > sequential.mean_sec,
    )


def _write_result_file(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark whether parallel RGB/depth/segmentation rendering helps "
            "or hurts on the current headless renderer backend."
        )
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="Number of timed runs per mode after warmups.",
    )
    parser.add_argument(
        "--warmup-runs",
        type=int,
        default=1,
        help="Number of untimed warmup runs per mode.",
    )
    parser.add_argument(
        "--smoke-test-mode",
        type=_str_to_bool,
        default=False,
        help="Reduce the scene to one view for a quick sanity check.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional explicit JSON output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be >= 1")
    if args.warmup_runs < 0:
        raise SystemExit("--warmup-runs must be >= 0")

    scene, payload_path_points = _build_probe_scene()

    records: list[RunRecord] = []
    warmup_modes = [True, False] if args.smoke_test_mode else [False]
    for mode_index, parallel_modalities in enumerate(warmup_modes, start=1):
        for warmup_index in range(args.warmup_runs):
            record = _render_once(
                scene=scene,
                payload_path_points=payload_path_points,
                parallel_modalities=parallel_modalities,
                smoke_test_mode=args.smoke_test_mode,
            )
            records.append(
                RunRecord(
                    mode=record.mode,
                    repetition=warmup_index + 1,
                    order_index=mode_index,
                    warmup=True,
                    parallel_modalities=record.parallel_modalities,
                    elapsed_sec=record.elapsed_sec,
                    render_count=record.render_count,
                    success=record.success,
                    error=record.error,
                    traceback=record.traceback,
                )
            )

    for repetition in range(1, args.repetitions + 1):
        if args.smoke_test_mode:
            order = [True, False] if repetition % 2 == 1 else [False, True]
        else:
            order = [False]
        for order_index, parallel_modalities in enumerate(order, start=1):
            record = _render_once(
                scene=scene,
                payload_path_points=payload_path_points,
                parallel_modalities=parallel_modalities,
                smoke_test_mode=args.smoke_test_mode,
            )
            records.append(
                RunRecord(
                    mode=record.mode,
                    repetition=repetition,
                    order_index=order_index,
                    warmup=False,
                    parallel_modalities=record.parallel_modalities,
                    elapsed_sec=record.elapsed_sec,
                    render_count=record.render_count,
                    success=record.success,
                    error=record.error,
                    traceback=record.traceback,
                )
            )

    summary = _summarize_experiment(records)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = (
        Path(args.output)
        if args.output
        else Path(__file__).with_name(f"results-parallel-modalities-{timestamp}.json")
    )

    payload = {
        "experiment": "renderer_parallel_modalities",
        "timestamp_utc": timestamp,
        "repo_root": str(REPO_ROOT),
        "scene": {
            "component_label": scene.component_label,
            "entity_count": len(scene.entities),
            "bounds_min": scene.bounds_min,
            "bounds_max": scene.bounds_max,
            "diagonal": scene.diagonal,
        },
        "payload_path_points": payload_path_points,
        "render_policy": load_agents_config().render.model_dump(mode="json"),
        "repetitions": args.repetitions,
        "warmup_runs": args.warmup_runs,
        "smoke_test_mode": args.smoke_test_mode,
        "summary": asdict(summary),
        "rows": [asdict(record) for record in records],
    }
    _write_result_file(payload, output_path)

    print(
        json.dumps(
            {
                "output": str(output_path),
                "summary": asdict(summary),
            },
            sort_keys=True,
        )
    )
    print(f"{RESULT_PREFIX}{json.dumps(payload, sort_keys=True)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
