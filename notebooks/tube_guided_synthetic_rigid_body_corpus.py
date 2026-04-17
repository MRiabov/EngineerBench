"""Synthetic tube-guided rigid-body corpus generator.

This module is the execution core behind the Jupyter notebook driver.
It stages a scratch tube scaffold, runs batched jittered verification,
captures the wall-contact cloud, prunes the scaffold into simple box
primitives, and exports planner/coder row bundles plus dataset row records.
"""

from __future__ import annotations

import json
import math
import random
import re
import runpy
import shutil
import sys
import textwrap
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import structlog
import yaml
from build123d import (
    Align,
    Box,
    BuildLine,
    BuildPart,
    BuildSketch,
    Circle,
    Compound,
    Location,
    Plane,
    Polyline,
    sweep,
)
from scipy.spatial.transform import Rotation as SciPyRotation

from shared.enums import AgentName, ManufacturingMethod
from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    CompoundMetadata,
    PartMetadata,
)
from shared.simulation.backends import SimulationScene
from shared.simulation.schemas import SimulatorBackendType
from shared.workers.workbench_models import ManufacturingConfig

logger = structlog.get_logger(__name__)


def notebook_log_path(scenario_id: str) -> Path:
    return NOTEBOOK_LOG_DIR / f"{scenario_id}.log"


def append_notebook_log(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


class NotebookLogCapture:
    def __init__(self, path: Path):
        self.path = path
        self._stdout = StringIO()
        self._stderr = StringIO()

    def __enter__(self):
        append_notebook_log(self.path, "=== notebook run start ===")
        self._stdout_cm = redirect_stdout(self._stdout)
        self._stderr_cm = redirect_stderr(self._stderr)
        self._stdout_cm.__enter__()
        self._stderr_cm.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stdout_cm.__exit__(exc_type, exc, tb)
        self._stderr_cm.__exit__(exc_type, exc, tb)
        stdout_value = self._stdout.getvalue().strip()
        stderr_value = self._stderr.getvalue().strip()
        if stdout_value:
            append_notebook_log(self.path, "--- stdout ---")
            append_notebook_log(self.path, stdout_value)
        if stderr_value:
            append_notebook_log(self.path, "--- stderr ---")
            append_notebook_log(self.path, stderr_value)
        if exc_type is not None:
            append_notebook_log(
                self.path, f"=== notebook run failed: {exc_type.__name__}: {exc} ==="
            )
        else:
            append_notebook_log(self.path, "=== notebook run completed ===")
        return False


def progress_iter(iterable, desc: str):
    try:
        from tqdm.auto import tqdm

        return tqdm(iterable, desc=desc, leave=False)
    except Exception:
        return iterable


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "specs" / "desired_architecture.md").exists():
            return candidate
    raise FileNotFoundError("Could not locate the repository root")


ROOT = find_repo_root(Path(__file__).resolve().parent)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NOTEBOOK_LOG_DIR = ROOT / "logs" / "notebook"
NOTEBOOK_LOG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class RoutePoint:
    name: str
    pos_mm: tuple[float, float, float]
    t_s: float | None = None


@dataclass(frozen=True)
class SegmentSpan:
    segment_index: int
    split_index: int
    start_mm: tuple[float, float, float]
    end_mm: tuple[float, float, float]


@dataclass(frozen=True)
class PartSpec:
    name: str
    segment_index: int
    split_index: int
    side: str
    dims_mm: tuple[float, float, float]
    center_mm: tuple[float, float, float]
    euler_deg: tuple[float, float, float]
    material_id: str = "aluminum_6061"
    manufacturing_method: ManufacturingMethod = ManufacturingMethod.CNC
    fixed: bool = True


@dataclass(frozen=True)
class ContactHit:
    time_s: float
    position_mm: tuple[float, float, float]
    payload_body: str
    other_body: str
    force_n: tuple[float, float, float]


@dataclass
class ScenarioConfig:
    scenario_id: str
    benchmark_bundle_dir: Path
    planner_row_id: str
    coder_row_id: str
    route_points: list[RoutePoint]
    scratch_root: Path
    promote_to_dataset: bool = False
    emit_debug_plots: bool = True
    batch_width_range: tuple[int, int] = (10, 20)
    success_threshold: float = 0.8
    backend_order: tuple[SimulatorBackendType, ...] = (SimulatorBackendType.MUJOCO,)
    retry_seeds: tuple[int, ...] = (11, 19, 29)
    clearance_mm: float = 2.0
    wall_thickness_mm: float = 2.0
    max_segment_mm: float = 72.0
    route_margin_mm: float = 8.0
    material_id: str = "aluminum_6061"
    markdown_mode: str = "template"

    @property
    def staged_planner_root(self) -> Path:
        return self.scratch_root / "engineer_planner" / self.planner_row_id

    @property
    def staged_coder_root(self) -> Path:
        return self.scratch_root / "engineer_coder" / self.coder_row_id


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_manufacturing_config() -> ManufacturingConfig:
    config_path = ROOT / "worker_heavy" / "workbenches" / "manufacturing_config.yaml"
    data = load_yaml(config_path)
    return ManufacturingConfig.model_validate(data or {})


def dump_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=False,
        ),
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def payload_scene_name(label: str) -> str:
    return f"benchmark_payload__{str(label).strip()}"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def load_benchmark_build_fn(bundle_dir: Path):
    namespace = runpy.run_path(str(bundle_dir / "benchmark_script.py"))
    build_fn = namespace.get("build")
    if build_fn is None:
        raise KeyError(f"{bundle_dir / 'benchmark_script.py'} does not define build()")
    return build_fn


def as_np(point: Iterable[float]) -> np.ndarray:
    return np.asarray(tuple(float(v) for v in point), dtype=float)


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0:
        raise ValueError("zero-length vector")
    return vector / norm


def frame_from_segment(
    start_mm: Iterable[float],
    end_mm: Iterable[float],
    up_hint: Iterable[float] = (0.0, 0.0, 1.0),
) -> tuple[np.ndarray, tuple[float, float, float]]:
    start = as_np(start_mm)
    end = as_np(end_mm)
    x_axis = normalize(end - start)
    up = normalize(as_np(up_hint))
    if abs(float(np.dot(x_axis, up))) > 0.95:
        up = np.array([0.0, 1.0, 0.0], dtype=float)
    y_axis = normalize(np.cross(up, x_axis))
    z_axis = normalize(np.cross(x_axis, y_axis))
    frame = np.column_stack([x_axis, y_axis, z_axis])
    euler = tuple(
        float(value)
        for value in SciPyRotation.from_matrix(frame).as_euler("xyz", degrees=True)
    )
    return frame, euler


def route_bbox(route_points: list[RoutePoint]) -> tuple[np.ndarray, np.ndarray]:
    stacked = np.stack([as_np(point.pos_mm) for point in route_points], axis=0)
    return stacked.min(axis=0), stacked.max(axis=0)


def subdivide_segment(
    start_mm: Iterable[float],
    end_mm: Iterable[float],
    max_segment_mm: float,
    rng: random.Random,
) -> list[SegmentSpan]:
    start = as_np(start_mm)
    end = as_np(end_mm)
    distance = float(np.linalg.norm(end - start))
    split_count = max(1, math.ceil(distance / max_segment_mm))
    fractions = np.linspace(0.0, 1.0, split_count + 1)
    if split_count > 1:
        jitter = min(0.10 / split_count, 0.04)
        for idx in range(1, split_count):
            base = fractions[idx]
            candidate = base + rng.uniform(-jitter, jitter)
            lower = fractions[idx - 1] + 1e-4
            upper = fractions[idx + 1] - 1e-4
            fractions[idx] = min(max(candidate, lower), upper)
        fractions.sort()

    spans: list[SegmentSpan] = []
    for split_index in range(split_count):
        p0 = tuple(float(v) for v in (start + (end - start) * fractions[split_index]))
        p1 = tuple(
            float(v) for v in (start + (end - start) * fractions[split_index + 1])
        )
        spans.append(
            SegmentSpan(
                segment_index=-1,
                split_index=split_index,
                start_mm=p0,
                end_mm=p1,
            )
        )
    return spans


