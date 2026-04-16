"""Static and visual randomization utilities for simulation benchmarks.

Implements material randomization per architecture spec:
- Randomly switch materials for moving parts
- Apply material colors to parts for visual diversity
"""

import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class MaterialAssignment(BaseModel):
    """Material assignment for a part."""

    part_name: str
    material_id: str
    color: str  # Hex color from material config
    density_g_cm3: float
    friction_coef: float
    restitution: float


class RandomizationConfig(BaseModel):
    """Configuration for static randomization."""

    seed: int
    material_whitelist: list[str] | None = None  # Allowed materials


def get_eligible_materials(
    materials: dict[str, Any],
    whitelist: list[str] | None = None,
) -> list[str]:
    """Filter materials based on constraints.

    Args:
        materials: Materials config dict from manufacturing_config.yaml.
        whitelist: If provided, only these materials are considered.

    Returns:
        List of eligible material IDs.
    """
    eligible = []

    for mat_id in materials:
        # Check whitelist
        if whitelist and mat_id not in whitelist:
            continue

        eligible.append(mat_id)

    return eligible


def randomize_materials(
    payload_parts: list[str],
    materials: dict[str, Any],
    seed: int,
    whitelist: list[str] | None = None,
) -> dict[str, MaterialAssignment]:
    """Assign random materials to payload parts.

    Args:
        payload_parts: List of part names that have degrees of freedom.
        materials: Materials config dict from manufacturing_config.yaml.
        seed: Random seed for reproducibility.
        whitelist: If provided, only these materials are considered.

    Returns:
        Mapping of part_name -> MaterialAssignment.
    """
    rng = random.Random(seed)

    eligible = get_eligible_materials(materials, whitelist=whitelist)

    if not eligible:
        raise ValueError("No eligible materials found with given constraints")

    assignments: dict[str, MaterialAssignment] = {}

    for part_name in payload_parts:
        mat_id = rng.choice(eligible)
        props = materials[mat_id]

        assignments[part_name] = MaterialAssignment(
            part_name=part_name,
            material_id=mat_id,
            color=props.get("color", "#FFFFFF"),
            density_g_cm3=props.get("density_g_cm3", 1.0),
            friction_coef=props.get("friction_coef", 0.5),
            restitution=props.get("restitution", 0.5),
        )

    return assignments


def apply_material_to_mjcf_geom(
    material_assignment: MaterialAssignment,
) -> dict[str, str]:
    """Generate MJCF geom attributes for a material assignment.

    Args:
        material_assignment: The material assignment to apply.

    Returns:
        Dict of MJCF geom attributes (rgba, friction, etc.).
    """
    # Convert hex color to RGBA
    color = material_assignment.color.lstrip("#")
    r = int(color[0:2], 16) / 255
    g = int(color[2:4], 16) / 255
    b = int(color[4:6], 16) / 255

    return {
        "rgba": f"{r:.3f} {g:.3f} {b:.3f} 1",
        "friction": f"{material_assignment.friction_coef} 0.005 0.0001",
        "density": str(
            material_assignment.density_g_cm3 * 1000
        ),  # Convert g/cm3 to kg/m3
    }


def apply_randomization_to_xml(
    xml_path: str | Path,
    assignments: dict[str, MaterialAssignment],
    output_path: str | Path | None = None,
) -> Path:
    """Applies material assignments to an MJCF XML file.

    Args:
        xml_path: Path to input XML.
        assignments: Map of body name -> MaterialAssignment.
        output_path: Path to save modified XML. If None, overwrites input.

    Returns:
        Path to the modified XML.
    """
    import xml.etree.ElementTree as ET

    xml_p = Path(xml_path)
    tree = ET.parse(xml_p)
    root = tree.getroot()
    worldbody = root.find("worldbody")
    if worldbody is None:
        raise ValueError("Invalid MJCF: no worldbody found")

    for body in worldbody.findall("body"):
        name = body.get("name")
        if name in assignments:
            assignment = assignments[name]
            attribs = apply_material_to_mjcf_geom(assignment)

            # Apply to all geoms in this body
            # Note: This overrides existing attributes
            geoms = body.findall("geom")
            if not geoms:
                # If no geoms (e.g. dummy body), nothing to do
                continue

            for geom in geoms:
                for k, v in attribs.items():
                    geom.set(k, v)

    out = Path(output_path) if output_path else xml_p
    tree.write(out, encoding="utf-8")
    return out
