from pathlib import Path
from typing import Any

import structlog
import yaml
from build123d import Compound, Part

from shared.models.schemas import (
    AssemblyDefinition,
    BenchmarkDefinition,
    BoundingBox,
)
from shared.workers.workbench_models import (
    CostBreakdown,
    ManufacturingConfig,
    ManufacturingMethod,
    MaterialDefinition,
    WorkbenchMetadata,
    WorkbenchResult,
)
from worker_heavy.workbenches.cnc import analyze_cnc
from worker_heavy.workbenches.config import load_required_merged_config
from worker_heavy.workbenches.injection_molding import analyze_im
from worker_heavy.workbenches.print_3d import analyze_3dp

logger = structlog.get_logger()


def load_planner_manufacturing_config(
    config_path: str | Path | None = None,
    override_data: dict[str, Any] | None = None,
) -> ManufacturingConfig:
    """Load the planner's merged manufacturing config with fail-closed semantics."""
    return load_required_merged_config(
        config_path=config_path,
        override_data=override_data,
        source_name="manufacturing_config.yaml",
    )


def load_planner_manufacturing_config_from_text(
    config_text: str,
    *,
    source_name: str = "manufacturing_config.yaml",
) -> ManufacturingConfig:
    """Load the planner manufacturing config from raw YAML text."""
    try:
        override_data = yaml.safe_load(config_text)
    except Exception as exc:
        raise ValueError(f"{source_name} invalid: {exc}") from exc

    if override_data is None:
        raise ValueError(f"{source_name} is empty")
    if not isinstance(override_data, dict):
        raise ValueError(f"{source_name} must deserialize to a mapping")

    return load_planner_manufacturing_config(override_data=override_data)


def resolve_requested_quantity(
    quantity: int | None = None,
    benchmark_definition: BenchmarkDefinition | None = None,
    *,
    require_benchmark_quantity: bool = False,
) -> int:
    """Resolve the production quantity from explicit or benchmark-scoped input."""
    benchmark_quantity = (
        benchmark_definition.constraints.target_quantity
        if benchmark_definition is not None and benchmark_definition.constraints
        else None
    )

    if quantity is not None:
        if quantity < 1:
            raise ValueError("quantity must be >= 1")
        if benchmark_quantity is not None and quantity != benchmark_quantity:
            raise ValueError(
                "quantity conflict: explicit quantity "
                f"{quantity} does not match benchmark_definition.constraints.target_quantity "
                f"{benchmark_quantity}"
            )
        return quantity

    if benchmark_quantity is not None:
        return benchmark_quantity

    if require_benchmark_quantity:
        raise ValueError(
            "benchmark_definition.constraints.target_quantity is missing; "
            "cannot resolve requested production quantity"
        )

    return 1


def _part_reports_for_analysis(part: Part | Compound) -> list[Part | Compound]:
    children = getattr(part, "children", [])
    if not children:
        return [part]
    return [
        child
        for child in children
        if not getattr(child, "label", "").startswith("zone_")
    ]


def _is_within_bounds(
    part: Part | Compound, build_zone: BoundingBox
) -> tuple[bool, str]:
    """
    Check if a part's bounding box is fully within the build zone.

    Returns:
        (True, "") if within bounds
        (False, error_message) if out of bounds
    """
    bbox = part.bounding_box()

    # Check each dimension
    violations = []
    if build_zone.min[0] > bbox.min.X:
        violations.append(
            f"X min ({bbox.min.X:.2f}) < build zone min ({build_zone.min[0]:.2f})"
        )
    if build_zone.min[1] > bbox.min.Y:
        violations.append(
            f"Y min ({bbox.min.Y:.2f}) < build zone min ({build_zone.min[1]:.2f})"
        )
    if build_zone.min[2] > bbox.min.Z:
        violations.append(
            f"Z min ({bbox.min.Z:.2f}) < build zone min ({build_zone.min[2]:.2f})"
        )
    if build_zone.max[0] < bbox.max.X:
        violations.append(
            f"X max ({bbox.max.X:.2f}) > build zone max ({build_zone.max[0]:.2f})"
        )
    if build_zone.max[1] < bbox.max.Y:
        violations.append(
            f"Y max ({bbox.max.Y:.2f}) > build zone max ({build_zone.max[1]:.2f})"
        )
    if build_zone.max[2] < bbox.max.Z:
        violations.append(
            f"Z max ({bbox.max.Z:.2f}) > build zone max ({build_zone.max[2]:.2f})"
        )

    if violations:
        return False, "; ".join(violations)
    return True, ""


