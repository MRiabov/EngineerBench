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
):
    part = Box(length, width, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = part.move(Location((x, y, z)))
    part.label = label
    part.metadata = PartMetadata(material_id=material_id, fixed=True)
    return part


def build():
    # Build the platform_handoff subassembly containing all engineered parts.
    parts = [
        _build_part(
            label="handoff_base",
            length=148.0,
            width=140.0,
            height=10.0,
            x=246.0,
            y=0.0,
            z=0.0,
            material_id="aluminum_6061",
        ),
        _build_part(
            label="catch_funnel",
            length=140.0,
            width=130.0,
            height=42.0,
            x=245.0,
            y=0.0,
            z=125.0,
            material_id="hdpe",
        ),
        _build_part(
            label="upper_guide_left",
            length=120.0,
            width=18.0,
            height=34.0,
            x=260.0,
            y=-61.0,
            z=167.0,
            material_id="hdpe",
        ),
        _build_part(
            label="upper_guide_right",
            length=120.0,
            width=18.0,
            height=34.0,
            x=260.0,
            y=61.0,
            z=167.0,
            material_id="hdpe",
        ),
        _build_part(
            label="goal_ramp",
            length=170.0,
            width=90.0,
            height=22.0,
            x=235.0,
            y=0.0,
            z=215.0,
            material_id="hdpe",
        ),
        _build_part(
            label="platform_clearance_guard",
            length=98.0,
            width=18.0,
            height=80.0,
            x=221.0,
            y=80.0,
            z=0.0,
            material_id="hdpe",
        ),
    ]

    subassembly = Compound(children=parts)
    subassembly.label = "platform_handoff"
    subassembly.metadata = CompoundMetadata()

    # Wrap in an unlabeled root so the subassembly label is counted by the
    # identity-pair validator.
    assembly = Compound(children=[subassembly])
    assembly.metadata = CompoundMetadata()
    return assembly
