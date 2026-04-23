from __future__ import annotations

from build123d import Align, Axis, Box, BuildPart, BuildSketch, Compound, Ellipse, Location, extrude

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


def _make_oval_wall(
    label: str,
    radii: tuple[float, float],
    height: float,
    center: tuple[float, float, float],
    material_id: str,
):
    with BuildPart() as bp:
        with BuildSketch() as sk:
            Ellipse(*radii)
        extrude(amount=height)
    part = bp.part.move(Location(center))
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
            _make_oval_wall(
                "perimeter_wall_north",
                (560.0, 7.0),
                180.0,
                (250.0, 287.0, 96.0),
                "hardwood",
            ),
            _make_oval_wall(
                "perimeter_wall_south",
                (560.0, 7.0),
                180.0,
                (250.0, -287.0, 96.0),
                "hardwood",
            ),
            _make_oval_wall(
                "perimeter_wall_west",
                (7.0, 280.0),
                180.0,
                (-314.0, 0.0, 96.0),
                "hardwood",
            ),
            _make_oval_wall(
                "perimeter_wall_east",
                (7.0, 280.0),
                180.0,
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
                (-20.0, 110.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "corridor_block_c",
                (80.0, 130.0, 170.0),
                (130.0, -110.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "noise_pillar_a",
                (42.0, 42.0, 120.0),
                (40.0, -10.0, 66.0),
                "hardwood",
                fillet_radius=1.5,
                chamfer_length=1.0,
            ),
            _make_box(
                "corridor_block_d",
                (80.0, 130.0, 170.0),
                (280.0, 115.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "noise_beam_a",
                (200.0, 30.0, 24.0),
                (350.0, 0.0, 220.0),
                "hardwood",
                fillet_radius=1.0,
            ),
            _make_box(
                "corridor_block_e",
                (80.0, 130.0, 170.0),
                (430.0, -105.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "corridor_block_f",
                (80.0, 130.0, 170.0),
                (570.0, 120.0, 91.0),
                "hardwood",
                fillet_radius=4.0,
                chamfer_length=2.0,
            ),
            _make_box(
                "goal_catch_tray",
                (90.0, 60.0, 30.0),
                (760.0, 160.0, 21.0),
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
