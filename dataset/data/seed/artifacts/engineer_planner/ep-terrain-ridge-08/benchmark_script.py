from __future__ import annotations

from build123d import Align, Axis, Box, BuildPart, Compound, Cylinder, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
    fillet_radius: float = 0.0,
    chamfer_length: float = 0.0,
    rotation: tuple[float, float, float] | None = None,
):
    with BuildPart() as bp:
        Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part = bp.part
    if fillet_radius > 0.0:
        part = part.fillet(fillet_radius, part.edges().filter_by(Axis.Z))
    if chamfer_length > 0.0:
        part = part.chamfer(chamfer_length, None, part.edges().group_by(Axis.Z)[-1])
    part = part.move(Location(center, rotation or (0.0, 0.0, 0.0)))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def _make_cylinder(
    label: str,
    radius: float,
    height: float,
    center: tuple[float, float, float],
    material_id: str,
):
    with BuildPart() as bp:
        Cylinder(
            radius=radius,
            height=height,
            rotation=(90.0, 0.0, 0.0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    part = bp.part.move(Location(center))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build() -> Compound:
    """Return the benchmark assembly geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_box(
                "terrain_base",
                (720.0, 180.0, 12.0),
                (0.0, 0.0, 6.0),
                "hardwood",
            ),
            _make_cylinder(
                "terrain_ridge",
                18.0,
                150.0,
                (0.0, 0.0, 34.0),
                "hdpe",
            ),
            _make_cylinder(
                "left_noise_pillar",
                12.0,
                28.0,
                (-210.0, -52.0, 26.0),
                "hardwood",
            ),
            _make_box(
                "right_noise_block",
                (38.0, 26.0, 18.0),
                (176.0, 50.0, 24.0),
                "hdpe",
            ),
            _make_box(
                "false_tray",
                (80.0, 60.0, 8.0),
                (214.0, -40.0, 20.0),
                "hardwood",
                fillet_radius=0.8,
                chamfer_length=0.6,
            ),
            _make_box(
                "canted_mid_beam",
                (30.0, 16.0, 72.0),
                (104.0, 14.0, 56.0),
                "hdpe",
                rotation=(0.0, 0.0, 20.0),
                fillet_radius=0.8,
                chamfer_length=0.5,
            ),
            _make_box(
                "north_wall",
                (700.0, 2.0, 10.0),
                (0.0, 89.0, 17.0),
                "hdpe",
                fillet_radius=0.5,
                chamfer_length=0.4,
            ),
            _make_box(
                "south_wall",
                (700.0, 2.0, 10.0),
                (0.0, -89.0, 17.0),
                "hdpe",
                fillet_radius=0.5,
                chamfer_length=0.4,
            ),
            _make_box(
                "west_wall",
                (2.0, 176.0, 10.0),
                (-405.0, 0.0, 17.0),
                "hdpe",
                fillet_radius=0.5,
                chamfer_length=0.4,
            ),
            _make_box(
                "east_wall",
                (2.0, 176.0, 10.0),
                (405.0, 0.0, 17.0),
                "hdpe",
                fillet_radius=0.5,
                chamfer_length=0.4,
            ),
            _make_box(
                "goal_catch_tray",
                (90.0, 90.0, 12.0),
                (345.0, 30.0, 24.0),
                "hardwood",
                fillet_radius=1.0,
                chamfer_length=0.6,
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
