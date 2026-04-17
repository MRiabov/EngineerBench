#!/usr/bin/env python3
"""Probe how much semantic construction data build123d exposes for comparison."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build123d import Box, BuildPart, BuildSketch, Cylinder, Rectangle


def _normalize(value: Any, *, _depth: int = 0) -> Any:
    """Turn common build123d objects into stable JSON-compatible data."""
    if _depth > 5:
        return repr(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else repr(value)
    if all(hasattr(value, attr) for attr in ("X", "Y", "Z")):
        return {
            "x": round(float(value.X), 6),
            "y": round(float(value.Y), 6),
            "z": round(float(value.Z), 6),
        }
    if all(hasattr(value, attr) for attr in ("x", "y", "z")):
        return {
            "x": round(float(value.x), 6),
            "y": round(float(value.y), 6),
            "z": round(float(value.z), 6),
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item, _depth=_depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize(item, _depth=_depth + 1)
            for key, item in value.items()
            if not str(key).startswith("_")
        }
    if hasattr(value, "__dict__"):
        data: dict[str, Any] = {}
        for key, item in vars(value).items():
            if key.startswith("_") or callable(item):
                continue
            data[key] = _normalize(item, _depth=_depth + 1)
        if data:
            return {"__type__": type(value).__name__, **data}
    return repr(value)


def _interesting_dir_names(obj: Any) -> list[str]:
    names = []
    for name in dir(obj):
        lowered = name.lower()
        if any(
            token in lowered
            for token in ("child", "hist", "shape", "face", "wire", "obj", "part")
        ):
            names.append(name)
    return names


def _snapshot_object(name: str, obj: Any) -> dict[str, Any]:
    raw_dict = getattr(obj, "__dict__", {})
    visible_dict = {
        key: _normalize(value)
        for key, value in raw_dict.items()
        if not key.startswith("_") and not callable(value)
    }
    children = getattr(obj, "children", None)
    children_count = len(children) if isinstance(children, tuple) else None
    return {
        "name": name,
        "type": type(obj).__name__,
        "repr": repr(obj),
        "has_children": hasattr(obj, "children"),
        "children_count": children_count,
        "interesting_dir_names": _interesting_dir_names(obj)[:100],
        "visible_dict": visible_dict,
    }


@dataclass
class ProbeResult:
    probe_name: str
    generated_at: str
    build123d_part: dict[str, Any]
    build_part_builder: dict[str, Any]
    primitives: list[dict[str, Any]]
    sketch: dict[str, Any]
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "probe_name": self.probe_name,
            "generated_at": self.generated_at,
            "build123d_part": self.build123d_part,
            "build_part_builder": self.build_part_builder,
            "primitives": self.primitives,
            "sketch": self.sketch,
            "notes": self.notes,
        }


def run_probe() -> ProbeResult:
    box = Box(10, 20, 30)
    cylinder = Cylinder(5, 12)

    with BuildSketch() as sketch_builder:
        rectangle = Rectangle(8, 4)

    with BuildPart() as part_builder:
        box_in_part = Box(10, 20, 30)
        cylinder_in_part = Cylinder(5, 12)

    part = part_builder.part
    part_children = getattr(part, "children", ())
    part_metrics = {
        "type": type(part).__name__,
        "repr": repr(part),
        "has_children": hasattr(part, "children"),
        "children_count": len(part_children)
        if isinstance(part_children, tuple)
        else None,
        "solids_count": len(list(part.solids())) if hasattr(part, "solids") else None,
        "faces_count": len(list(part.faces())) if hasattr(part, "faces") else None,
        "edges_count": len(list(part.edges())) if hasattr(part, "edges") else None,
        "wires_count": len(list(part.wires())) if hasattr(part, "wires") else None,
        "bbox": _normalize(part.bounding_box())
        if hasattr(part, "bounding_box")
        else None,
        "volume": _normalize(getattr(part, "volume", None)),
        "visible_dict": _normalize(
            {
                key: value
                for key, value in vars(part).items()
                if not key.startswith("_") and not callable(value)
            }
        ),
    }

    builder_metrics = {
        "type": type(part_builder).__name__,
        "repr": repr(part_builder),
        "dir_names": _interesting_dir_names(part_builder)[:100],
        "dict_keys": list(vars(part_builder).keys()),
        "part_repr": repr(getattr(part_builder, "part", None)),
        "pending_faces_len": len(getattr(part_builder, "pending_faces", [])),
        "pending_edges_len": len(getattr(part_builder, "pending_edges", [])),
        "has_part_attr": hasattr(part_builder, "part"),
        "has_sketch_attr": hasattr(part_builder, "sketch"),
    }

    primitives = [
        _snapshot_object("box", box),
        _snapshot_object("cylinder", cylinder),
        _snapshot_object("box_in_part", box_in_part),
        _snapshot_object("cylinder_in_part", cylinder_in_part),
        _snapshot_object("rectangle", rectangle),
    ]

    sketch = _snapshot_object("sketch", sketch_builder.sketch)
    notes = [
        "Primitive objects expose authored parameter fields directly on the object.",
        "The fused BuildPart output keeps coarse topology metrics, but its children tuple is empty in this probe.",
        "A semantic comparison should therefore use primitive/component metadata and coarse invariants, not exact mesh equality.",
    ]

    return ProbeResult(
        probe_name="build123d_construction_signature_probe",
        generated_at=datetime.now(tz=UTC).isoformat(),
        build123d_part=part_metrics,
        build_part_builder=builder_metrics,
        primitives=primitives,
        sketch=sketch,
        notes=notes,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path(__file__).with_name(
            "latest-build123d-construction-signature.json"
        ),
        help="Where to write the JSON report.",
    )
    args = parser.parse_args()

    result = run_probe()
    payload = result.as_dict()
    args.json_out.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
