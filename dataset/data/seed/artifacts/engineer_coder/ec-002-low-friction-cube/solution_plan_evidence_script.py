from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_part(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, fixed=True)
    return part


def build() -> Compound:
    entry_box = _make_part(
        "entry_box",
        (160.0, 120.0, 38.0),
        (-225.0, 0.0, 33.0),
        "hdpe",
    )
    entry_box = entry_box - Box(
        152.0,
        120.0,
        30.0,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    ).move(Location((-225.0, 0.0, 33.0)))
    entry_box.label = "entry_box"
    entry_box.metadata = PartMetadata(material_id="hdpe", fixed=True)

    parts = [
        _make_part(
            "slide_base",
            (620.0, 140.0, 10.0),
            (20.0, 0.0, 9.0),
            "aluminum_6061",
        ),
        entry_box,
        _make_part(
            "guide_wall_left",
            (420.0, 18.0, 42.0),
            (-40.0, -66.0, 35.0),
            "hdpe",
        ),
        _make_part(
            "guide_wall_right",
            (390.0, 18.0, 42.0),
            (0.0, 66.0, 35.0),
            "hdpe",
        ),
        _make_part(
            "blocker_bypass_panel",
            (200.0, 18.0, 65.0),
            (145.0, 42.0, 46.5),
            "hdpe",
        ),
        _make_part(
            "goal_pocket",
            (110.0, 90.0, 32.0),
            (315.0, 0.0, 30.0),
            "hdpe",
        ),
        _make_part(
            "solution_assembly",
            (10.0, 10.0, 10.0),
            (-280.0, 0.0, 24.0),
            "abs",
        ),
    ]
    assembly = Compound(children=parts)
    assembly.label = "low_friction_route"
    assembly.metadata = CompoundMetadata()
    return assembly


result = build()