def _count_dofs(part: Part | Compound) -> int:
    """
    Count degrees of freedom in a compound assembly.

    Per architecture spec: Warn if DOF >= 4 as it's unusual in engineering.
    This is a simplified heuristic based on child count of compounds.

    Returns:
        Estimated DOF count based on assembly structure
    """
    if isinstance(part, Part):
        # Single parts typically have 0 internal DOFs
        return 0

    # For compounds, each child that could move independently adds DOFs
    # A simple heuristic: count children that are not zones or fixed
    dof_count = 0
    for child in part.children:
        label = getattr(child, "label", "")
        # Skip zones (they don't contribute to mechanical DOF)
        if label.startswith("zone_"):
            continue
        # Check if part is marked as fixed
        if getattr(child, "fixed", False):
            continue
        # Each free part could add up to 6 DOFs (3 translation + 3 rotation)
        # But we count conservatively as 1 DOF per movable part
        dof_count += 1

    return dof_count


def _metadata_is_fixed(metadata: Any) -> bool:
    if metadata is None:
        return False
    value = getattr(metadata, "is_fixed", None)
    if value is not None:
        return bool(value)
    if isinstance(metadata, dict):
        return bool(metadata.get("is_fixed", metadata.get("fixed", False)))
    return False


def _metadata_cots_id(metadata: Any) -> str | None:
    if metadata is None:
        return None
    value = getattr(metadata, "cots_id", None)
    if value:
        return str(value)
    if isinstance(metadata, dict):
        raw = metadata.get("cots_id")
        if raw:
            return str(raw)
    return None


def _part_label(part: Part | Compound) -> str:
    return getattr(part, "label", None) or "unnamed_part"


def _prefix_part_violation(label: str, violation: str) -> str:
    prefix = f"{label}: "
    return violation if violation.startswith(prefix) else f"{prefix}{violation}"


def _resolve_cots_catalog_item(part_id: str):
    from shared.cots.runtime import get_catalog_item_with_metadata

    return get_catalog_item_with_metadata(part_id)


