import structlog
from build123d import Compound, Part, Solid

from shared.workers.workbench_models import (
    CostBreakdown,
    ManufacturingConfig,
    MaterialDefinition,
    WorkbenchContext,
    WorkbenchResult,
)
from worker_heavy.workbenches.analysis_utils import (
    check_undercuts,
    compute_part_hash,
    part_to_trimesh,
)
from worker_heavy.workbenches.base import Workbench

logger = structlog.get_logger()


def _resolve_cnc_material(
    part: Part | Compound | Solid, config: ManufacturingConfig
) -> tuple[str, MaterialDefinition]:
    metadata = getattr(part, "metadata", None)
    material_name = getattr(metadata, "material_id", None)
    if not material_name:
        material_name = config.defaults.get("material")
    material_name = str(material_name).strip() if material_name is not None else ""
    if not material_name:
        raise ValueError(
            "CNC costing requires part.metadata.material_id or config.defaults.material"
        )

    cnc_cfg = config.cnc
    material_cfg = (
        cnc_cfg.materials.get(material_name) if cnc_cfg else None
    ) or config.materials.get(material_name)
    if not material_cfg:
        raise ValueError(f"Unknown material_id '{material_name}' for CNC costing")

    return material_name, material_cfg


def check_internal_corner_radii(
    part: Part | Compound | Solid, min_radius: float = 1.0
) -> list[str]:
    """
    Checks for internal corners that have a radius smaller than the minimum tool radius.
    In 3-axis CNC, sharp internal vertical corners are impossible to machine.
    """
    violations = []
    logger.debug("checking_internal_corner_radii", min_radius=min_radius)

    # Identify all edges
    all_edges = part.edges()

    # Pre-compute edge to faces map
    edge_to_faces = {}
    for face in part.faces():
        for edge in face.edges():
            if edge not in edge_to_faces:
                edge_to_faces[edge] = []
            edge_to_faces[edge].append(face)

    for edge in all_edges:
        # 1. Identify vertical edges (parallel to Z axis)
        try:
            # Get tangent at midpoint
            tangent = edge.tangent_at(edge.param_at(0.5))
            # Check if it's vertical (|Z| close to 1.0)
            if abs(abs(tangent.Z) - 1.0) > 1e-3:
                continue
        except:
            continue

        # 2. Check for sharp corners (LINE) or small fillets (CIRCLE)
        geom_str = str(edge.geom_type)
        is_sharp = "LINE" in geom_str
        is_small_fillet = "CIRCLE" in geom_str and edge.radius < min_radius

        if is_sharp or is_small_fillet:
            # Find adjacent faces to determine if it's an internal (concave) corner
            adj_faces = edge_to_faces.get(edge, [])

            if len(adj_faces) == 2:
                f1, f2 = adj_faces[0], adj_faces[1]
                p = edge.center()

                try:
                    # Check for tangency - if faces are tangent, it's not a sharp corner
                    n1 = f1.normal_at(p)
                    n2 = f2.normal_at(p)
                    if n1.dot(n2) > 0.99:  # Nearly tangent
                        continue

                    # Get points on each face by moving slightly from the edge toward the face center
                    p1 = p + (f1.center() - p).normalized() * 0.1
                    p2 = p + (f2.center() - p).normalized() * 0.1

                    mid = (p1 + p2) * 0.5

                    # If the midpoint is OUTSIDE the solid, it's a concave (internal) corner.
                    if not part.is_inside(mid):
                        if is_sharp:
                            violations.append(
                                f"Sharp internal vertical corner detected at {p}"
                            )
                        else:
                            violations.append(
                                f"Internal corner radius too small at {p}: {edge.radius:.2f}mm < {min_radius}mm"
                            )
                except:
                    continue

    return list(set(violations))


