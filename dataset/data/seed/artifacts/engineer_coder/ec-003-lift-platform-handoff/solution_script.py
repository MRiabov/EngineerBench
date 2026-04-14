"""Engineer coder solution: passive lift-platform handoff guide.

Implements the approved engineering plan for a passive catch-and-guide
assembly that receives a projectile ball from the moving benchmark
lift_platform and guides it into the seeded goal zone.

All parts are passive (zero DOFs) and stay outside the
platform_travel_clearance forbid zone.
"""

from build123d import Align, Box, Compound, Location

from utils.metadata import CompoundMetadata, PartMetadata


def _build_part(
    *,
    label: str,
    length: float,
    width: float,
    height: float,
    x: float,
    y: float,
    z: float,
    material_id: str,
) -> Box:
    """Create a passive part with proper metadata."""
    part = Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part.move(Location((x, y, z)))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, fixed=True)
    return part


def build() -> Compound:
    """Build the platform_handoff subassembly."""
    parts = [
        _build_part(
            label="handoff_base",
            length=300.0,
            width=140.0,
            height=10.0,
            x=190.0,
            y=0.0,
            z=0.0,
            material_id="aluminum_6061",
        ),
        _build_part(
            label="catch_funnel",
            length=150.0,
            width=130.0,
            height=42.0,
            x=190.0,
            y=0.0,
            z=125.0,
            material_id="hdpe",
        ),
        _build_part(
            label="upper_guide_left",
            length=240.0,
            width=18.0,
            height=34.0,
            x=190.0,
            y=-61.0,
            z=167.0,
            material_id="hdpe",
        ),
        _build_part(
            label="upper_guide_right",
            length=240.0,
            width=18.0,
            height=34.0,
            x=190.0,
            y=61.0,
            z=167.0,
            material_id="hdpe",
        ),
        _build_part(
            label="goal_ramp",
            length=170.0,
            width=90.0,
            height=22.0,
            x=230.0,
            y=0.0,
            z=215.0,
            material_id="hdpe",
        ),
        _build_part(
            label="platform_clearance_guard",
            length=18.0,
            width=150.0,
            height=80.0,
            x=175.0,
            y=0.0,
            z=0.0,
            material_id="hdpe",
        ),
    ]

    subassembly = Compound(children=parts)
    subassembly.label = "platform_handoff"
    subassembly.metadata = CompoundMetadata()

    assembly = Compound(children=[subassembly])
    assembly.label = "final_assembly"
    assembly.metadata = CompoundMetadata()
    return assembly
