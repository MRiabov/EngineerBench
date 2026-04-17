from __future__ import annotations

import json
import textwrap
from collections import defaultdict

from .models import PartSpec, RoutePoint
from .paths import REPO_ROOT


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
        from build123d import Align, Box, BuildPart, Compound, Extrinsic, Location
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

        def frame_from_segment(
            start_mm,
            end_mm,
            up_hint=(0.0, 0.0, 1.0),
            previous_frame=None,
        ):
            start = as_np(start_mm)
            end = as_np(end_mm)
            x_axis = normalize(end - start)
            up = normalize(as_np(up_hint))
            if abs(float(np.dot(x_axis, up))) > 0.95:
                up = np.array([0.0, 1.0, 0.0], dtype=float)
            if previous_frame is not None:
                previous_frame = np.asarray(previous_frame, dtype=float)
                transported_y = previous_frame[:, 1] - float(
                    np.dot(previous_frame[:, 1], x_axis)
                ) * x_axis
                if float(np.linalg.norm(transported_y)) > 1e-9:
                    y_axis = normalize(transported_y)
                else:
                    y_axis = normalize(np.cross(up, x_axis))
            else:
                y_axis = normalize(np.cross(up, x_axis))
            z_axis = normalize(np.cross(x_axis, y_axis))
            y_axis = normalize(np.cross(z_axis, x_axis))
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
                for idx in range(1, split_count):
                    lower = fractions[idx - 1] + 1e-4
                    upper = fractions[idx + 1] - 1e-4
                    fractions[idx] = min(max(fractions[idx], lower), upper)
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
            part = builder.part.moved(
                Location(
                    tuple(spec["center_mm"]),
                    tuple(spec["euler_deg"]),
                    Extrinsic.XYZ,
                )
            )
            part.label = spec["name"]
            part.metadata = PartMetadata(
                material_id=spec["material_id"],
                is_fixed=bool(spec.get("fixed", True)),
            )
            return part

        def box_part_specs_for_route(route_points, tube_radius_mm, clearance_mm, wall_thickness_mm, max_segment_mm, seed, material_id):
            corridor_width_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
            corridor_height_mm = 2.0 * tube_radius_mm + 2.0 * clearance_mm
            inner_width_mm = max(corridor_width_mm - 2.0 * wall_thickness_mm, wall_thickness_mm)
            inner_height_mm = max(corridor_height_mm - 2.0 * wall_thickness_mm, wall_thickness_mm)
            spans = route_spans(route_points, max_segment_mm=max_segment_mm, seed=seed)
            specs = []
            previous_frame = None

            for span in spans:
                start = as_np(span["start_mm"])
                end = as_np(span["end_mm"])
                frame, euler = frame_from_segment(
                    start,
                    end,
                    previous_frame=previous_frame,
                )
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
                            "is_fixed": True,
                        }}
                    )
                previous_frame = frame

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
            assembly.metadata = CompoundMetadata(is_fixed=True)
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
        REPO_ROOT
        / "shared"
        / "assets"
        / "template_repos"
        / "engineer"
        / "engineering_plan.md"
    ).read_text(encoding="utf-8")
    todo_template = (
        REPO_ROOT / "shared" / "assets" / "template_repos" / "engineer" / "todo.md"
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
