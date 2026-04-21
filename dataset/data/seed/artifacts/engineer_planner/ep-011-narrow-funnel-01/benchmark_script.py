from __future__ import annotations

from build123d import BuildPart, BuildSketch, Compound, Location, Plane, Polygon, loft

from utils.metadata import CompoundMetadata, PartMetadata


def _make_fixture(label: str):
    with BuildPart() as fixture_builder:
        # A vertical loft makes the funnel read clearly from the benchmark
        # renders without adding extra benchmark-owned labels.
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
    """Return the benchmark assembly geometry for this workspace."""

    # Do NOT include the payload here. The simulator spawns `projectile_ball`
    # from `benchmark_definition.yaml`.
    environment_fixture = _make_fixture("environment_fixture")
    environment = Compound(children=[environment_fixture])
    environment.label = "benchmark_environment"
    environment.metadata = CompoundMetadata()
    return environment


result = build()
