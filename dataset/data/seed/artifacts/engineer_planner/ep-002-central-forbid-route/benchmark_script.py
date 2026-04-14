from __future__ import annotations

import yaml
from build123d import Align, Box, Compound, Cylinder, Location, Sphere

from utils.metadata import CompoundMetadata, PartMetadata


def _load_moved_object() -> dict:
    """Load moved_object contract from planner handoff."""
    with open("benchmark_definition.yaml", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    moved = payload.get("moved_object", {})
    return moved if isinstance(moved, dict) else {}


def _build_moved_object(moved: dict):
    label = str(moved.get("label", "")).strip()
    if not label:
        raise ValueError("moved_object.label must be a non-empty string")
    start = moved.get("start_position", [0.0, 0.0, 0.0])
    radius_range = moved.get("static_randomization", {}).get("radius", [0.01, 0.01])
    radius = float(max(radius_range)) if radius_range else 0.01
    shape = str(moved.get("shape", "sphere")).strip().lower()
    material_id = str(moved.get("material_id", "abs")).strip()
    if not material_id:
        raise ValueError("moved_object.material_id must be a non-empty string")

    if shape == "sphere":
        moved_part = Sphere(radius, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    elif shape in {"cube", "box"}:
        edge = radius * 2.0
        moved_part = Box(
            edge, edge, edge, align=(Align.CENTER, Align.CENTER, Align.CENTER)
        )
    elif shape == "cylinder":
        moved_part = Cylinder(
            radius=radius,
            height=radius * 2.0,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    else:
        raise ValueError(
            f"Unsupported moved_object.shape '{shape}'. Expected sphere, cube, box, or cylinder."
        )

    moved_part = moved_part.move(
        Location((float(start[0]), float(start[1]), float(start[2])))
    )
    moved_part.label = label
    moved_part.metadata = PartMetadata(material_id=material_id, fixed=False)
    return moved_part


_moved_object_contract = _load_moved_object()
_moved_object = _build_moved_object(_moved_object_contract)


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    # Add authored benchmark fixtures to this children list.
    # Every top-level child you add here must have a unique label, and that label
    # must not be `environment`, start with `zone_`, or start with
    # `benchmark_moved_object__` because the simulator reserves those names for the
    # scene root and generated objective bodies.
    environment = Compound(children=[_moved_object])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
