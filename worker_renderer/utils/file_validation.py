from __future__ import annotations

from typing import Any

import structlog
import yaml
from pydantic import ValidationError

from shared.enums import BenchmarkRefusalReason
from shared.models.schemas import BenchmarkDefinition
from worker_renderer.utils.workbench_config import load_config

logger = structlog.get_logger(__name__)


def _benchmark_refusal_error(reason: BenchmarkRefusalReason, message: str) -> str:
    return f"{reason.value}: {message}"


def _boxes_intersect(
    a_min: tuple[float, float, float],
    a_max: tuple[float, float, float],
    b_min: tuple[float, float, float],
    b_max: tuple[float, float, float],
) -> bool:
    return all(a_min[i] <= b_max[i] and b_min[i] <= a_max[i] for i in range(3))


def _validate_bounding_box_order(label: str, box: Any) -> str | None:
    for axis, min_value, max_value in zip(("x", "y", "z"), box.min_mm, box.max_mm):
        if min_value > max_value:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.INVALID_OBJECTIVES,
                f"{label} has inverted bounds on axis {axis}: "
                f"min {min_value} > max {max_value}",
            )
    return None


def _validate_non_negative_range(
    label: str, values: tuple[float, ...] | None
) -> str | None:
    if values is None:
        return None

    if any(value < 0 for value in values):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.INVALID_OBJECTIVES,
            f"{label} must be non-negative; got {list(values)}",
        )

    if len(values) == 2 and values[0] > values[1]:
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.INVALID_OBJECTIVES,
            f"{label} minimum must be <= maximum; got {list(values)}",
        )

    return None


def _validate_benchmark_definition_consistency(
    objectives: BenchmarkDefinition,
) -> str | None:
    goal_zone = objectives.objectives.goal_zone_mm
    build_zone = objectives.objectives.build_zone_mm

    for label, box in (
        ("goal_zone_mm", goal_zone),
        ("build_zone_mm", build_zone),
        ("simulation_bounds_mm", objectives.simulation_bounds_mm),
    ):
        box_error = _validate_bounding_box_order(label, box)
        if box_error is not None:
            return box_error

    for zone in objectives.objectives.forbid_zones:
        zone_error = _validate_bounding_box_order(f"forbid zone '{zone.name}'", zone)
        if zone_error is not None:
            return zone_error
        if _boxes_intersect(
            goal_zone.min_mm, goal_zone.max_mm, zone.min_mm, zone.max_mm
        ):
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.CONTRADICTORY_CONSTRAINTS,
                f"goal_zone_mm overlaps forbid zone '{zone.name}'",
            )

    if not _boxes_intersect(
        goal_zone.min_mm, goal_zone.max_mm, build_zone.min_mm, build_zone.max_mm
    ):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "goal_zone_mm does not overlap build_zone_mm",
        )

    jitter = objectives.payload.runtime_jitter_mm
    start = objectives.payload.start_position_mm
    jitter_error = _validate_non_negative_range("payload.runtime_jitter_mm", jitter)
    if jitter_error is not None:
        return jitter_error

    radius_max = 0.0
    radius_range = objectives.payload.static_randomization.radius_mm
    radius_error = _validate_non_negative_range(
        "payload.static_randomization.radius_mm", radius_range
    )
    if radius_error is not None:
        return radius_error
    if radius_range:
        radius_max = max(radius_range)

    moved_min = (
        start[0] - jitter[0] - radius_max,
        start[1] - jitter[1] - radius_max,
        start[2] - jitter[2] - radius_max,
    )
    moved_max = (
        start[0] + jitter[0] + radius_max,
        start[1] + jitter[1] + radius_max,
        start[2] + jitter[2] + radius_max,
    )

    if not _boxes_intersect(moved_min, moved_max, build_zone.min_mm, build_zone.max_mm):
        return _benchmark_refusal_error(
            BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
            "payload runtime envelope does not overlap build_zone_mm",
        )

    for i, axis in enumerate(("x", "y", "z")):
        if moved_min[i] < build_zone.min_mm[i] or moved_max[i] > build_zone.max_mm[i]:
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.UNSOLVABLE_SCENARIO,
                f"payload runtime envelope exceeds build_zone_mm on axis {axis}",
            )

    for zone in objectives.objectives.forbid_zones:
        if _boxes_intersect(moved_min, moved_max, zone.min_mm, zone.max_mm):
            return _benchmark_refusal_error(
                BenchmarkRefusalReason.CONTRADICTORY_CONSTRAINTS,
                "payload runtime envelope intersects forbid zone "
                f"'{zone.name}' across jitter/randomization",
            )

    return None


def validate_benchmark_definition_yaml(
    content: str, session_id: str | None = None
) -> tuple[bool, BenchmarkDefinition | list[str]]:
    try:
        data = yaml.safe_load(content)
        if data is None:
            return False, ["Empty or invalid YAML content"]

        benchmark_parts = data.get("benchmark_parts")
        if not isinstance(benchmark_parts, list) or not benchmark_parts:
            return False, [
                "benchmark_definition.yaml must declare at least one benchmark_parts entry"
            ]

        objectives = BenchmarkDefinition(**data)

        material_id = objectives.payload.material_id
        manufacturing_config = load_config()
        known_material_ids = set(manufacturing_config.materials.keys())
        known_material_ids.update(manufacturing_config.cnc.materials.keys())
        known_material_ids.update(
            manufacturing_config.injection_molding.materials.keys()
        )
        known_material_ids.update(manufacturing_config.three_dp.materials.keys())
        if material_id not in known_material_ids:
            return False, [
                "payload.material_id must reference a known material from "
                f"manufacturing_config.yaml (got '{material_id}')"
            ]

        objective_error = _validate_benchmark_definition_consistency(objectives)
        if objective_error:
            logger.error(
                "benchmark_definition_yaml_invalid",
                errors=[objective_error],
                session_id=session_id,
            )
            return False, [objective_error]

        logger.info("benchmark_definition_yaml_valid", session_id=session_id)
        return True, objectives
    except yaml.YAMLError as e:
        logger.error(
            "benchmark_definition_yaml_parse_error", error=str(e), session_id=session_id
        )
        return False, [f"YAML parse error: {e}"]
    except ValidationError as e:
        errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
        logger.error(
            "benchmark_definition_yaml_validation_error",
            errors=errors,
            session_id=session_id,
        )
        return False, errors
