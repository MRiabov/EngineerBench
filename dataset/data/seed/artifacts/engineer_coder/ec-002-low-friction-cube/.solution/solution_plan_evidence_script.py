from build123d import (
    Axis,
    BuildLine,
    BuildPart,
    BuildSketch,
    Plane,
    Polyline,
    Rectangle,
    offset,
    sweep,
)

from utils.metadata import PartMetadata


def build():
    path_points = [
        (-280.0, 0.0, 180.0),
        (-240.0, 0.0, 168.0),
        (-240.0, 110.0, 150.0),
        (-40.0, 110.0, 126.0),
        (240.0, 110.0, 90.0),
        (315.0, 0.0, 57.0),
    ]

    with BuildLine() as route_line:
        Polyline(path_points)

    with BuildSketch(Plane.XY) as route_section:
        Rectangle(44.0, 44.0)

    with BuildPart() as route:
        sweep(route_section.sketch, path=route_line.line)

    rail = route.part
    top_face = rail.faces().sort_by(Axis.Z)[-1]
    rail = offset(rail, amount=-6.0, openings=top_face)
    rail.label = "solution_plan_evidence"
    rail.metadata = PartMetadata(material_id="hdpe", is_fixed=True)
    return rail


result = build()
