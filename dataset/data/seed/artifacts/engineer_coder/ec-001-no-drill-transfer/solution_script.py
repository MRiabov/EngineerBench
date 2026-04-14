"""Freestanding no-drill transfer solution for the projectile-ball benchmark."""

from __future__ import annotations

from build123d import Align, Box, Compound, Location

from shared.enums import ManufacturingMethod
from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    """Build the freestanding no-drill transfer assembly."""

    # --- freestanding_base: wide aluminum base, no attachment ---
    freestanding_base = Box(
        620, 180, 12, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
    freestanding_base.label = "freestanding_base"
    freestanding_base.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- ballast_block: steel mass low on the base for stability ---
    ballast_block = Box(180, 80, 18, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ballast_block = ballast_block.move(Location((0, 0, 12)))
    ballast_block.label = "ballast_block"
    ballast_block.metadata = PartMetadata(
        material_id="steel_structural",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- capture_funnel: wide pocket covering the spawn jitter ---
    capture_funnel = Box(
        160, 140, 40, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
    capture_funnel = capture_funnel.move(Location((-250, 0, 30)))
    capture_funnel.label = "capture_funnel"
    capture_funnel.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- left_wall: left chute wall ---
    left_wall = Box(460, 20, 32, align=(Align.CENTER, Align.CENTER, Align.MIN))
    left_wall = left_wall.move(Location((-20, -50, 30)))
    left_wall.label = "left_wall"
    left_wall.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- right_wall: right chute wall ---
    right_wall = Box(460, 20, 32, align=(Align.CENTER, Align.CENTER, Align.MIN))
    right_wall = right_wall.move(Location((-20, 50, 30)))
    right_wall.label = "right_wall"
    right_wall.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- exit_tray: goal-side tray overlapping the seeded goal zone ---
    exit_tray = Box(140, 110, 35, align=(Align.CENTER, Align.CENTER, Align.MIN))
    exit_tray = exit_tray.move(Location((260, 0, 30)))
    exit_tray.label = "exit_tray"
    exit_tray.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    assembly = Compound(
        children=[
            freestanding_base,
            ballast_block,
            capture_funnel,
            left_wall,
            right_wall,
            exit_tray,
        ]
    )
    assembly.label = "freestanding_transfer"
    assembly.metadata = CompoundMetadata()
    return assembly


result = build()