def route_spans(
    route_points: list[RoutePoint], max_segment_mm: float, seed: int
) -> list[SegmentSpan]:
    rng = random.Random(seed)
    spans: list[SegmentSpan] = []
    for segment_index, (start, end) in enumerate(zip(route_points, route_points[1:])):
        for span in subdivide_segment(start.pos_mm, end.pos_mm, max_segment_mm, rng):
            spans.append(
                SegmentSpan(
                    segment_index=segment_index,
                    split_index=len(
                        [s for s in spans if s.segment_index == segment_index]
                    ),
                    start_mm=span.start_mm,
                    end_mm=span.end_mm,
                )
            )
    return spans


def build_tube_scaffold(route_points: list[RoutePoint], radius_mm: float) -> Compound:
    route_points_xyz = [tuple(point.pos_mm) for point in route_points]
    with BuildLine() as route_line:
        Polyline(route_points_xyz)
    with BuildSketch(Plane(origin=route_points_xyz[0])) as route_profile:
        Circle(radius_mm)
    with BuildPart() as tube:
        sweep(route_profile.sketch, path=route_line.line)
    part = tube.part
    part.label = "tube_scaffold"
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    compound = Compound(children=[part])
    compound.label = "tube_scaffold"
    compound.metadata = CompoundMetadata(fixed=True)
    return compound


def build_box_part(spec: PartSpec):
    with BuildPart() as part_builder:
        Box(
            spec.dims_mm[0],
            spec.dims_mm[1],
            spec.dims_mm[2],
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    part = part_builder.part.moved(Location(spec.center_mm, spec.euler_deg))
    part.label = spec.name
    part.metadata = PartMetadata(
        material_id=spec.material_id,
        fixed=spec.fixed,
    )
    return part


def box_part_specs_for_route(
    route_points: list[RoutePoint],
    *,
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    seed: int,
    material_id: str,
) -> list[PartSpec]:
    corridor_width_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
    corridor_height_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
    inner_width_mm = max(corridor_width_mm - 2.0 * wall_thickness_mm, wall_thickness_mm)
    inner_height_mm = max(
        corridor_height_mm - 2.0 * wall_thickness_mm, wall_thickness_mm
    )
    spans = route_spans(route_points, max_segment_mm=max_segment_mm, seed=seed)
    specs: list[PartSpec] = []

    for span in spans:
        start = as_np(span.start_mm)
        end = as_np(span.end_mm)
        frame, euler = frame_from_segment(start, end)
        center = (start + end) * 0.5
        length_mm = float(np.linalg.norm(end - start))

        side_defs = {
            "floor": (
                (length_mm, inner_width_mm, wall_thickness_mm),
                np.array(
                    [0.0, 0.0, -corridor_height_mm / 2.0 + wall_thickness_mm / 2.0]
                ),
            ),
            "roof": (
                (length_mm, inner_width_mm, wall_thickness_mm),
                np.array(
                    [0.0, 0.0, corridor_height_mm / 2.0 - wall_thickness_mm / 2.0]
                ),
            ),
            "left_wall": (
                (length_mm, wall_thickness_mm, inner_height_mm),
                np.array(
                    [0.0, -corridor_width_mm / 2.0 + wall_thickness_mm / 2.0, 0.0]
                ),
            ),
            "right_wall": (
                (length_mm, wall_thickness_mm, inner_height_mm),
                np.array([0.0, corridor_width_mm / 2.0 - wall_thickness_mm / 2.0, 0.0]),
            ),
        }

        for side_name, (dims_mm, offset_local) in side_defs.items():
            offset_world = frame @ offset_local
            world_center = center + offset_world
            name = (
                f"seg_{span.segment_index:02d}_split_{span.split_index:02d}_{side_name}"
            )
            specs.append(
                PartSpec(
                    name=name,
                    segment_index=span.segment_index,
                    split_index=span.split_index,
                    side=side_name,
                    dims_mm=tuple(float(v) for v in dims_mm),
                    center_mm=tuple(float(v) for v in world_center),
                    euler_deg=euler,
                    material_id=material_id,
                )
            )

    return specs


def parts_from_specs(specs: list[PartSpec]) -> list:
    return [build_box_part(spec) for spec in specs]


def compound_from_specs(specs: list[PartSpec], label: str) -> Compound:
    parts = parts_from_specs(specs)
    compound = Compound(children=parts)
    compound.label = label
    compound.metadata = CompoundMetadata(fixed=True)
    return compound


def intersects_any(compound: Compound) -> tuple[bool, tuple[Any, Any], float]:
    if hasattr(compound, "do_children_intersect"):
        return compound.do_children_intersect()
    return False, (None, None), 0.0


def payload_extent_mm(benchmark_definition: BenchmarkDefinition) -> float:
    payload = benchmark_definition.payload
    shape = str(getattr(payload, "shape", "sphere")).strip().lower()
    radius_range = getattr(
        getattr(payload, "static_randomization", None), "radius", None
    )
    radius = float(max(radius_range)) if radius_range else None

    if shape == "sphere":
        return 2.0 * (radius if radius is not None else 1.0)
    if shape in {"cube", "box"}:
        return (2.0 * radius) if radius is not None else 1.0
    if shape == "cylinder":
        return 2.0 * (radius if radius is not None else 1.0)
    return 2.0 * (radius if radius is not None else 1.0)


def scale_benchmark_definition_to_mm(
    benchmark_definition: BenchmarkDefinition,
    *,
    scale: float = 1000.0,
) -> BenchmarkDefinition:
    data = benchmark_definition.model_dump(mode="json")

    def scale_point(point: list[float] | tuple[float, float, float] | None):
        if point is None:
            return None
        return [float(value) * scale for value in point]

    def scale_bbox(box: dict[str, list[float]] | None):
        if not isinstance(box, dict):
            return box
        scaled = dict(box)
        if "min" in scaled:
            scaled["min"] = scale_point(scaled["min"])
        if "max" in scaled:
            scaled["max"] = scale_point(scaled["max"])
        return scaled

    objectives = (
        data.get("objectives") if isinstance(data.get("objectives"), dict) else {}
    )
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    constraints = (
        data.get("constraints") if isinstance(data.get("constraints"), dict) else {}
    )
    simulation_bounds = data.get("simulation_bounds")

    if isinstance(objectives, dict):
        if "goal_zone" in objectives:
            objectives["goal_zone"] = scale_bbox(objectives.get("goal_zone"))
        if "build_zone" in objectives:
            objectives["build_zone"] = scale_bbox(objectives.get("build_zone"))
        if "forbid_zones" in objectives and isinstance(
            objectives["forbid_zones"], list
        ):
            scaled_forbid_zones = []
            for zone in objectives["forbid_zones"]:
                if not isinstance(zone, dict):
                    scaled_forbid_zones.append(zone)
                    continue
                zone_scaled = dict(zone)
                zone_scaled["min"] = scale_point(zone_scaled.get("min"))
                zone_scaled["max"] = scale_point(zone_scaled.get("max"))
                scaled_forbid_zones.append(zone_scaled)
            objectives["forbid_zones"] = scaled_forbid_zones

    if isinstance(payload, dict):
        if payload.get("start_position") is not None:
            payload["start_position"] = scale_point(payload.get("start_position"))
        static_randomization = (
            payload.get("static_randomization")
            if isinstance(payload.get("static_randomization"), dict)
            else {}
        )
        if static_randomization.get("radius") is not None:
            static_randomization["radius"] = [
                float(value) * scale for value in static_randomization["radius"]
            ]
        payload["static_randomization"] = static_randomization
        if payload.get("runtime_jitter") is not None:
            payload["runtime_jitter"] = [
                float(value) * scale for value in payload["runtime_jitter"]
            ]

    if isinstance(simulation_bounds, dict):
        data["simulation_bounds"] = scale_bbox(simulation_bounds)
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
        "min": [float(v) for v in lower.tolist()],
        "max": [float(v) for v in upper.tolist()],
    }


