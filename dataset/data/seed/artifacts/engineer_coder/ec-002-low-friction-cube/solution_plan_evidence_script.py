from build123d import (
    BuildLine,
    BuildPart,
    BuildSketch,
    Compound,
    Plane,
    Polyline,
    Rectangle,
    sweep,
)

from utils.metadata import CompoundMetadata, PartMetadata


def _make_fixed_rail() -> Compound:
    rail_path_points = [
        (-280.0, 0.0, 140.0),
        (-240.0, 0.0, 128.0),
        (-240.0, 110.0, 110.0),
        (-40.0, 110.0, 86.0),
        (240.0, 110.0, 50.0),
        (315.0, 0.0, 17.0),
    ]

    with BuildLine() as route_line:
        Polyline(rail_path_points)

    with BuildSketch(Plane(origin=rail_path_points[0])) as route_section:
        Rectangle(12.0, 6.0)

    with BuildPart() as route:
        sweep(route_section.sketch, path=route_line.line)

    rail = route.part
    rail.label = "guide_rail"
    rail.metadata = PartMetadata(material_id="hdpe", fixed=True)
    return rail


def build() -> Compound:
    assembly = Compound(children=[_make_fixed_rail()])
    assembly.label = "low_friction_route"
    assembly.metadata = CompoundMetadata()
    return assembly


result = build()
