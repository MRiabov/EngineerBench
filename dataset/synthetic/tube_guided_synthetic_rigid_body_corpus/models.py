from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.enums import ManufacturingMethod
from shared.simulation.schemas import SimulatorBackendType


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
    is_fixed: bool = True


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
    source_seed_bundle_dir: Path
    planner_row_id: str
    coder_row_id: str
    route_points: list[RoutePoint]
    scratch_root: Path
    promote_to_dataset: bool = False
    backfill_source_solution: bool = False
    emit_debug_plots: bool = True
    emit_simulation_video: bool = True
    simulation_video_retry_seed: int | None = 11
    simulation_video_duration_s: float = 8.0
    batch_width_range: tuple[int, int] = (10, 20)
    success_threshold: float = 0.8
    backend_order: tuple[SimulatorBackendType, ...] = (SimulatorBackendType.MUJOCO,)
    retry_seeds: tuple[int, ...] = (11, 19, 29)
    clearance_mm: float = 2.0
    wall_thickness_mm: float = 2.0
    max_segment_mm: float = 32.0
    route_margin_mm: float = 8.0
    material_id: str = "aluminum_6061"
    markdown_mode: str = "template"

    @property
    def staged_planner_root(self) -> Path:
        return self.scratch_root / "engineer_planner" / self.planner_row_id

    @property
    def staged_coder_root(self) -> Path:
        return self.scratch_root / "engineer_coder" / self.coder_row_id
