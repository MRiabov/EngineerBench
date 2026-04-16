from __future__ import annotations

import yaml
from build123d import Align, Box, Compound, Cylinder, Location, Sphere

from utils.metadata import CompoundMetadata, PartMetadata


def _load_payload() -> dict:
    """Load payload contract from planner handoff."""
    with open("benchmark_definition.yaml", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    payload_spec = payload.get("payload", {})
    return payload_spec if isinstance(payload_spec, dict) else {}


def _build_payload(payload_spec: dict):
    label = str(payload_spec.get("label", "")).strip()
    if not label:
        raise ValueError("payload.label must be a non-empty string")
    start = payload_spec.get("start_position", [0.0, 0.0, 0.0])
    radius_range = payload_spec.get("static_randomization", {}).get(
        "radius", [0.01, 0.01]
    )
    radius = float(max(radius_range)) if radius_range else 0.01
    shape = str(payload_spec.get("shape", "sphere")).strip().lower()
    material_id = str(payload_spec.get("material_id", "abs")).strip()
    if not material_id:
        raise ValueError("payload.material_id must be a non-empty string")

    if shape == "sphere":
        payload_part = Sphere(radius, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    elif shape in {"cube", "box"}:
        edge = radius * 2.0
        payload_part = Box(
            edge, edge, edge, align=(Align.CENTER, Align.CENTER, Align.CENTER)
        )
    elif shape == "cylinder":
        payload_part = Cylinder(
            radius=radius,
            height=radius * 2.0,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    else:
        raise ValueError(
            f"Unsupported payload.shape '{shape}'. Expected sphere, cube, box, or cylinder."
        )

    payload_part = payload_part.move(
        Location((float(start[0]), float(start[1]), float(start[2])))
    )
    payload_part.label = label
    payload_part.metadata = PartMetadata(material_id=material_id, fixed=False)
    return payload_part


_payload_contract = _load_payload()
_payload = _build_payload(_payload_contract)


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    # Add authored benchmark fixtures to this children list.
    # Every top-level child you add here must have a unique label, and that label
    # must not be `environment`, start with `zone_`, or start with
    # `benchmark_payload__` because the simulator reserves those names for the
    # scene root and generated objective bodies.
    environment = Compound(children=[_payload])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