def load_benchmark_definition(bundle_dir: Path) -> BenchmarkDefinition:
    raw = load_yaml(bundle_dir / "benchmark_definition.yaml")
    if not isinstance(raw, dict):
        raise ValueError("benchmark_definition.yaml must deserialize to a mapping")

    objectives = (
        raw.get("objectives") if isinstance(raw.get("objectives"), dict) else {}
    )
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    constraints = (
        raw.get("constraints") if isinstance(raw.get("constraints"), dict) else {}
    )
    randomization = (
        raw.get("randomization") if isinstance(raw.get("randomization"), dict) else {}
    )
    physics = raw.get("physics") if isinstance(raw.get("physics"), dict) else {}

    pruned = {
        "objectives": {
            "goal_zone": objectives.get("goal_zone"),
            "forbid_zones": objectives.get("forbid_zones", []),
            "build_zone": objectives.get("build_zone"),
        },
        "benchmark_parts": raw.get("benchmark_parts", []),
        "physics": {
            "backend": physics.get("backend", SimulatorBackendType.MUJOCO.value),
            "compute_target": physics.get("compute_target", "auto"),
        },
        "simulation_bounds": raw.get("simulation_bounds"),
        "payload": {
            "label": payload.get("label"),
            "shape": payload.get("shape"),
            "material_id": payload.get("material_id"),
            "static_randomization": payload.get("static_randomization", {}),
            "start_position": payload.get("start_position"),
            "runtime_jitter": payload.get("runtime_jitter"),
        },
        "constraints": {
            "estimated_solution_cost_usd": constraints.get(
                "estimated_solution_cost_usd"
            ),
            "estimated_solution_weight_g": constraints.get(
                "estimated_solution_weight_g"
            ),
            "max_unit_cost": constraints.get("max_unit_cost"),
            "max_weight_g": constraints.get("max_weight_g"),
            "target_quantity": constraints.get("target_quantity"),
        },
        "randomization": {
            "static_variation_id": randomization.get("static_variation_id"),
            "runtime_jitter_enabled": randomization.get("runtime_jitter_enabled", True),
        },
        "assembly_totals": raw.get("assembly_totals"),
    }
    return BenchmarkDefinition.model_validate(pruned)


def synthetic_benchmark_definition(
    benchmark_definition: BenchmarkDefinition,
    *,
    route_points: list[RoutePoint],
    envelope_mm: float,
    margin_mm: float,
) -> dict[str, Any]:
    benchmark_data = benchmark_definition.model_dump(mode="json")
    bbox = expanded_bounding_box(
        route_points, envelope_mm=envelope_mm, margin_mm=margin_mm
    )
    benchmark_data["objectives"]["build_zone"] = bbox
    benchmark_data["simulation_bounds"] = bbox
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
    parts: list, config: ScenarioConfig
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


def selected_side_map_literal(part_specs: list[PartSpec]) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for spec in part_specs:
        grouped[f"{spec.segment_index}:{spec.split_index}"].append(spec.side)

    order = {"floor": 0, "roof": 1, "left_wall": 2, "right_wall": 3}
    for key, sides in grouped.items():
        grouped[key] = sorted(
            dict.fromkeys(sides), key=lambda side: order.get(side, 99)
        )
    return json.dumps(dict(sorted(grouped.items())), indent=2)


def build_route_lowering_script_text(
    *,
    scenario_id: str,
    route_points: list[RoutePoint],
    selected_sides: str,
    payload_name: str,
    assembly_label: str,
    split_seed: int,
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    material_id: str,
) -> str:
    route_literal = json.dumps(
        [
            {"name": p.name, "pos_mm": list(p.pos_mm), "t_s": p.t_s}
            for p in route_points
        ],
        indent=2,
    )
    return (
        textwrap.dedent(
            f"""\
        from __future__ import annotations

        import math
        import random

        import numpy as np
        from build123d import Align, Box, BuildPart, Compound, Location
        from scipy.spatial.transform import Rotation as SciPyRotation
        from shared.models.schemas import CompoundMetadata, PartMetadata

        ROUTE_POINTS = {route_literal}
        SELECTED_SIDES_BY_SPAN = {selected_sides}
        SCENARIO_ID = {scenario_id!r}
        PAYLOAD_NAME = {payload_name!r}
        ASSEMBLY_LABEL = {assembly_label!r}
        SPLIT_SEED = {split_seed}
        TUBE_RADIUS_MM = {float(tube_radius_mm):.6f}
        CLEARANCE_MM = {float(clearance_mm):.6f}
        WALL_THICKNESS_MM = {float(wall_thickness_mm):.6f}
        MAX_SEGMENT_MM = {float(max_segment_mm):.6f}
        MATERIAL_ID = {material_id!r}

        def as_np(point):
            return np.asarray(tuple(float(v) for v in point), dtype=float)

        def normalize(vector):
            norm = float(np.linalg.norm(vector))
            if norm <= 0.0:
                raise ValueError("zero-length vector")
            return vector / norm

        def frame_from_segment(start_mm, end_mm, up_hint=(0.0, 0.0, 1.0)):
            start = as_np(start_mm)
            end = as_np(end_mm)
            x_axis = normalize(end - start)
            up = normalize(as_np(up_hint))
            if abs(float(np.dot(x_axis, up))) > 0.95:
                up = np.array([0.0, 1.0, 0.0], dtype=float)
            y_axis = normalize(np.cross(up, x_axis))
            z_axis = normalize(np.cross(x_axis, y_axis))
            frame = np.column_stack([x_axis, y_axis, z_axis])
            euler = tuple(
                float(value)
                for value in SciPyRotation.from_matrix(frame).as_euler("xyz", degrees=True)
            )
            return frame, euler

        def subdivide_segment(start_mm, end_mm, max_segment_mm, rng):
            start = as_np(start_mm)
            end = as_np(end_mm)
            distance = float(np.linalg.norm(end - start))
            split_count = max(1, math.ceil(distance / max_segment_mm))
            fractions = np.linspace(0.0, 1.0, split_count + 1)
            if split_count > 1:
                jitter = min(0.10 / split_count, 0.04)
                for idx in range(1, split_count):
                    base = fractions[idx]
                    candidate = base + rng.uniform(-jitter, jitter)
                    lower = fractions[idx - 1] + 1e-4
                    upper = fractions[idx + 1] - 1e-4
                    fractions[idx] = min(max(candidate, lower), upper)
                fractions.sort()

            spans = []
            for split_index in range(split_count):
                p0 = tuple(float(v) for v in (start + (end - start) * fractions[split_index]))
                p1 = tuple(float(v) for v in (start + (end - start) * fractions[split_index + 1]))
                spans.append(
                    {{
                        "segment_index": -1,
                        "split_index": split_index,
                        "start_mm": p0,
                        "end_mm": p1,
                    }}
                )
            return spans

        def route_spans(route_points, max_segment_mm, seed):
            rng = random.Random(seed)
            spans = []
            for segment_index, (start, end) in enumerate(zip(route_points, route_points[1:])):
                for span in subdivide_segment(start["pos_mm"], end["pos_mm"], max_segment_mm, rng):
                    span["segment_index"] = segment_index
                    span["split_index"] = len(
                        [candidate for candidate in spans if candidate["segment_index"] == segment_index]
                    )
                    spans.append(span)
            return spans

        def build_box_part(spec):
            with BuildPart() as builder:
                Box(
                    spec["dims_mm"][0],
                    spec["dims_mm"][1],
                    spec["dims_mm"][2],
                    align=(Align.CENTER, Align.CENTER, Align.CENTER),
                )
            part = builder.part.moved(Location(tuple(spec["center_mm"]), tuple(spec["euler_deg"])))
            part.label = spec["name"]
            part.metadata = PartMetadata(
                material_id=spec["material_id"],
                fixed=bool(spec.get("fixed", True)),
            )
            return part

        def box_part_specs_for_route(route_points, tube_radius_mm, clearance_mm, wall_thickness_mm, max_segment_mm, seed, material_id):
            corridor_width_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
            corridor_height_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
            inner_width_mm = max(corridor_width_mm - 2.0 * wall_thickness_mm, wall_thickness_mm)
            inner_height_mm = max(corridor_height_mm - 2.0 * wall_thickness_mm, wall_thickness_mm)
            spans = route_spans(route_points, max_segment_mm=max_segment_mm, seed=seed)
            specs = []

            for span in spans:
                start = as_np(span["start_mm"])
                end = as_np(span["end_mm"])
                frame, euler = frame_from_segment(start, end)
                center = (start + end) * 0.5
                length_mm = float(np.linalg.norm(end - start))
                span_key = f"{{span['segment_index']}}:{{span['split_index']}}"
                selected_sides = SELECTED_SIDES_BY_SPAN.get(
                    span_key,
                    [],
                )
                if not selected_sides:
                    continue

                side_defs = {{
                    "floor": (
                        (length_mm, inner_width_mm, wall_thickness_mm),
                        np.array([0.0, 0.0, -corridor_height_mm / 2.0 + wall_thickness_mm / 2.0]),
                    ),
                    "roof": (
                        (length_mm, inner_width_mm, wall_thickness_mm),
                        np.array([0.0, 0.0, corridor_height_mm / 2.0 - wall_thickness_mm / 2.0]),
                    ),
                    "left_wall": (
                        (length_mm, wall_thickness_mm, inner_height_mm),
                        np.array([0.0, -corridor_width_mm / 2.0 + wall_thickness_mm / 2.0, 0.0]),
                    ),
                    "right_wall": (
                        (length_mm, wall_thickness_mm, inner_height_mm),
                        np.array([0.0, corridor_width_mm / 2.0 - wall_thickness_mm / 2.0, 0.0]),
                    ),
                }}

                for side_name in selected_sides:
                    dims_mm, offset_local = side_defs[side_name]
                    offset_world = frame @ offset_local
                    world_center = center + offset_world
                    name = f"seg_{{span['segment_index']:02d}}_split_{{span['split_index']:02d}}_{{side_name}}"
                    specs.append(
                        {{
                            "name": name,
                            "segment_index": span["segment_index"],
                            "split_index": span["split_index"],
                            "side": side_name,
                            "dims_mm": [float(v) for v in dims_mm],
                            "center_mm": [float(v) for v in world_center],
                            "euler_deg": [float(v) for v in euler],
                            "material_id": material_id,
                            "fixed": True,
                        }}
                    )

            return specs

        def build():
            parts = [
                build_box_part(spec)
                for spec in box_part_specs_for_route(
                    ROUTE_POINTS,
                    tube_radius_mm=TUBE_RADIUS_MM,
                    clearance_mm=CLEARANCE_MM,
                    wall_thickness_mm=WALL_THICKNESS_MM,
                    max_segment_mm=MAX_SEGMENT_MM,
                    seed=SPLIT_SEED,
                    material_id=MATERIAL_ID,
                )
            ]
            assembly = Compound(children=parts)
            assembly.label = ASSEMBLY_LABEL
            assembly.metadata = CompoundMetadata(fixed=True)
            return assembly
        """
        )
        .lstrip()
        .replace("\n        ", "\n")
    )


