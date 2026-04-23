from __future__ import annotations

from build123d import Align, Axis, Box, BuildPart, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
    fillet_radius: float = 0.0,
    chamfer_length: float = 0.0,
):
    with BuildPart() as bp:
        Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part = bp.part
    if fillet_radius > 0.0:
        part = part.fillet(fillet_radius, part.edges().filter_by(Axis.Z))
    if chamfer_length > 0.0:
        part = part.chamfer(chamfer_length, None, part.edges().group_by(Axis.Z)[-1])
    part = part.move(Location(center))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "corridor_floor",
                (1120.0, 560.0, 6.0),
                (250.0, 0.0, 3.0),
                "hardwood",
                fillet_radius=0.5,
            ),
            _make_box(
                "perimeter_wall_north",
                (1120.0, 14.0, 180.0),
                (250.0, 287.0, 96.0),
                "hardwood",
            ),
            _make_box(
                "perimeter_wall_south",
                (1120.0, 14.0, 180.0),
                (250.0, -287.0, 96.0),
                "hardwood",
            ),
            _make_box(
                "perimeter_wall_west",
                (14.0, 560.0, 180.0),
                (-314.0, 0.0, 96.0),
                "hardwood",
            ),
            _make_box(
                "perimeter_wall_east",
                (14.0, 560.0, 180.0),
                (814.0, 0.0, 96.0),
                "hardwood",
            ),
            _make_box(
                "left_launch_pad",
                (80.0, 60.0, 30.0),
                (-250.0, -190.0, 21.0),
                "hardwood",
                fillet_radius=2.0,
                chamfer_length=1.5,
            ),
            _make_box(
                "corridor_block_a",
                (80.0, 130.0, 170.0),
                (-170.0, -120.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "corridor_block_b",
                (80.0, 130.0, 170.0),
                (-10.0, -100.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "corridor_block_c",
                (80.0, 130.0, 170.0),
                (140.0, 125.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "center_divider",
                (40.0, 420.0, 180.0),
                (360.0, 10.0, 96.0),
                "hardwood",
            ),
            _make_box(
                "noise_pillar_a",
                (42.0, 42.0, 220.0),
                (40.0, 0.0, 117.0),
                "hardwood",
                fillet_radius=1.5,
                chamfer_length=1.0,
            ),
            _make_box(
                "corridor_block_d",
                (80.0, 130.0, 170.0),
                (285.0, -120.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "noise_beam_a",
                (220.0, 30.0, 24.0),
                (360.0, 10.0, 260.0),
                "hardwood",
                fillet_radius=1.0,
            ),
            _make_box(
                "corridor_block_e",
                (80.0, 130.0, 170.0),
                (440.0, 105.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "noise_pillar_b",
                (42.0, 42.0, 220.0),
                (600.0, 15.0, 117.0),
                "hardwood",
                fillet_radius=1.5,
                chamfer_length=1.0,
            ),
            _make_box(
                "corridor_block_f",
                (80.0, 130.0, 170.0),
                (585.0, -125.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "goal_catch_tray",
                (90.0, 60.0, 30.0),
                (760.0, -190.0, 21.0),
                "hardwood",
                fillet_radius=2.0,
                chamfer_length=1.5,
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
