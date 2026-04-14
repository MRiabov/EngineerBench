from typing import Any

from pydantic import BaseModel, Field

from shared.enums import ManufacturingMethod


class WorkbenchContext(BaseModel):
    """Context for tracking part reuse and other state during assembly analysis."""

    part_counts: dict[str, int] = Field(default_factory=dict)
    additional_data: dict[str, Any] = Field(default_factory=dict)


class BuildZone(BaseModel):
    """Defines the spatial bounds within which a design must fit."""

    min: tuple[float, float, float]  # (x, y, z) minimum coordinates
    max: tuple[float, float, float]  # (x, y, z) maximum coordinates


class CostBreakdown(BaseModel):
    process: str
    total_cost: float
    unit_cost: float
    material_cost_per_unit: float
    setup_cost: float
    variable_cost_per_unit: float = 0.0
    quantity: int = 1
    is_reused: bool
    details: dict[str, Any] = Field(default_factory=dict)
    pricing_explanation: str = ""


class WorkbenchMetadata(BaseModel):
    """Standardized metadata for workbench results."""

    cost_breakdown: CostBreakdown | None = None
    undercut_count: int | None = None
    gate_count: int | None = None
    additional_info: dict[str, Any] = Field(default_factory=dict)


class WorkbenchResult(BaseModel):
    is_manufacturable: bool
    unit_cost: float
    weight_g: float = 0.0
    violations: list[str] = Field(default_factory=list)
    metadata: WorkbenchMetadata = Field(default_factory=WorkbenchMetadata)


class DFMReport(BaseModel):
    overall_status: bool
    results: dict[str, WorkbenchResult]


class MaterialDefinition(BaseModel):
    name: str
    density_g_cm3: float
    density_kg_m3: float | None = None
    cost_per_kg: float
    color: str = "#FFFFFF"
    restitution: float = 0.5
    friction_coef: float = 0.61  # Default for aluminum
    machine_hourly_rate: float = 0.0
    compatibility: list[ManufacturingMethod] = Field(default_factory=list)


class WireDefinition(BaseModel):
    cost_per_m: float


class CNCConstraints(BaseModel):
    min_tool_radius_mm: float = 1.0
    mrr_mm3_per_min: float = 1000.0


class CNCParameters(BaseModel):
    finishing_feed_rate_mm_min: float = 500.0
    finishing_stepover_mm: float = 0.5


class CNCCosts(BaseModel):
    setup_fee: float = 80.0


class CNCMethodConfig(BaseModel):
    materials: dict[str, MaterialDefinition]
    constraints: CNCConstraints = Field(default_factory=CNCConstraints)
    parameters: CNCParameters = Field(default_factory=CNCParameters)
    costs: CNCCosts = Field(default_factory=CNCCosts)


class IMConstraints(BaseModel):
    min_draft_angle_deg: float = 2.0
    min_wall_thickness_mm: float = 1.0
    max_wall_thickness_mm: float = 4.0


class IMCosts(BaseModel):
    base_mold_cost: float = 5000.0
    mold_cost_per_surface_area_cm2: float = 0.5
    injection_rate_cm3_s: float = 10.0


class IMMethodConfig(BaseModel):
    materials: dict[str, MaterialDefinition]
    constraints: IMConstraints = Field(default_factory=IMConstraints)
    costs: IMCosts = Field(default_factory=IMCosts)


class ThreeDPParameters(BaseModel):
    deposition_rate_cm3_hr: float = 15.0


class ThreeDPCosts(BaseModel):
    setup_fee: float = 10.0


class ThreeDPMethodConfig(BaseModel):
    materials: dict[str, MaterialDefinition]
    parameters: ThreeDPParameters = Field(default_factory=ThreeDPParameters)
    costs: ThreeDPCosts = Field(default_factory=ThreeDPCosts)


class ManufacturingConfig(BaseModel):
    defaults: dict[str, Any] = Field(default_factory=dict)
    materials: dict[str, MaterialDefinition] = Field(default_factory=dict)
    wires: dict[str, WireDefinition] = Field(default_factory=dict)
    cnc: CNCMethodConfig | None = None
    injection_molding: IMMethodConfig | None = None
    three_dp: ThreeDPMethodConfig | None = None

    def __getitem__(self, key: str) -> Any:
        # Support dict-like access for backward compatibility with existing workbenches
        if key == "cnc":
            return self.cnc.model_dump() if self.cnc else {}
        if key == "injection_molding":
            return self.injection_molding.model_dump() if self.injection_molding else {}
        if key == "three_dp":
            return self.three_dp.model_dump() if self.three_dp else {}
        if key == "defaults":
            return self.defaults
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default