def build_solution_script_text(
    *,
    scenario_id: str,
    route_points: list[RoutePoint],
    part_specs: list[PartSpec],
    payload_name: str,
    split_seed: int,
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    material_id: str,
) -> str:
    return build_route_lowering_script_text(
        scenario_id=scenario_id,
        route_points=route_points,
        selected_sides=selected_side_map_literal(part_specs),
        payload_name=payload_name,
        assembly_label=f"synthetic_route_{scenario_id}",
        split_seed=split_seed,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        material_id=material_id,
    )


def build_evidence_script_text(
    *,
    scenario_id: str,
    route_points: list[RoutePoint],
    part_specs: list[PartSpec],
    payload_name: str,
    split_seed: int,
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    material_id: str,
) -> str:
    return build_route_lowering_script_text(
        scenario_id=scenario_id,
        route_points=route_points,
        selected_sides=selected_side_map_literal(part_specs),
        payload_name=payload_name,
        assembly_label=f"synthetic_route_preview_{scenario_id}",
        split_seed=split_seed,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        material_id=material_id,
    )


def build_engineering_plan_text(
    *,
    scenario_id: str,
    route_points: list[RoutePoint],
    total_cost: float,
    total_weight: float,
    planner_target_cost: float,
    planner_target_weight: float,
) -> str:
    route_names = ", ".join(point.name for point in route_points)
    return textwrap.dedent(
        f"""\
        # Engineering Plan

        ## 1. Solution Overview

        - **Core Mechanism**: A box-decomposed corridor follows the supplied route trace and preserves the wall-contact cloud captured from the scratch tube run.
        - **Key Principle**: Tube geometry exists only as an intermediate scaffold. The published solution is a segmented set of box primitives that keep the same route and contact order.
        - **Robustness Strategy**: Split long spans, keep the parts that actually participate in the collision cloud, and verify the same batched jitter batch after pruning.

        ## 2. Parts List

        | Part | Purpose |
        | -- | -- |
        | corridor floor / walls | route capture and support |
        | segment splits | keep the geometry from becoming one long monolithic bar |

        **Estimated Total Weight**: {total_weight:.2f} g
        **Estimated Total Cost**: ${total_cost:.2f}

        ## 3. Assembly Strategy

        1. Read the benchmark-owned bundle and the manual route trace.
        2. Build the scratch tube scaffold to capture the wall-contact cloud.
        3. Decompose the scaffold into four-sided box primitives along the route.
        4. Prune any box side that did not register collision hits in the cloud.
        5. Export the planner and coder bundles from the resulting layout.

        ## 4. Assumption Register

        - Route points: {route_names}
        - Planner target cost: ${planner_target_cost:.2f}
        - Planner target weight: {planner_target_weight:.2f} g

        ## 5. Risk Assessment

        - Geometry generation is seeded-random: the candidate split layout changes with the retry seed.
        - Pruning is deterministic and depends only on collision hits in the wall-contact cloud.
        - If a candidate fails the jittered acceptance batch, retry with a different split seed before changing the route trace or span-length threshold.
        """
    )


def build_todo_text() -> str:
    return textwrap.dedent(
        """\
        # TODO

        ## Phase 1: Load Inputs

        - [ ] Confirm the benchmark bundle path and manual route trace.
        - [ ] Confirm the build zone envelope derived from the payload geometry.

        ## Phase 2: Generate Scratch Scaffold

        - [ ] Build the tube scaffold from the route points.
        - [ ] Collect the wall-contact cloud from the scratch run.

        ## Phase 3: Decompose and Prune

        - [ ] Split the route into shorter box segments.
        - [ ] Prune unused or near-unused box sides.

        ## Phase 4: Export

        - [ ] Write the planner and coder bundle roots.
        - [ ] Update the role-based dataset rows.
        - [ ] Keep markdown edits in the filesystem, not in the notebook.
        """
    )


