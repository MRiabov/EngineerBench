from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    material_id: str,
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, is_fixed=True)
    return part


def build():
    fixtures = Compound(
        children=[
            _make_box(
                "left_launch_pad",
                (120.0, 120.0, 110.0),
                (-180.0, 0.0, 55.0),
                "aluminum_6061",
            ),
            _make_box(
                "central_blocker",
                (140.0, 260.0, 150.0),
                (190.0, 0.0, 75.0),
                "aluminum_6061",
            ),
            _make_box(
                "upper_route_wall",
                (360.0, 20.0, 120.0),
                (260.0, 140.0, 60.0),
                "hdpe",
            ),
            _make_box(
                "lower_route_wall",
                (360.0, 20.0, 120.0),
                (260.0, -140.0, 60.0),
                "hdpe",
            ),
            _make_box(
                "goal_catch_tray",
                (130.0, 110.0, 30.0),
                (470.0, 0.0, 30.0),
                "hdpe",
            ),
        ]
    )
    fixtures.label = "benchmark_fixtures"
    fixtures.metadata = CompoundMetadata()
    return fixtures
