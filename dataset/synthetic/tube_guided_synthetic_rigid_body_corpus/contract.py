from __future__ import annotations

import json
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from build123d import Compound

from shared.enums import ManufacturingMethod
from shared.models.schemas import BenchmarkDefinition, PayloadTrajectoryDefinition
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.workbench_models import ManufacturingConfig

from .geometry import route_bbox
from .models import PartSpec, RoutePoint
from .paths import REPO_ROOT, load_yaml


def payload_extent_mm(benchmark_definition: BenchmarkDefinition) -> float:
    payload = benchmark_definition.payload
    shape = str(getattr(payload, "shape", "sphere")).strip().lower()
    static_randomization = getattr(payload, "static_randomization", None)
    radius_range = getattr(static_randomization, "radius_mm", None)
    if radius_range is None:
        radius_range = getattr(static_randomization, "radius", None)
    radius = float(max(radius_range)) if radius_range else None

    if shape == "sphere":
        return 2.0 * (radius if radius is not None else 1.0)
    if shape in {"cube", "box"}:
        return (2.0 * radius) if radius is not None else 1.0
    if shape == "cylinder":
        return 2.0 * (radius if radius is not None else 1.0)
    return 2.0 * (radius if radius is not None else 1.0)


def normalize_benchmark_contract_dict(data: dict[str, Any]) -> dict[str, Any]:
    objectives = (
        data.get("objectives") if isinstance(data.get("objectives"), dict) else {}
    )
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    constraints = (
        data.get("constraints") if isinstance(data.get("constraints"), dict) else {}
    )
    randomization = (
        data.get("randomization") if isinstance(data.get("randomization"), dict) else {}
    )
    physics = data.get("physics") if isinstance(data.get("physics"), dict) else {}

    normalized_benchmark_parts: list[dict[str, Any]] = []
    for part in data.get("benchmark_parts", []):
        if not isinstance(part, dict):
            normalized_benchmark_parts.append(part)
            continue
        metadata = (
            part.get("metadata") if isinstance(part.get("metadata"), dict) else {}
        )
        normalized_benchmark_parts.append(
            {
                "part_id": part.get("part_id"),
                "label": part.get("label"),
                "metadata": {
                    "is_fixed": metadata.get("is_fixed")
                    if metadata.get("is_fixed") is not None
                    else metadata.get("fixed"),
                    "material_id": metadata.get("material_id"),
                },
            }
        )

    normalized = {
        "objectives": {
            "goal_zone_mm": objectives.get("goal_zone_mm")
            or objectives.get("goal_zone"),
            "forbid_zones": [],
            "build_zone_mm": objectives.get("build_zone_mm")
            or objectives.get("build_zone"),
        },
        "benchmark_parts": normalized_benchmark_parts,
        "physics": physics,
        "simulation_bounds_mm": data.get("simulation_bounds_mm")
        or data.get("simulation_bounds"),
        "payload": {
            "label": payload.get("label"),
            "shape": payload.get("shape"),
            "material_id": payload.get("material_id"),
            "static_randomization": {
                "radius_mm": (
                    payload.get("static_randomization", {}).get("radius_mm")
                    if isinstance(payload.get("static_randomization"), dict)
                    else None
                )
                or (
                    payload.get("static_randomization", {}).get("radius")
                    if isinstance(payload.get("static_randomization"), dict)
                    else None
                ),
            },
            "start_position_mm": payload.get("start_position_mm")
            or payload.get("start_position"),
            "runtime_jitter_mm": payload.get("runtime_jitter_mm")
            or payload.get("runtime_jitter"),
        },
        "constraints": constraints,
        "randomization": randomization,
        "assembly_totals": data.get("assembly_totals"),
    }

    for zone in objectives.get("forbid_zones", []):
        if not isinstance(zone, dict):
            continue
        normalized["objectives"]["forbid_zones"].append(
            {
                "name": zone.get("name"),
                "min_mm": zone.get("min_mm") or zone.get("min"),
                "max_mm": zone.get("max_mm") or zone.get("max"),
            }
        )

    return normalized