def build_solution_description_text(bundle_name: str, files: list[str]) -> str:
    items = "\n".join(f"- `{name}`" for name in files)
    return textwrap.dedent(
        f"""\
        # Solution Description

        This snapshot captures the replaceable solution overlay for `{bundle_name}`.

        Construction notes:
        1. Copy the role-owned workspace files from the seed root into `.solution`.
        2. Omit backend-owned manifests and scratch notebook state.
        3. Use this overlay to materialize or compare the solved workspace state.

        Included root items:
        {items}
        """
    )


def build_journal_text() -> str:
    return textwrap.dedent(
        """\
        # Journal

        - Generated by the synthetic tube-guided corpus notebook.
        - Manual review notes can be appended here after export.
        """
    )


def build_payload_trajectory_template_text() -> str:
    return textwrap.dedent(
        """\
        # Engineer-owned payload trajectory scaffold.
        # Replace this with the backend-specific path proof before submission.
        backend: GENESIS
        payload_part_names: []
        initial_pose:
          reference_point: ""
          pos_mm: [0.0, 0.0, 0.0]
          rot_deg: [0.0, 0.0, 0.0]
        sample_stride_s: 0.1
        anchors: []
        terminal_event: null
        """
    )


def build_markdown_templates() -> dict[str, str]:
    engineering_template = (
        ROOT
        / "shared"
        / "assets"
        / "template_repos"
        / "engineer"
        / "engineering_plan.md"
    ).read_text(encoding="utf-8")
    todo_template = (
        ROOT / "shared" / "assets" / "template_repos" / "engineer" / "todo.md"
    ).read_text(encoding="utf-8")
    return {
        "engineering_plan.md": engineering_template,
        "todo.md": todo_template,
        "solution_description.md": build_solution_description_text(
            "synthetic tube-guided corpus",
            [
                "assembly_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "benchmark_definition.yaml",
                "benchmark_script.py",
                "engineering_plan.md",
                "solution_plan_evidence_script.py",
                "todo.md",
            ],
        ),
        "journal.md": build_journal_text(),
    }


def choose_batch_width(config: ScenarioConfig) -> int:
    lower, upper = config.batch_width_range
    return int(round((lower + upper) / 2.0))


def contact_body_name(contact, payload_body_name: str) -> str | None:
    if contact.body1 == payload_body_name:
        return contact.body2
    if contact.body2 == payload_body_name:
        return contact.body1
    return None


def capture_contact_cloud(
    *,
    scene_path: Path,
    backend_type: SimulatorBackendType,
    benchmark_definition: BenchmarkDefinition,
    duration_s: float,
    seed: int,
) -> list[ContactHit]:
    from worker_heavy.simulation.factory import get_physics_backend

    logger.info(
        "capture_contact_cloud_start",
        scene_path=str(scene_path),
        backend=backend_type.value,
        duration_s=duration_s,
        seed=seed,
    )
    backend = get_physics_backend(backend_type, session_id=f"tube-cloud-{seed}")
    backend.load_scene(SimulationScene(scene_path=str(scene_path)))
    payload_name = payload_scene_name(benchmark_definition.payload.label)
    dt = getattr(backend, "timestep", 0.002)
    steps = max(1, int(duration_s / dt))
    hits: list[ContactHit] = []

    try:
        for _ in range(steps):
            result = backend.step(dt)
            if not result.success:
                break
            current_time = float(result.time)
            for contact in backend.get_contact_forces():
                other = contact_body_name(contact, payload_name)
                if other is None:
                    continue
                if not other.startswith("seg_"):
                    continue
                hits.append(
                    ContactHit(
                        time_s=current_time,
                        position_mm=tuple(float(v) for v in contact.position),
                        payload_body=payload_name,
                        other_body=other,
                        force_n=tuple(float(v) for v in contact.force),
                    )
                )
    finally:
        backend.close()
    logger.info(
        "capture_contact_cloud_done",
        scene_path=str(scene_path),
        backend=backend_type.value,
        hit_count=len(hits),
    )
    return hits


