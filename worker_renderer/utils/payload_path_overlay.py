from __future__ import annotations

from pathlib import Path

import yaml

from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    PayloadTrajectoryDefinition,
)


def resolve_payload_path_points(
    workspace_root: Path,
    *,
    benchmark_definition: BenchmarkDefinition | None = None,
) -> list[tuple[float, float, float]] | None:
    """Resolve the best available payload-path polyline for overlay rendering.

    Only real motion artifacts are eligible. If the workspace does not contain
    an engineer payload trajectory or a planner motion forecast, the renderer
    returns no overlay instead of inventing a benchmark start-to-goal line.
    """

    candidate_files = (
        workspace_root / "payload_trajectory_definition.yaml",
        workspace_root / "assembly_definition.yaml",
    )

    for candidate in candidate_files:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            raw_payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(raw_payload, dict):
            continue

        if candidate.name == "payload_trajectory_definition.yaml":
            try:
                definition = PayloadTrajectoryDefinition.model_validate(raw_payload)
            except Exception:
                continue
            points: list[tuple[float, float, float]] = []
            initial_point = _as_point3(definition.initial_pose.pos_mm)
            if initial_point is not None:
                points.append(initial_point)
            for anchor in definition.anchors:
                point = _as_point3(anchor.pos_mm)
                if point is not None:
                    points.append(point)
            if len(points) >= 2:
                return points
            continue

        try:
            definition = AssemblyDefinition.model_validate(raw_payload)
        except Exception:
            continue
        motion_forecast = definition.motion_forecast
        if motion_forecast is None:
            continue
        points = [
            point
            for point in (
                _as_point3(anchor.pos_mm) for anchor in motion_forecast.anchors
            )
            if point is not None
        ]
        if len(points) >= 2:
            return points

    if benchmark_definition is not None:
        # Keep the argument for call-site compatibility. The benchmark
        # definition is used as the enclosing workspace context, but it is not
        # a motion artifact and should not be promoted into a fake overlay.
        _ = benchmark_definition

    return None


def _as_point3(value: object) -> tuple[float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return (float(value[0]), float(value[1]), float(value[2]))
        except (TypeError, ValueError):
            return None
    return None