def scale_benchmark_definition_to_mm(
    benchmark_definition: BenchmarkDefinition,
    *,
    scale: float = 1.0,
) -> BenchmarkDefinition:
    data = normalize_benchmark_contract_dict(
        benchmark_definition.model_dump(mode="json")
    )

    def scale_point(point: list[float] | tuple[float, float, float] | None):
        if point is None:
            return None
        return [float(value) * scale for value in point]

    def scale_bbox(box: dict[str, list[float]] | None):
        if not isinstance(box, dict):
            return box
        scaled = dict(box)
        for key in ("min_mm", "min"):
            if key in scaled:
                scaled[key] = scale_point(scaled[key])
        for key in ("max_mm", "max"):
            if key in scaled:
                scaled[key] = scale_point(scaled[key])
        return scaled

    objectives = (
        data.get("objectives") if isinstance(data.get("objectives"), dict) else {}
    )
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    constraints = (
        data.get("constraints") if isinstance(data.get("constraints"), dict) else {}
    )
    simulation_bounds = data.get("simulation_bounds_mm")

    if isinstance(objectives, dict):
        if "goal_zone_mm" in objectives:
            objectives["goal_zone_mm"] = scale_bbox(objectives.get("goal_zone_mm"))
        if "build_zone_mm" in objectives:
            objectives["build_zone_mm"] = scale_bbox(objectives.get("build_zone_mm"))
        if "forbid_zones" in objectives and isinstance(
            objectives["forbid_zones"], list
        ):
            scaled_forbid_zones = []
            for zone in objectives["forbid_zones"]:
                if not isinstance(zone, dict):
                    scaled_forbid_zones.append(zone)
                    continue
                zone_scaled = dict(zone)
                if "min_mm" in zone_scaled:
                    zone_scaled["min_mm"] = scale_point(zone_scaled.get("min_mm"))
                if "max_mm" in zone_scaled:
                    zone_scaled["max_mm"] = scale_point(zone_scaled.get("max_mm"))
                scaled_forbid_zones.append(zone_scaled)
            objectives["forbid_zones"] = scaled_forbid_zones

    if isinstance(payload, dict):
        if payload.get("start_position_mm") is not None:
            payload["start_position_mm"] = scale_point(payload.get("start_position_mm"))
        static_randomization = (
            payload.get("static_randomization")
            if isinstance(payload.get("static_randomization"), dict)
            else {}
        )
        if static_randomization.get("radius_mm") is not None:
            static_randomization["radius_mm"] = [
                float(value) * scale for value in static_randomization["radius_mm"]
            ]
        payload["static_randomization"] = static_randomization
        if payload.get("runtime_jitter_mm") is not None:
            payload["runtime_jitter_mm"] = [
                float(value) * scale for value in payload["runtime_jitter_mm"]
            ]

    if isinstance(simulation_bounds, dict):
        data["simulation_bounds_mm"] = scale_bbox(simulation_bounds)
    if isinstance(constraints, dict):
        for key in (
            "estimated_solution_cost_usd",
            "estimated_solution_weight_g",
            "max_unit_cost",
            "max_weight_g",
            "target_quantity",
        ):
            constraints[key] = constraints.get(key)

    return BenchmarkDefinition.model_validate(data)


def expanded_bounding_box(
    route_points: list[RoutePoint],
    envelope_mm: float,
    margin_mm: float,
) -> dict[str, list[float]]:
    lower, upper = route_bbox(route_points)
    lower = lower - np.array(
        [margin_mm, margin_mm, envelope_mm + margin_mm], dtype=float
    )
    upper = upper + np.array(
        [margin_mm, margin_mm, envelope_mm + margin_mm], dtype=float
    )
    return {
        "min_mm": [float(v) for v in lower.tolist()],
        "max_mm": [float(v) for v in upper.tolist()],
    }


def load_benchmark_definition(bundle_dir: Path) -> BenchmarkDefinition:
    raw = load_yaml(bundle_dir / "benchmark_definition.yaml")
    if not isinstance(raw, dict):
        raise ValueError("benchmark_definition.yaml must deserialize to a mapping")
    return BenchmarkDefinition.model_validate(normalize_benchmark_contract_dict(raw))


def synthetic_benchmark_definition(
    benchmark_definition: BenchmarkDefinition,
    *,
    route_points: list[RoutePoint],
    envelope_mm: float,
    margin_mm: float,
) -> dict[str, Any]:
    benchmark_data = normalize_benchmark_contract_dict(
        benchmark_definition.model_dump(mode="json")
    )
    bbox = expanded_bounding_box(
        route_points, envelope_mm=envelope_mm, margin_mm=margin_mm
    )
    benchmark_data["objectives"]["build_zone_mm"] = bbox
    benchmark_data["simulation_bounds_mm"] = bbox
    benchmark_data["payload"]["label"] = "slider_ball"
    benchmark_data["payload"]["shape"] = "sphere"
    benchmark_data["payload"]["start_position_mm"] = [
        float(v) for v in route_points[0].pos_mm
    ]
    benchmark_data["constraints"]["estimated_solution_cost_usd"] = None
    benchmark_data["constraints"]["estimated_solution_weight_g"] = None
    return benchmark_data