def _build_cots_workbench_result(
    part: Part | Compound,
    *,
    quantity: int,
    build_zone: BoundingBox | None,
    session_id: str | None,
) -> WorkbenchResult:
    label = _part_label(part)
    metadata = getattr(part, "metadata", None)
    cots_id = _metadata_cots_id(metadata)
    if not cots_id:
        raise ValueError(f"{label}: COTS validation requested without cots_id")

    lookup = _resolve_cots_catalog_item(cots_id)
    if lookup is None:
        raise ValueError(f"{label}: unresolved COTS part_id '{cots_id}'")

    catalog_item, catalog_metadata = lookup
    catalog_details = catalog_item.metadata or {}
    if build_zone is not None:
        is_valid, error_msg = _is_within_bounds(part, build_zone)
        if not is_valid:
            breakdown = CostBreakdown(
                process="cots",
                total_cost=catalog_item.unit_cost * quantity,
                unit_cost=catalog_item.unit_cost,
                material_cost_per_unit=catalog_item.unit_cost,
                setup_cost=0.0,
                variable_cost_per_unit=catalog_item.unit_cost,
                quantity=quantity,
                is_reused=quantity > 1,
                details={
                    "part_id": cots_id,
                    "manufacturer": catalog_details.get("manufacturer", "unknown"),
                    "source": "catalog",
                    "catalog_version": catalog_metadata.get("catalog_version"),
                    "bd_warehouse_commit": catalog_metadata.get("bd_warehouse_commit"),
                    "catalog_snapshot_id": catalog_metadata.get("catalog_snapshot_id"),
                    "generated_at": catalog_metadata.get("generated_at"),
                },
                pricing_explanation="Exact COTS catalog lookup",
            )
            return WorkbenchResult(
                is_manufacturable=False,
                unit_cost=catalog_item.unit_cost,
                weight_g=catalog_item.weight_g,
                violations=[
                    _prefix_part_violation(
                        label, f"COTS build zone violation: {error_msg}"
                    )
                ],
                metadata=WorkbenchMetadata(
                    cost_breakdown=breakdown,
                    additional_info={
                        "cots_part_id": cots_id,
                        "manufacturer": catalog_item.metadata.get(
                            "manufacturer", "unknown"
                        ),
                        "source": "catalog",
                        "catalog_version": catalog_metadata.get("catalog_version"),
                        "bd_warehouse_commit": catalog_metadata.get(
                            "bd_warehouse_commit"
                        ),
                        "catalog_snapshot_id": catalog_metadata.get(
                            "catalog_snapshot_id"
                        ),
                        "generated_at": catalog_metadata.get("generated_at"),
                        "quantity": quantity,
                        "requested_quantity": quantity,
                    },
                ),
            )

    breakdown = {
        "cots_part_id": cots_id,
        "manufacturer": catalog_details.get("manufacturer", "unknown"),
        "source": "catalog",
        "catalog_version": catalog_metadata.get("catalog_version"),
        "bd_warehouse_commit": catalog_metadata.get("bd_warehouse_commit"),
        "catalog_snapshot_id": catalog_metadata.get("catalog_snapshot_id"),
        "generated_at": catalog_metadata.get("generated_at"),
        "quantity": quantity,
        "requested_quantity": quantity,
    }
    cost_breakdown = CostBreakdown(
        process="cots",
        total_cost=catalog_item.unit_cost * quantity,
        unit_cost=catalog_item.unit_cost,
        material_cost_per_unit=catalog_item.unit_cost,
        setup_cost=0.0,
        variable_cost_per_unit=catalog_item.unit_cost,
        quantity=quantity,
        is_reused=quantity > 1,
        details={
            "part_id": cots_id,
            "manufacturer": catalog_details.get("manufacturer", "unknown"),
            "source": "catalog",
            "catalog_version": catalog_metadata.get("catalog_version"),
            "bd_warehouse_commit": catalog_metadata.get("bd_warehouse_commit"),
            "catalog_snapshot_id": catalog_metadata.get("catalog_snapshot_id"),
            "generated_at": catalog_metadata.get("generated_at"),
        },
        pricing_explanation="Exact COTS catalog lookup",
    )
    return WorkbenchResult(
        is_manufacturable=True,
        unit_cost=catalog_item.unit_cost,
        weight_g=catalog_item.weight_g,
        violations=[],
        metadata=WorkbenchMetadata(
            cost_breakdown=cost_breakdown,
            additional_info=breakdown,
        ),
    )


