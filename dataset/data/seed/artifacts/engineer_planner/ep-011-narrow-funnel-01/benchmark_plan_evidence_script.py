from __future__ import annotations

from build123d import BuildPart, BuildSketch, Compound, Location, Plane, Polygon, loft

from utils.metadata import CompoundMetadata, PartMetadata


def _make_fixture(label: str):
    with BuildPart() as fixture_builder:
        with BuildSketch(Plane.XY.offset(0.0)):
            Polygon([(-18.0, -18.0), (18.0, -18.0), (18.0, 18.0), (-18.0, 18.0)])
        with BuildSketch(Plane.XY.offset(44.0)):
            Polygon([(-42.0, -42.0), (42.0, -42.0), (42.0, 42.0), (-42.0, 42.0)])
        with BuildSketch(Plane.XY.offset(118.0)):
            Polygon([(-84.0, -84.0), (84.0, -84.0), (84.0, 84.0), (-84.0, 84.0)])
        with BuildSketch(Plane.XY.offset(178.0)):
            Polygon(
                [(-126.0, -126.0), (126.0, -126.0), (126.0, 126.0), (-126.0, 126.0)]
            )
        loft()

    fixture = fixture_builder.part.move(Location((150.0, 0.0, 1.0)))
    fixture.label = label
    fixture.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return fixture


def build() -> Compound:
    """Return the benchmark plan evidence geometry for this workspace."""

    fixtures = Compound(
        children=[
            _make_fixture("environment_fixture"),
        ]
    )
    fixtures.label = "benchmark_environment"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