def make_planner_constraints(
    benchmark_definition: BenchmarkDefinition, total_cost: float, total_weight: float
) -> dict[str, float]:
    benchmark_max_cost = float(
        benchmark_definition.constraints.max_unit_cost or total_cost
    )
    benchmark_max_weight = float(
        benchmark_definition.constraints.max_weight_g or total_weight
    )
    target_cost = min(
        benchmark_max_cost, round(max(total_cost * 1.25, total_cost + 0.01), 2)
    )
    target_weight = min(
        benchmark_max_weight, round(max(total_weight * 1.25, total_weight + 0.01), 2)
    )
    return {
        "benchmark_max_unit_cost_usd": round(benchmark_max_cost, 2),
        "benchmark_max_weight_g": round(benchmark_max_weight, 2),
        "planner_target_max_unit_cost_usd": round(target_cost, 2),
        "planner_target_max_weight_g": round(target_weight, 2),
    }


def manufactured_part_entry(part, quantity: int = 1) -> dict[str, Any]:
    bbox = part.bounding_box()
    stock_bbox = {
        "x": round(float(bbox.size.X), 3),
        "y": round(float(bbox.size.Y), 3),
        "z": round(float(bbox.size.Z), 3),
    }
    return {
        "part_name": part.label,
        "part_id": part.label,
        "manufacturing_method": ManufacturingMethod.CNC.value,
        "material_id": str(getattr(part.metadata, "material_id", "aluminum_6061")),
        "quantity": quantity,
        "part_volume_mm3": round(float(part.volume), 3),
        "stock_bbox_mm": stock_bbox,
        "stock_volume_mm3": round(
            stock_bbox["x"] * stock_bbox["y"] * stock_bbox["z"], 3
        ),
        "removed_volume_mm3": round(
            stock_bbox["x"] * stock_bbox["y"] * stock_bbox["z"] - float(part.volume), 3
        ),
        "estimated_unit_cost_usd": 0.0,
        "pricing_notes": "Generated by tube-guided synthetic corpus notebook",
        "dfm_suggestions": [],
    }


def _resolve_cnc_material(
    part,
    workbench_config,
) -> tuple[str, Any, Any]:
    cnc_cfg = getattr(workbench_config, "cnc", None)
    if cnc_cfg is None:
        raise ValueError("Manufacturing config does not define CNC costing")

    metadata = getattr(part, "metadata", None)
    material_name = getattr(metadata, "material_id", None)
    if not material_name:
        material_name = workbench_config.defaults.get("material")
    if not material_name:
        material_name = next(iter(cnc_cfg.materials.keys()), None)
    if not material_name:
        raise ValueError("Could not resolve a CNC material for the part")

    material_name = str(material_name).strip()
    material_cfg = cnc_cfg.materials.get(
        material_name
    ) or workbench_config.materials.get(material_name)
    if material_cfg is None:
        raise ValueError(f"Unknown CNC material_id '{material_name}'")
    return material_name, material_cfg, cnc_cfg


def estimate_cnc_manufacturing(
    part,
    workbench_config,
    quantity: int = 1,
) -> tuple[dict[str, Any], float, float]:
    material_name, material_cfg, cnc_cfg = _resolve_cnc_material(part, workbench_config)
    bbox = part.bounding_box()
    stock_bbox = {
        "x": round(float(bbox.size.X), 3),
        "y": round(float(bbox.size.Y), 3),
        "z": round(float(bbox.size.Z), 3),
    }
    stock_volume_mm3 = float(stock_bbox["x"] * stock_bbox["y"] * stock_bbox["z"])
    part_volume_mm3 = max(float(part.volume), 1e-6)
    removed_volume_mm3 = max(stock_volume_mm3 - part_volume_mm3, 0.0)

    density_g_cm3 = float(material_cfg.density_g_cm3)
    cost_per_kg = float(material_cfg.cost_per_kg)
    stock_mass_g = (stock_volume_mm3 / 1000.0) * density_g_cm3
    part_mass_g = (part_volume_mm3 / 1000.0) * density_g_cm3
    material_cost_per_part = (stock_mass_g / 1000.0) * cost_per_kg

    mrr_mm3_per_min = float(getattr(cnc_cfg.constraints, "mrr_mm3_per_min", 1000.0))
    machine_hourly_rate = float(
        getattr(material_cfg, "machine_hourly_rate", 0.0) or 0.0
    )
    if machine_hourly_rate <= 0.0:
        machine_hourly_rate = 120.0
    machining_time_min = max(stock_volume_mm3 / max(mrr_mm3_per_min, 1.0), 0.5)
    run_cost_per_part = (machining_time_min / 60.0) * machine_hourly_rate
    setup_cost = float(getattr(cnc_cfg.costs, "setup_fee", 80.0))
    total_cost = setup_cost + (material_cost_per_part + run_cost_per_part) * quantity
    unit_cost = total_cost / max(quantity, 1)

    entry = manufactured_part_entry(part, quantity=quantity)
    entry["material_id"] = material_name
    entry["part_volume_mm3"] = round(part_volume_mm3, 3)
    entry["stock_volume_mm3"] = round(stock_volume_mm3, 3)
    entry["removed_volume_mm3"] = round(removed_volume_mm3, 3)
    entry["estimated_unit_cost_usd"] = round(unit_cost, 2)
    entry["pricing_notes"] = (
        f"CNC estimate from stock envelope {stock_bbox['x']}x{stock_bbox['y']}x{stock_bbox['z']} mm "
        f"using {material_name}, {round(machining_time_min, 2)} min runtime, "
        f"{round(part_mass_g, 3)} g part mass."
    )
    entry["dfm_suggestions"] = []
    return entry, round(total_cost, 2), round(part_mass_g * quantity, 2)