def calculate_benchmark_drilling_cost(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> float:
    """Return static benchmark drilling cost from declared environment operations."""
    unit_cost = config.benchmark_operations.drilling.cost_per_hole_usd
    total_holes = sum(
        operation.quantity
        for operation in assembly_definition.environment_drill_operations
    )
    return round(total_holes * unit_cost, 2)


def calculate_declared_assembly_cost(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> float:
    """Return deterministic planner-declared assembly cost minimum."""
    manufactured_cost = sum(
        part.estimated_unit_cost_usd * part.quantity
        for part in assembly_definition.manufactured_parts
    )
    cots_cost = sum(
        part.unit_cost_usd * part.quantity for part in assembly_definition.cots_parts
    )
    drilling_cost = calculate_benchmark_drilling_cost(assembly_definition, config)
    return round(manufactured_cost + cots_cost + drilling_cost, 2)


def _resolve_declared_material(
    *,
    material_id: str,
    manufacturing_method: ManufacturingMethod,
    config: ManufacturingConfig,
) -> MaterialDefinition:
    material_name = material_id.strip()
    if not material_name:
        raise ValueError("manufactured_parts material_id must be a non-empty string")

    method_config = None
    if manufacturing_method == ManufacturingMethod.CNC:
        method_config = config.cnc
    elif manufacturing_method == ManufacturingMethod.INJECTION_MOLDING:
        method_config = config.injection_molding
    elif manufacturing_method == ManufacturingMethod.THREE_DP:
        method_config = config.three_dp

    material_cfg = None
    if method_config is not None:
        material_cfg = method_config.materials.get(material_name)
    if material_cfg is None:
        material_cfg = config.materials.get(material_name)
    if material_cfg is None:
        raise ValueError(
            f"Unknown material_id '{material_name}' for {manufacturing_method.value} weight calculation"
        )
    return material_cfg


def calculate_declared_assembly_weight(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> float:
    """Return deterministic planner-declared assembly weight."""
    manufactured_weight = 0.0
    for part in assembly_definition.manufactured_parts:
        material_cfg = _resolve_declared_material(
            material_id=part.material_id,
            manufacturing_method=part.manufacturing_method,
            config=config,
        )
        part_weight = (part.part_volume_mm3 / 1000.0) * material_cfg.density_g_cm3
        manufactured_weight += part_weight * part.quantity

    cots_weight = 0.0
    for part in assembly_definition.cots_parts:
        cots_weight += part.weight_g * part.quantity

    return round(manufactured_weight + cots_weight, 2)


def validate_declared_assembly_cost(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> list[str]:
    """Ensure planner totals include all declared part, COTS, and drilling costs."""
    minimum_cost = calculate_declared_assembly_cost(assembly_definition, config)
    if assembly_definition.totals.estimated_unit_cost_usd + 1e-6 < minimum_cost:
        return [
            "assembly_definition.totals.estimated_unit_cost_usd "
            f"(${assembly_definition.totals.estimated_unit_cost_usd:.2f}) "
            "must include declared manufactured-part costs, COTS costs, and "
            f"benchmark drilling cost (minimum ${minimum_cost:.2f})"
        ]
    return []


def validate_exact_declared_assembly_cost(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> list[str]:
    """Ensure planner totals exactly match the deterministic declared cost."""
    expected_cost = calculate_declared_assembly_cost(assembly_definition, config)
    actual_cost = round(assembly_definition.totals.estimated_unit_cost_usd, 2)
    if actual_cost != expected_cost:
        return [
            "assembly_definition.totals.estimated_unit_cost_usd "
            f"(${actual_cost:.2f}) must equal the deterministic declared cost "
            f"(${expected_cost:.2f})"
        ]
    return []


def validate_declared_assembly_weight(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> list[str]:
    """Ensure planner totals include all declared manufactured and COTS weights."""
    minimum_weight = calculate_declared_assembly_weight(assembly_definition, config)
    if assembly_definition.totals.estimated_weight_g + 1e-6 < minimum_weight:
        return [
            "assembly_definition.totals.estimated_weight_g "
            f"({assembly_definition.totals.estimated_weight_g:.2f}g) "
            "must include declared manufactured-part weights and COTS weights "
            f"(minimum {minimum_weight:.2f}g)"
        ]
    return []


def validate_exact_declared_assembly_weight(
    assembly_definition: AssemblyDefinition,
    config: ManufacturingConfig,
) -> list[str]:
    """Ensure planner totals exactly match the deterministic declared weight."""
    expected_weight = calculate_declared_assembly_weight(assembly_definition, config)
    actual_weight = round(assembly_definition.totals.estimated_weight_g, 2)
    if actual_weight != expected_weight:
        return [
            "assembly_definition.totals.estimated_weight_g "
            f"({actual_weight:.2f}g) must equal the deterministic declared weight "
            f"({expected_weight:.2f}g)"
        ]
    return []


def validate_and_price(
    part: Part | Compound,
    method: ManufacturingMethod,
    config: ManufacturingConfig,
    build_zone: BoundingBox | None = None,
    quantity: int = 1,
    session_id: str | None = None,
) -> WorkbenchResult:
    """
    Unified entry point for DFM (Design for Manufacturing) validation and pricing.
    Dispatches to the appropriate workbench analysis function.

    Args:
        part: The build123d Part or Compound to validate
        method: Manufacturing method (CNC, 3DP, IM)
        config: Manufacturing configuration
        build_zone: Optional build zone bounds to validate against
        quantity: Number of units
    Returns:
        WorkbenchResult with manufacturability, cost, and violations
    """
    logger.info("starting_dfm_facade_analysis", method=method)
    metadata = getattr(part, "metadata", None)
    label = _part_label(part)

    cots_id = _metadata_cots_id(metadata)
    if cots_id:
        return _build_cots_workbench_result(
            part,
            quantity=quantity,
            build_zone=build_zone,
            session_id=session_id,
        )

    if _metadata_is_fixed(metadata):
        return WorkbenchResult(
            is_manufacturable=True,
            unit_cost=0.0,
            weight_g=0.0,
            violations=[],
            metadata=WorkbenchMetadata(
                additional_info={
                    "quantity": quantity,
                    "requested_quantity": quantity,
                    "batch_total_cost_usd": 0.0,
                    "skipped_fixed_context": True,
                }
            ),
        )

    # First, check build zone if provided
    build_zone_violations: list[str] = []
    if build_zone is not None:
        is_valid, error_msg = _is_within_bounds(part, build_zone)
        if not is_valid:
            build_zone_violations = [
                _prefix_part_violation(label, f"Build zone violation: {error_msg}")
            ]
            logger.warning("build_zone_violations", violations=build_zone_violations)

    # Check for excessive DOFs (per architecture spec Item 8)
    dof_count = _count_dofs(part)
    dof_warning = (
        f"Compound has {dof_count} DOFs - unusual in engineering"
        if dof_count >= 4
        else None
    )
    if dof_warning is not None:
        logger.warning(
            "dof_warning",
            dof_count=dof_count,
            message=dof_warning,
        )

    # Dispatch to appropriate workbench
    if method == ManufacturingMethod.CNC:
        result = analyze_cnc(part, config, quantity=quantity)
    elif method == ManufacturingMethod.INJECTION_MOLDING:
        result = analyze_im(part, config, quantity=quantity)
    elif method == ManufacturingMethod.THREE_DP:
        result = analyze_3dp(part, config, quantity=quantity)
    else:
        logger.error(
            "unsupported_manufacturing_method", method=method, session_id=session_id
        )
        raise ValueError(f"Unsupported manufacturing method: {method}")

    # Add DOF warning to metadata (for reviewer notification)

    additional_info = dict(result.metadata.additional_info or {})
    additional_info.update(
        {
            "quantity": quantity,
            "requested_quantity": quantity,
            "batch_total_cost_usd": (
                result.metadata.cost_breakdown.total_cost
                if result.metadata.cost_breakdown is not None
                else result.unit_cost * quantity
            ),
        }
    )
    result_metadata = result.metadata.model_copy(
        update={
            "dof_count": dof_count,
            "dof_warning": dof_warning,
            "additional_info": additional_info,
        }
    )

    # Combine all violations
    all_violations = [
        _prefix_part_violation(label, violation)
        for violation in (list(result.violations) + build_zone_violations)
    ]
    is_manufacturable = result.is_manufacturable and not build_zone_violations

    return WorkbenchResult(
        is_manufacturable=is_manufacturable,
        unit_cost=result.unit_cost,
        weight_g=result.weight_g,
        violations=all_violations,
        metadata=result_metadata,
    )


def validate_and_price_assembly(
    part: Part | Compound,
    config: ManufacturingConfig,
    assembly_definition: AssemblyDefinition | None = None,
    part_labels: set[str] | None = None,
    build_zone: BoundingBox | None = None,
    quantity: int = 1,
    session_id: str | None = None,
    default_method: ManufacturingMethod = ManufacturingMethod.CNC,
) -> WorkbenchResult:
    """
    Validate compound assemblies per child instead of as one fused stock block.

    Benchmark/environment compounds usually represent separate manufactured parts.
    Treating the whole assembly as one CNC stock body creates false undercut and
    corner violations across disconnected children.
    """
    if assembly_definition is not None:
        from worker_heavy.utils.file_validation import (
            _assembly_script_expected_identity_pairs,
            _assembly_script_expected_tokens,
            validate_component_inventory_exactness,
        )

        inventory_errors = validate_component_inventory_exactness(
            component=part,
            expected_tokens=_assembly_script_expected_tokens(assembly_definition),
            artifact_name=_part_label(part),
            expected_identity_pairs=_assembly_script_expected_identity_pairs(
                assembly_definition
            ),
        )
        if inventory_errors:
            return WorkbenchResult(
                is_manufacturable=False,
                unit_cost=0.0,
                weight_g=0.0,
                violations=inventory_errors,
                metadata=WorkbenchMetadata(
                    additional_info={
                        "part_reports": [],
                        "part_count": 0,
                        "quantity": quantity,
                        "requested_quantity": quantity,
                    }
                ),
            )

    reports = _part_reports_for_analysis(part)
    if part_labels is not None:
        reports = [
            child
            for child in reports
            if (getattr(child, "label", None) or "") in part_labels
        ]
    if not reports:
        return WorkbenchResult(
            is_manufacturable=True,
            unit_cost=0.0,
            weight_g=0.0,
            violations=[],
            metadata=WorkbenchMetadata(
                additional_info={
                    "part_reports": [],
                    "part_count": 0,
                    "quantity": quantity,
                    "requested_quantity": quantity,
                }
            ),
        )
    if len(reports) == 1 and reports[0] is part:
        metadata = getattr(part, "metadata", None)
        method = getattr(metadata, "manufacturing_method", None) or default_method
        if isinstance(method, str):
            method = ManufacturingMethod(method)
        result = validate_and_price(
            part,
            method,
            config,
            build_zone=build_zone,
            quantity=quantity,
            session_id=session_id,
        )
        if assembly_definition is None:
            result_metadata = result.metadata.model_copy(
                update={
                    "additional_info": {
                        **dict(result.metadata.additional_info or {}),
                        "quantity": quantity,
                        "requested_quantity": quantity,
                        "batch_total_cost_usd": (
                            result.metadata.cost_breakdown.total_cost
                            if result.metadata.cost_breakdown is not None
                            else result.unit_cost * quantity
                        ),
                    }
                }
            )
            return result.model_copy(update={"metadata": result_metadata})

        drilling_cost = calculate_benchmark_drilling_cost(assembly_definition, config)
        result_metadata = result.metadata.model_copy(
            update={
                "additional_info": {
                    **dict(result.metadata.additional_info or {}),
                    "quantity": quantity,
                    "requested_quantity": quantity,
                    "batch_total_cost_usd": (
                        result.metadata.cost_breakdown.total_cost
                        if result.metadata.cost_breakdown is not None
                        else result.unit_cost * quantity
                    ),
                }
            }
        )
        return WorkbenchResult(
            is_manufacturable=result.is_manufacturable,
            unit_cost=result.unit_cost + drilling_cost,
            weight_g=result.weight_g,
            violations=list(result.violations),
            metadata=result_metadata,
        )

    total_cost = 0.0
    total_weight = 0.0
    violations: list[str] = []
    per_part: list[dict[str, object]] = []
    overall_ok = True

    for child in reports:
        label = getattr(child, "label", None) or "unnamed_part"
        metadata = getattr(child, "metadata", None)
        cots_id = _metadata_cots_id(metadata)
        if cots_id:
            child_result = validate_and_price(
                child,
                default_method,
                config,
                build_zone=build_zone,
                quantity=quantity,
                session_id=session_id,
            )
            total_cost += child_result.unit_cost
            total_weight += child_result.weight_g
            overall_ok = overall_ok and child_result.is_manufacturable
            per_part.append(
                {
                    "label": label,
                    "method": "COTS",
                    "is_manufacturable": child_result.is_manufacturable,
                    "unit_cost": child_result.unit_cost,
                    "weight_g": child_result.weight_g,
                }
            )
            violations.extend(
                _prefix_part_violation(label, violation)
                for violation in child_result.violations
            )
            continue

        if _metadata_is_fixed(metadata):
            per_part.append(
                {
                    "label": label,
                    "method": "fixed",
                    "is_manufacturable": True,
                    "unit_cost": 0.0,
                    "weight_g": 0.0,
                    "skipped": True,
                }
            )
            continue

        method = getattr(metadata, "manufacturing_method", None) or default_method
        if isinstance(method, str):
            method = ManufacturingMethod(method)

        child_result = validate_and_price(
            child,
            method,
            config,
            build_zone=build_zone,
            quantity=quantity,
            session_id=session_id,
        )
        total_cost += child_result.unit_cost
        total_weight += child_result.weight_g
        overall_ok = overall_ok and child_result.is_manufacturable
        per_part.append(
            {
                "label": label,
                "method": "COTS" if cots_id else method.value,
                "is_manufacturable": child_result.is_manufacturable,
                "unit_cost": child_result.unit_cost,
                "weight_g": child_result.weight_g,
            }
        )
        violations.extend(
            _prefix_part_violation(label, violation)
            for violation in child_result.violations
        )

    benchmark_drilling_cost = (
        calculate_benchmark_drilling_cost(assembly_definition, config)
        if assembly_definition is not None
        else 0.0
    )
    total_cost += benchmark_drilling_cost

    return WorkbenchResult(
        is_manufacturable=overall_ok,
        unit_cost=total_cost,
        weight_g=total_weight,
        violations=violations,
        metadata=WorkbenchMetadata(
            additional_info={
                "part_reports": per_part,
                "part_count": len(reports),
                "benchmark_drilling_cost_usd": benchmark_drilling_cost,
                "quantity": quantity,
                "requested_quantity": quantity,
                "batch_total_cost_usd": total_cost * quantity,
                "batch_total_weight_g": total_weight * quantity,
            }
        ),
    )