def calculate_cnc_cost(
    part: Part | Compound | Solid,
    config: ManufacturingConfig,
    quantity: int = 1,
    context: WorkbenchContext | None = None,
) -> CostBreakdown:
    """
    Calculates CNC cost: Setup + (Material + Run) * Quantity.
    """
    cnc_cfg = config.cnc
    if not cnc_cfg:
        raise ValueError("CNC configuration missing")

    material_name, material_cfg = _resolve_cnc_material(part, config)
    mrr = cnc_cfg.constraints.mrr_mm3_per_min

    logger.info("calculating_cnc_cost", material=material_name, quantity=quantity)

    # 0. Stock / Material Analysis
    bbox = part.bounding_box()
    stock_dims = (bbox.size.X, bbox.size.Y, bbox.size.Z)
    stock_volume_cm3 = (stock_dims[0] * stock_dims[1] * stock_dims[2]) / 1000.0
    part_volume_cm3 = part.volume / 1000.0
    removed_volume_cm3 = max(0, stock_volume_cm3 - part_volume_cm3)

    # 1. Material Cost
    density = material_cfg.density_g_cm3
    cost_per_kg = material_cfg.cost_per_kg
    stock_mass_kg = (stock_volume_cm3 * density) / 1000.0
    material_cost_per_part = stock_mass_kg * cost_per_kg

    # 2. Run Cost
    # Machining time driven by removed volume + finishing
    roughing_time_min = (removed_volume_cm3 * 1000.0) / mrr

    params = cnc_cfg.parameters
    finishing_feed_rate = params.finishing_feed_rate_mm_min
    finishing_stepover = params.finishing_stepover_mm

    surface_area_mm2 = part.area
    finishing_time_min = surface_area_mm2 / (finishing_feed_rate * finishing_stepover)

    machining_time_min = roughing_time_min + finishing_time_min
    hourly_rate = material_cfg.machine_hourly_rate
    run_cost_per_part = (machining_time_min / 60.0) * hourly_rate

    # 3. Setup Cost
    setup_cost = cnc_cfg.costs.setup_fee

    # Apply reuse discount if part hash is in context
    is_reused = False
    if context is not None:
        part_hash = compute_part_hash(part)
        if part_hash in context.part_counts:
            setup_cost *= 0.5
            is_reused = True
        context.part_counts[part_hash] = (
            context.part_counts.get(part_hash, 0) + quantity
        )

    total_cost = setup_cost + (material_cost_per_part + run_cost_per_part) * quantity

    return CostBreakdown(
        process="cnc_milling",
        total_cost=total_cost,
        unit_cost=total_cost / quantity if quantity > 0 else 0.0,
        material_cost_per_unit=round(material_cost_per_part, 2),
        setup_cost=round(setup_cost, 2),
        variable_cost_per_unit=round(material_cost_per_part + run_cost_per_part, 2),
        quantity=quantity,
        is_reused=is_reused,
        details={
            "stock_dims_mm": [round(d, 2) for d in stock_dims],
            "stock_volume_cm3": round(stock_volume_cm3, 2),
            "part_volume_cm3": round(part_volume_cm3, 2),
            "removed_volume_cm3": round(removed_volume_cm3, 2),
            "machining_time_min": round(machining_time_min, 2),
            "run_cost_per_unit": round(run_cost_per_part, 2),
            "variable_cost_per_unit": round(
                material_cost_per_part + run_cost_per_part, 2
            ),
            "quantity": quantity,
        },
        pricing_explanation=(
            f"CNC cost (${total_cost:.2f}) for {quantity} units. "
            f"Material: {material_name} (${material_cost_per_part:.2f}/unit). "
            f"Machining time: {machining_time_min:.2f} min. "
            f"Setup fee: ${setup_cost:.2f}."
        ),
    )


def analyze_cnc(
    part: Part | Compound | Solid, config: ManufacturingConfig, quantity: int = 1
) -> WorkbenchResult:
    """
    Functional entry point for CNC analysis.
    """
    logger.info("starting_cnc_analysis")

    violations = []

    # 1. Undercut Check
    mesh = part_to_trimesh(part)
    undercuts = check_undercuts(mesh, (0, 0, 1))
    if undercuts:
        msg = f"CNC Machining Violation: {len(undercuts)} undercut faces detected."
        logger.warning("cnc_undercuts_detected", count=len(undercuts))
        violations.append(msg)

    # 2. Internal Corner Check
    min_radius = config.cnc.constraints.min_tool_radius_mm if config.cnc else 1.0
    corner_violations = check_internal_corner_radii(part, min_radius)
    violations.extend(corner_violations)

    # 3. Cost Calculation
    cost_breakdown = calculate_cnc_cost(part, config, quantity=quantity)

    # 4. Weight Calculation
    material_name, material_cfg = _resolve_cnc_material(part, config)
    density = material_cfg.density_g_cm3

    weight_g = (part.volume / 1000.0) * density

    is_manufacturable = len(violations) == 0

    logger.info(
        "cnc_analysis_complete",
        is_manufacturable=is_manufacturable,
        violations=len(violations),
    )

    from shared.workers.workbench_models import WorkbenchMetadata

    return WorkbenchResult(
        is_manufacturable=is_manufacturable,
        unit_cost=cost_breakdown.unit_cost,
        weight_g=weight_g,
        violations=violations,
        metadata=WorkbenchMetadata(
            cost_breakdown=cost_breakdown,
            undercut_count=len(undercuts),
            additional_info={
                "quantity": quantity,
                "requested_quantity": quantity,
            },
        ),
    )


class CNCWorkbench(Workbench):
    """
    CNC Milling Workbench for 3-axis machining (Workbench Class wrapper).
    """

    def __init__(self, config: ManufacturingConfig | None = None):
        from worker_heavy.workbenches.config import load_config

        self.config = config or load_config()

    def validate(self, part: Part) -> list[Exception | str]:
        result = analyze_cnc(part, self.config)
        return result.violations

    def calculate_cost(
        self,
        part: Part,
        quantity: int = 1,
        context: WorkbenchContext | None = None,
    ) -> CostBreakdown:
        return calculate_cnc_cost(part, self.config, quantity, context)