def annotate_manufactured_parts(
    parts: list, config
) -> tuple[list[dict[str, Any]], float, float]:
    workbench_config = load_manufacturing_config()
    entries: list[dict[str, Any]] = []
    total_cost = 0.0
    total_weight = 0.0
    for part in parts:
        entry, part_cost, part_weight = estimate_cnc_manufacturing(
            part, workbench_config
        )
        entries.append(entry)
        total_cost += part_cost
        total_weight += part_weight
    return entries, round(total_cost, 2), round(total_weight, 2)


def coarse_payload_trajectory_dict(
    *,
    payload_name: str,
    route_points: list[RoutePoint],
    first_contacts: list[str],
    terminal_reference_point: str,
    sample_stride_s: float,
) -> dict[str, Any]:
    anchors = []
    for idx, point in enumerate(route_points):
        anchor = {
            "t_s": float(point.t_s if point.t_s is not None else idx * sample_stride_s),
            "reference_point": point.name,
            "pos_mm": [float(v) for v in point.pos_mm],
            "rot_deg": [0.0, 0.0, 0.0],
            "position_tolerance_mm": [1.2, 1.2, 1.2],
            "rotation_tolerance_deg": [0.1, 0.1, 5.0],
        }
        if idx == 0:
            anchor["build_zone_valid"] = True
            anchor["first_contacts"] = [
                {
                    "order": order + 1,
                    "surface": surface,
                    "first_touch_window_s": [0.0, sample_stride_s],
                }
                for order, surface in enumerate(first_contacts)
            ]
        if idx == len(route_points) - 1:
            anchor["goal_zone_contact"] = True
        anchors.append(anchor)
    return {
        "payload_part_names": [payload_name],
        "reference_frame": "world",
        "sample_stride_s": sample_stride_s,
        "anchors": anchors,
        "terminal_event": None,
    }


def payload_trajectory_dict(
    *,
    payload_name: str,
    route_points: list[RoutePoint],
    first_contacts: list[str],
    terminal_reference_point: str,
    backend: SimulatorBackendType,
    sample_stride_s: float,
) -> dict[str, Any]:
    anchors = []
    for idx, point in enumerate(route_points):
        anchor = {
            "t_s": float(point.t_s if point.t_s is not None else idx * sample_stride_s),
            "reference_point": point.name,
            "pos_mm": [float(v) for v in point.pos_mm],
            "rot_deg": [0.0, 0.0, 0.0],
            "position_tolerance_mm": [1.2, 1.2, 1.2],
            "rotation_tolerance_deg": [0.1, 0.1, 5.0],
        }
        if idx == 0:
            anchor["build_zone_valid"] = True
            anchor["first_contacts"] = [
                {
                    "order": order + 1,
                    "surface": surface,
                    "first_touch_window_s": [0.0, sample_stride_s],
                }
                for order, surface in enumerate(first_contacts)
            ]
        if idx == len(route_points) - 1:
            anchor["goal_zone_contact"] = True
        anchors.append(anchor)
    return {
        "backend": backend.value,
        "payload_part_names": [payload_name],
        "initial_pose": {
            "reference_point": route_points[0].name,
            "pos_mm": [float(v) for v in route_points[0].pos_mm],
            "rot_deg": [0.0, 0.0, 0.0],
        },
        "sample_stride_s": sample_stride_s,
        "anchors": anchors,
        "terminal_event": None,
    }


from .text_templates import (
    build_engineering_plan_text,
    build_evidence_script_text,
    build_markdown_templates,
    build_route_lowering_script_text,
    build_journal_text,
    build_payload_trajectory_template_text,
    build_solution_description_text,
    build_solution_script_text,
    build_todo_text,
    selected_side_map_literal,
)


def load_manufacturing_config() -> ManufacturingConfig:
    config_path = REPO_ROOT / "worker_heavy" / "workbenches" / "manufacturing_config.yaml"
    data = load_yaml(config_path)
    return ManufacturingConfig.model_validate(data or {})
