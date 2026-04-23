from __future__ import annotations

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _make_part(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return part


def build() -> Compound:
    base_frame = _make_part("base_frame", (560.0, 180.0, 12.0), (0.0, 0.0, 6.0))
    bridge_deck = _make_part("bridge_deck", (300.0, 95.0, 8.0), (0.0, 0.0, 20.0))
    left_fence = _make_part("left_fence", (300.0, 20.0, 35.0), (0.0, 57.5, 33.5))
    right_fence = _make_part("right_fence", (300.0, 20.0, 35.0), (0.0, -57.5, 33.5))
    landing_pocket = _make_part(
        "landing_pocket",
        (130.0, 110.0, 30.0),
        (185.0, 0.0, 15.0),
    )

    assembly = Compound(
        children=[base_frame, bridge_deck, left_fence, right_fence, landing_pocket]
    )
    assembly.label = "lower_bin_redirector"
    assembly.metadata = CompoundMetadata()
    return assembly


result = build()