def hits_by_part(contact_hits: list[ContactHit]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for hit in contact_hits:
        counter[hit.other_body] += 1
    return counter


def prune_segment_specs(
    specs: list[PartSpec],
    contact_hits: list[ContactHit],
    *,
    min_hits: int = 1,
) -> list[PartSpec]:
    by_name = hits_by_part(contact_hits)
    grouped: dict[tuple[int, int], list[PartSpec]] = defaultdict(list)
    for spec in specs:
        grouped[(spec.segment_index, spec.split_index)].append(spec)

    kept: list[PartSpec] = []
    for key in sorted(grouped):
        group = grouped[key]
        selected = [spec for spec in group if by_name[spec.name] >= min_hits]
        if not selected:
            logger.info(
                "prune_segment_specs_drop_span",
                segment_index=key[0],
                split_index=key[1],
                part_count=len(group),
            )
            continue

        kept.extend(
            sorted(
                selected,
                key=lambda spec: (spec.segment_index, spec.split_index, spec.side),
            )
        )

    return kept


def build_scene_xml(
    *,
    benchmark_definition: BenchmarkDefinition,
    assembly,
    output_dir: Path,
    backend_type: SimulatorBackendType,
) -> Path:
    from worker_heavy.simulation.factory import get_simulation_builder

    builder = get_simulation_builder(
        output_dir=output_dir,
        backend_type=backend_type,
        use_vhacd=False,
    )
    return builder.build_from_assembly(
        assembly, objectives=benchmark_definition, payload_parts=None
    )


def write_bundle(
    *,
    root_dir: Path,
    benchmark_definition_yaml: dict[str, Any],
    benchmark_assembly_text: str,
    benchmark_script_text: str,
    assembly_definition_yaml: dict[str, Any],
    evidence_script_text: str,
    solution_script_text: str | None = None,
    payload_trajectory_yaml: dict[str, Any] | None = None,
    markdown_files: dict[str, str] | None = None,
    extra_files: dict[str, str] | None = None,
    copy_reviews_from: Path | None = None,
) -> None:
    logger.info("write_bundle_start", root_dir=str(root_dir))
    root_dir.mkdir(parents=True, exist_ok=True)
    solution_dir = root_dir / ".solution"
    solution_dir.mkdir(parents=True, exist_ok=True)

    root_payloads: dict[str, Any] = {
        "benchmark_definition.yaml": benchmark_definition_yaml,
        "benchmark_assembly_definition.yaml": benchmark_assembly_text,
        "benchmark_script.py": benchmark_script_text,
        "assembly_definition.yaml": assembly_definition_yaml,
        "solution_plan_evidence_script.py": evidence_script_text,
    }
    if solution_script_text is not None:
        root_payloads["solution_script.py"] = solution_script_text
    if payload_trajectory_yaml is not None:
        root_payloads["payload_trajectory_definition.yaml"] = payload_trajectory_yaml
    if markdown_files:
        root_payloads.update(markdown_files)
    if extra_files:
        root_payloads.update(extra_files)

    for name, payload in root_payloads.items():
        target = root_dir / name
        if isinstance(payload, str):
            write_text(target, payload)
        else:
            dump_yaml(target, payload)

    for name, payload in root_payloads.items():
        target = solution_dir / name
        if isinstance(payload, str):
            write_text(target, payload)
        else:
            dump_yaml(target, payload)

    if copy_reviews_from and copy_reviews_from.exists():
        copy_tree(copy_reviews_from, root_dir / "reviews")
        copy_tree(copy_reviews_from, solution_dir / "reviews")
    logger.info(
        "write_bundle_done",
        root_dir=str(root_dir),
        file_count=len(root_payloads),
    )


def update_dataset_row(path: Path, row: dict[str, Any]) -> None:
    logger.info("update_dataset_row", path=str(path), row_id=row.get("id"))
    rows = []
    if path.exists():
        rows = json.loads(path.read_text(encoding="utf-8"))
        rows = [existing for existing in rows if existing.get("id") != row["id"]]
    rows.append(row)
    rows.sort(key=lambda item: str(item.get("id", "")))
    write_json(path, rows)


def role_row(
    *,
    row_id: str,
    agent: AgentName,
    bundle_dir: Path,
    scenario_id: str,
    description: str,
) -> dict[str, Any]:
    task = (
        f"Use the seeded artifacts in the workspace to finish the {scenario_id} "
        f"{agent.value} handoff."
    )
    expected = description
    return {
        "id": row_id,
        "task": task,
        "seed_artifact_dir": str(bundle_dir.as_posix()),
        "expected_criteria": expected,
        "complexity_level": 2,
    }


def render_debug_plots(
    *,
    output_dir: Path,
    route_points: list[RoutePoint],
    tube_radius_mm: float,
    contact_hits: list[ContactHit],
    part_specs: list[PartSpec],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    route = np.asarray([point.pos_mm for point in route_points], dtype=float)
    contacts = (
        np.asarray([hit.position_mm for hit in contact_hits], dtype=float)
        if contact_hits
        else np.empty((0, 3))
    )

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(
        route[:, 0],
        route[:, 1],
        route[:, 2],
        color="#214d9c",
        linewidth=2.5,
        label="route",
    )
    if len(contacts):
        ax.scatter(
            contacts[:, 0],
            contacts[:, 1],
            contacts[:, 2],
            color="#c0392b",
            s=16,
            label="wall contacts",
        )
    for spec in part_specs[: min(24, len(part_specs))]:
        cx, cy, cz = spec.center_mm
        ax.scatter([cx], [cy], [cz], color="#2e8b57", s=10, alpha=0.6)
    ax.set_title(f"tube radius {tube_radius_mm:.2f} mm")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(output_dir / "route_contacts_3d.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    axes[0].plot(route[:, 0], route[:, 1], color="#214d9c")
    axes[0].scatter(route[:, 0], route[:, 1], color="#214d9c")
    axes[0].set_title("XY")
    axes[1].plot(route[:, 0], route[:, 2], color="#214d9c")
    axes[1].scatter(route[:, 0], route[:, 2], color="#214d9c")
    axes[1].set_title("XZ")
    axes[2].plot(route[:, 1], route[:, 2], color="#214d9c")
    axes[2].scatter(route[:, 1], route[:, 2], color="#214d9c")
    axes[2].set_title("YZ")
    for axis in axes:
        axis.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "route_projections.png", dpi=180)
    plt.close(fig)


def stage_bundle_root(
    *,
    root: Path,
    benchmark_bundle_dir: Path,
    benchmark_definition_yaml: dict[str, Any],
    benchmark_script_text: str,
    benchmark_assembly_text: str,
    assembly_definition_yaml: dict[str, Any],
    evidence_script_text: str,
    solution_script_text: str | None = None,
    payload_trajectory_yaml: dict[str, Any] | None = None,
    markdown_files: dict[str, str] | None = None,
    copy_reviews_from: Path | None = None,
) -> None:
    logger.info("stage_bundle_root", root=str(root))
    write_bundle(
        root_dir=root,
        benchmark_definition_yaml=benchmark_definition_yaml,
        benchmark_assembly_text=benchmark_assembly_text,
        benchmark_script_text=benchmark_script_text,
        assembly_definition_yaml=assembly_definition_yaml,
        evidence_script_text=evidence_script_text,
        solution_script_text=solution_script_text,
        payload_trajectory_yaml=payload_trajectory_yaml,
        markdown_files=markdown_files,
        copy_reviews_from=copy_reviews_from,
    )


def candidate_layout_summary(
    part_specs: list[PartSpec],
) -> dict[tuple[int, int], list[str]]:
    grouped: dict[tuple[int, int], list[str]] = defaultdict(list)
    for spec in part_specs:
        grouped[(spec.segment_index, spec.split_index)].append(spec.side)
    return grouped


def build_candidate_assembly(
    *,
    route_points: list[RoutePoint],
    tube_radius_mm: float,
    clearance_mm: float,
    wall_thickness_mm: float,
    max_segment_mm: float,
    seed: int,
    material_id: str,
) -> tuple[list[PartSpec], Compound]:
    specs = box_part_specs_for_route(
        route_points,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=clearance_mm,
        wall_thickness_mm=wall_thickness_mm,
        max_segment_mm=max_segment_mm,
        seed=seed,
        material_id=material_id,
    )
    parts = parts_from_specs(specs)
    compound = Compound(children=parts)
    compound.label = "synthetic_route_candidate"
    compound.metadata = CompoundMetadata(fixed=True)
    return specs, compound


def validate_geometry(compound: Compound) -> None:
    intersects, pair, volume = intersects_any(compound)
    if intersects and volume > 1e-8:
        a, b = pair
        label_a = str(getattr(a, "label", "") or "")
        label_b = str(getattr(b, "label", "") or "")
        match_a = re.search(r"seg_(\d+)_split_(\d+)_", label_a)
        match_b = re.search(r"seg_(\d+)_split_(\d+)_", label_b)
        if match_a and match_b:
            seg_a = int(match_a.group(1))
            seg_b = int(match_b.group(1))
            split_a = int(match_a.group(2))
            split_b = int(match_b.group(2))
            if (
                seg_a != seg_b
                and abs(seg_a - seg_b) <= 1
                and split_a == 0
                and split_b == 0
            ):
                return
        raise ValueError(
            f"Candidate geometry self-intersects between {label_a} and {label_b} "
            f"(volume={volume})"
        )


def synthesize(
    config: ScenarioConfig,
) -> dict[str, Any]:
    from worker_heavy.simulation.verification import verify_with_jitter

    logger.info(
        "synthesize_start",
        scenario_id=config.scenario_id,
        benchmark_bundle_dir=str(config.benchmark_bundle_dir),
        planner_row_id=config.planner_row_id,
        coder_row_id=config.coder_row_id,
    )
    benchmark_definition = scale_benchmark_definition_to_mm(
        load_benchmark_definition(config.benchmark_bundle_dir)
    )
    benchmark_build = load_benchmark_build_fn(config.benchmark_bundle_dir)
    benchmark_geometry = benchmark_build()
    payload_extent = payload_extent_mm(benchmark_definition)
    tube_radius_mm = (payload_extent / 2.0) + config.clearance_mm
    corridor_inner_extent_mm = payload_extent + 2.0 * config.clearance_mm
    build_zone_margin_mm = (
        max(tube_radius_mm, config.wall_thickness_mm) + config.route_margin_mm
    )
    logger.info(
        "synthesize_geometry_ready",
        payload_extent_mm=payload_extent,
        tube_radius_mm=tube_radius_mm,
        corridor_inner_extent_mm=corridor_inner_extent_mm,
        build_zone_margin_mm=build_zone_margin_mm,
    )

    synthetic_benchmark_dict = synthetic_benchmark_definition(
        benchmark_definition,
        route_points=config.route_points,
        envelope_mm=corridor_inner_extent_mm,
        margin_mm=build_zone_margin_mm,
    )
    synthetic_benchmark = BenchmarkDefinition.model_validate(synthetic_benchmark_dict)

    benchmark_script_text = (
        config.benchmark_bundle_dir / "benchmark_script.py"
    ).read_text(encoding="utf-8")
    benchmark_assembly_text = (
        config.benchmark_bundle_dir / "benchmark_assembly_definition.yaml"
    ).read_text(encoding="utf-8")
    benchmark_bundle_reviews = config.benchmark_bundle_dir / "reviews"
    scratch_root = config.scratch_root / config.scenario_id
    scratch_root.mkdir(parents=True, exist_ok=True)

    payload_body_name = payload_scene_name(benchmark_definition.payload.label)
    chosen_backend: SimulatorBackendType | None = None
    chosen_batch_width = None
    chosen_seed = None
    chosen_contact_hits: list[ContactHit] = []
    chosen_specs: list[PartSpec] | None = None
    chosen_pruned_specs: list[PartSpec] | None = None
    chosen_scene_path: Path | None = None
    chosen_verify_result = None
    chosen_pruned_result = None

    for retry_seed in progress_iter(config.retry_seeds, "retry seeds"):
        try:
            batch_width = choose_batch_width(config)
            logger.info("retry_start", retry_seed=retry_seed, batch_width=batch_width)
            candidate_specs, candidate_compound = build_candidate_assembly(
                route_points=config.route_points,
                tube_radius_mm=tube_radius_mm,
                clearance_mm=config.clearance_mm,
                wall_thickness_mm=config.wall_thickness_mm,
                max_segment_mm=config.max_segment_mm,
                seed=retry_seed,
                material_id=config.material_id,
            )
            validate_geometry(candidate_compound)

            candidate_scratch = scratch_root / f"retry-{retry_seed}"
            candidate_scratch.mkdir(parents=True, exist_ok=True)
            logger.info(
                "candidate_scene_build_start",
                retry_seed=retry_seed,
                output_dir=str(candidate_scratch),
            )
            scene_path = build_scene_xml(
                benchmark_definition=synthetic_benchmark,
                assembly=Compound(children=[benchmark_geometry, candidate_compound]),
                output_dir=candidate_scratch,
                backend_type=config.backend_order[0],
            )

            for backend_type in progress_iter(
                config.backend_order, f"backend {retry_seed}"
            ):
                try:
                    logger.info(
                        "verification_start",
                        retry_seed=retry_seed,
                        backend=backend_type.value,
                        batch_width=batch_width,
                    )
                    verify_result = verify_with_jitter(
                        xml_path=str(scene_path),
                        control_inputs={},
                        jitter_range=tuple(
                            float(v)
                            for v in benchmark_definition.payload.runtime_jitter
                        ),
                        num_scenes=batch_width,
                        duration=8.0,
                        seed=retry_seed,
                        backend_type=backend_type,
                        explicit_target_body_name=payload_body_name,
                    )
                    if verify_result.success_rate < config.success_threshold:
                        logger.info(
                            "verification_failed",
                            retry_seed=retry_seed,
                            backend=backend_type.value,
                            success_rate=float(verify_result.success_rate),
                            threshold=config.success_threshold,
                        )
                        continue

                    contact_hits = capture_contact_cloud(
                        scene_path=scene_path,
                        backend_type=backend_type,
                        benchmark_definition=benchmark_definition,
                        duration_s=8.0,
                        seed=retry_seed,
                    )
                    if not contact_hits:
                        logger.info(
                            "contact_cloud_empty",
                            retry_seed=retry_seed,
                            backend=backend_type.value,
                        )
                        continue

                    pruned_specs = prune_segment_specs(
                        candidate_specs, contact_hits, min_hits=1
                    )
                    pruned_compound = compound_from_specs(
                        pruned_specs, label="synthetic_route_solution"
                    )
                    validate_geometry(pruned_compound)

                    pruned_scene_path = build_scene_xml(
                        benchmark_definition=synthetic_benchmark,
                        assembly=Compound(
                            children=[benchmark_geometry, pruned_compound]
                        ),
                        output_dir=candidate_scratch / "pruned",
                        backend_type=backend_type,
                    )

                    pruned_result = verify_with_jitter(
                        xml_path=str(pruned_scene_path),
                        control_inputs={},
                        jitter_range=tuple(
                            float(v)
                            for v in benchmark_definition.payload.runtime_jitter
                        ),
                        num_scenes=batch_width,
                        duration=8.0,
                        seed=retry_seed,
                        backend_type=backend_type,
                        explicit_target_body_name=payload_body_name,
                    )
                    if pruned_result.success_rate < config.success_threshold:
                        logger.info(
                            "pruned_verification_failed",
                            retry_seed=retry_seed,
                            backend=backend_type.value,
                            success_rate=float(pruned_result.success_rate),
                            threshold=config.success_threshold,
                        )
                        continue

                    chosen_backend = backend_type
                    chosen_batch_width = batch_width
                    chosen_seed = retry_seed
                    chosen_contact_hits = contact_hits
                    chosen_specs = candidate_specs
                    chosen_pruned_specs = pruned_specs
                    chosen_scene_path = pruned_scene_path
                    chosen_verify_result = verify_result
                    chosen_pruned_result = pruned_result
                    logger.info(
                        "candidate_accepted",
                        retry_seed=retry_seed,
                        backend=backend_type.value,
                        batch_width=batch_width,
                        success_rate_tube=float(verify_result.success_rate),
                        success_rate_pruned=float(pruned_result.success_rate),
                        pruned_part_count=len(pruned_specs),
                    )
                    break
                except Exception:
                    logger.exception(
                        "backend_attempt_failed",
                        retry_seed=retry_seed,
                        backend=backend_type.value,
                    )
                    continue

            if chosen_backend is not None:
                break
        except Exception:
            logger.exception("retry_configuration_failed", retry_seed=retry_seed)
            continue

    if chosen_backend is None or chosen_pruned_specs is None or chosen_specs is None:
        logger.error(
            "no_retry_configuration_survived",
            scenario_id=config.scenario_id,
            retries=list(config.retry_seeds),
        )
        raise RuntimeError(
            "No retry configuration survived the tube and pruned batches"
        )

    pruned_parts = parts_from_specs(chosen_pruned_specs)
    pruned_compound = Compound(children=pruned_parts)
    pruned_compound.label = "synthetic_route_solution"
    pruned_compound.metadata = CompoundMetadata(fixed=True)
    validate_geometry(pruned_compound)

    manufactured_part_entries, total_cost, total_weight = annotate_manufactured_parts(
        pruned_parts, config
    )
    planner_constraints = make_planner_constraints(
        benchmark_definition, total_cost=total_cost, total_weight=total_weight
    )
    assembly_definition = {
        "version": "1.0",
        "units": {"length": "mm", "volume": "mm3", "mass": "g", "currency": "USD"},
        "constraints": planner_constraints,
        "manufactured_parts": manufactured_part_entries,
        "coarse_payload_trajectory": coarse_payload_trajectory_dict(
            payload_name=benchmark_definition.payload.label,
            route_points=config.route_points,
            first_contacts=[hit.other_body for hit in chosen_contact_hits[:6]],
            terminal_reference_point=config.route_points[-1].name,
            sample_stride_s=0.25,
        ),
        "final_assembly": [
            {"name": spec.name, "config": None} for spec in chosen_pruned_specs
        ],
        "totals": {
            "estimated_unit_cost_usd": total_cost,
            "estimated_weight_g": total_weight,
            "estimate_confidence": "high",
        },
        "dfm_suggestions": [],
    }
    AssemblyDefinition.model_validate(assembly_definition)

    payload_trajectory_yaml = payload_trajectory_dict(
        payload_name=benchmark_definition.payload.label,
        route_points=config.route_points,
        first_contacts=[hit.other_body for hit in chosen_contact_hits[:6]],
        terminal_reference_point=config.route_points[-1].name,
        backend=chosen_backend,
        sample_stride_s=0.1,
    )

    # Validate the fine trajectory contract before writing it.
    from shared.models.schemas import PayloadTrajectoryDefinition

    PayloadTrajectoryDefinition.model_validate(payload_trajectory_yaml)

    markdown_files = build_markdown_templates()
    planner_plan = build_engineering_plan_text(
        scenario_id=config.scenario_id,
        route_points=config.route_points,
        total_cost=total_cost,
        total_weight=total_weight,
        planner_target_cost=planner_constraints["planner_target_max_unit_cost_usd"],
        planner_target_weight=planner_constraints["planner_target_max_weight_g"],
    )

    # Preserve the template repo's plan/todo content as the starting point.
    markdown_files["engineering_plan.md"] = planner_plan
    markdown_files["todo.md"] = build_todo_text()

    planner_evidence_text = build_evidence_script_text(
        scenario_id=config.scenario_id,
        route_points=config.route_points,
        part_specs=chosen_pruned_specs,
        payload_name=benchmark_definition.payload.label,
        split_seed=chosen_seed,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=config.clearance_mm,
        wall_thickness_mm=config.wall_thickness_mm,
        max_segment_mm=config.max_segment_mm,
        material_id=config.material_id,
    )
    solution_script_text = build_solution_script_text(
        scenario_id=config.scenario_id,
        route_points=config.route_points,
        part_specs=chosen_pruned_specs,
        payload_name=benchmark_definition.payload.label,
        split_seed=chosen_seed,
        tube_radius_mm=tube_radius_mm,
        clearance_mm=config.clearance_mm,
        wall_thickness_mm=config.wall_thickness_mm,
        max_segment_mm=config.max_segment_mm,
        material_id=config.material_id,
    )

    planner_root = config.staged_planner_root
    coder_root = config.staged_coder_root
    copy_reviews_from = (
        benchmark_bundle_reviews if benchmark_bundle_reviews.exists() else None
    )

    stage_bundle_root(
        root=planner_root,
        benchmark_bundle_dir=config.benchmark_bundle_dir,
        benchmark_definition_yaml=synthetic_benchmark_dict,
        benchmark_script_text=benchmark_script_text,
        benchmark_assembly_text=benchmark_assembly_text,
        assembly_definition_yaml=assembly_definition,
        evidence_script_text=planner_evidence_text,
        markdown_files={
            "engineering_plan.md": markdown_files["engineering_plan.md"],
            "todo.md": markdown_files["todo.md"],
            "solution_description.md": markdown_files["solution_description.md"],
        },
        copy_reviews_from=copy_reviews_from,
    )

    stage_bundle_root(
        root=coder_root,
        benchmark_bundle_dir=config.benchmark_bundle_dir,
        benchmark_definition_yaml=synthetic_benchmark_dict,
        benchmark_script_text=benchmark_script_text,
        benchmark_assembly_text=benchmark_assembly_text,
        assembly_definition_yaml=assembly_definition,
        evidence_script_text=planner_evidence_text,
        solution_script_text=solution_script_text,
        payload_trajectory_yaml=payload_trajectory_yaml,
        markdown_files={
            "engineering_plan.md": markdown_files["engineering_plan.md"],
            "todo.md": markdown_files["todo.md"],
            "solution_description.md": markdown_files["solution_description.md"],
            "journal.md": markdown_files["journal.md"],
        },
        copy_reviews_from=copy_reviews_from,
    )

    if config.emit_debug_plots:
        logger.info(
            "render_debug_plots_start", output_dir=str(coder_root / "renders" / "debug")
        )
        render_debug_plots(
            output_dir=coder_root / "renders" / "debug",
            route_points=config.route_points,
            tube_radius_mm=tube_radius_mm,
            contact_hits=chosen_contact_hits,
            part_specs=chosen_pruned_specs,
        )

    if config.promote_to_dataset:
        logger.info("promote_to_dataset_start")
        dataset_root = ROOT / "dataset" / "data" / "seed" / "artifacts"
        final_planner_root = dataset_root / "engineer_planner" / config.planner_row_id
        final_coder_root = dataset_root / "engineer_coder" / config.coder_row_id
        if final_planner_root.exists():
            shutil.rmtree(final_planner_root)
        if final_coder_root.exists():
            shutil.rmtree(final_coder_root)
        shutil.copytree(planner_root, final_planner_root)
        shutil.copytree(coder_root, final_coder_root)

        planner_row_path = (
            ROOT / "dataset" / "data" / "seed" / "role_based" / "engineer_planner.json"
        )
        coder_row_path = (
            ROOT / "dataset" / "data" / "seed" / "role_based" / "engineer_coder.json"
        )
        planner_row = role_row(
            row_id=config.planner_row_id,
            agent=AgentName.ENGINEER_PLANNER,
            bundle_dir=Path("dataset/data/seed/artifacts/engineer_planner")
            / config.planner_row_id,
            scenario_id=config.scenario_id,
            description="Populate the planner bundle by editing the filesystem overlay and preserving the box-decomposed corridor contract.",
        )
        coder_row = role_row(
            row_id=config.coder_row_id,
            agent=AgentName.ENGINEER_CODER,
            bundle_dir=Path("dataset/data/seed/artifacts/engineer_coder")
            / config.coder_row_id,
            scenario_id=config.scenario_id,
            description="Populate the coder bundle by editing the filesystem overlay and preserving the generated payload-trajectory proof.",
        )
        update_dataset_row(planner_row_path, planner_row)
        update_dataset_row(coder_row_path, coder_row)
        logger.info(
            "promote_to_dataset_done",
            planner_row_id=config.planner_row_id,
            coder_row_id=config.coder_row_id,
        )

    logger.info(
        "synthesize_done",
        scenario_id=config.scenario_id,
        backend=chosen_backend.value,
        retry_seed=chosen_seed,
        success_rate_tube=float(chosen_verify_result.success_rate),
        success_rate_pruned=float(chosen_pruned_result.success_rate),
    )
    return {
        "scenario_id": config.scenario_id,
        "backend": chosen_backend.value,
        "batch_width": chosen_batch_width,
        "retry_seed": chosen_seed,
        "scene_path": str(chosen_scene_path) if chosen_scene_path else None,
        "planner_root": str(planner_root),
        "coder_root": str(coder_root),
        "total_cost": total_cost,
        "total_weight": total_weight,
        "success_rate_tube": float(chosen_verify_result.success_rate),
        "success_rate_pruned": float(chosen_pruned_result.success_rate),
        "pruned_part_count": len(chosen_pruned_specs),
    }


def default_route_points() -> list[RoutePoint]:
    return [
        RoutePoint(name="build_zone_start", pos_mm=(-250.0, 0.0, 140.0), t_s=0.0),
        RoutePoint(name="waypoint_01", pos_mm=(-220.0, 0.0, 132.0), t_s=0.8),
        RoutePoint(name="waypoint_02", pos_mm=(-220.0, 95.0, 120.0), t_s=1.6),
        RoutePoint(name="waypoint_03", pos_mm=(-60.0, 95.0, 98.0), t_s=2.7),
        RoutePoint(name="waypoint_04", pos_mm=(180.0, 95.0, 72.0), t_s=4.0),
        RoutePoint(name="goal_zone_contact", pos_mm=(300.0, 0.0, 40.0), t_s=5.5),
    ]


def main(config: ScenarioConfig | None = None) -> dict[str, Any]:
    if config is None:
        config = ScenarioConfig(
            scenario_id="tube-guided-synthetic-001",
            benchmark_bundle_dir=ROOT
            / "dataset"
            / "data"
            / "seed"
            / "artifacts"
            / "benchmark_coder"
            / "bc-002-tunnel",
            planner_row_id="ep-synth-001",
            coder_row_id="ec-synth-001",
            route_points=default_route_points(),
            scratch_root=ROOT / "tmp" / "tube_guided_synthetic_corpus",
            promote_to_dataset=False,
        )
    log_path = notebook_log_path(config.scenario_id)
    with NotebookLogCapture(log_path):
        logger.info("notebook_log_capture_start", log_path=str(log_path))
        summary = synthesize(config)
        logger.info("notebook_log_capture_done", log_path=str(log_path))
        return summary


if __name__ == "__main__":
    try:
        summary = main()
        print(json.dumps(summary, indent=2))
    except Exception:
        logger.exception("tube_guided_synthetic_corpus_main_failed")
        raise
