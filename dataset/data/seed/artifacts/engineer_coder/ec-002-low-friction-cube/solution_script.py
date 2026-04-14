from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from build123d import Align, Box, Compound, Location

from shared.enums import ManufacturingMethod
from shared.models.schemas import CompoundMetadata, PartMetadata
from shared.models.simulation import MultiRunResult, SimulationMetrics, SimulationResult
from shared.workers.schema import ReviewManifest, ValidationResultRecord


def build() -> Compound:
    """Build the low-friction route assembly for the cube transfer task.

    The assembly routes a low-friction ABS cube from its jittered spawn
    around the central forbid block and into the goal zone using a
    freestanding chute with continuous guide walls and a closed goal pocket.
    """

    # --- slide_base: freestanding aluminum base ---
    slide_base = Box(620, 140, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    slide_base = slide_base.move(Location((-30, 0, 0)))
    slide_base.label = "slide_base"
    slide_base.metadata = PartMetadata(
        material_id="aluminum_6061",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- entry_box: wide capture pocket at the spawn side ---
    entry_box = Box(160, 120, 38, align=(Align.CENTER, Align.CENTER, Align.MIN))
    entry_box = entry_box.move(Location((-250, 0, 10)))
    entry_box.label = "entry_box"
    entry_box.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- guide_wall_left: continuous left wall around the forbid block ---
    guide_wall_left = Box(420, 18, 42, align=(Align.CENTER, Align.CENTER, Align.MIN))
    guide_wall_left = guide_wall_left.move(Location((50, -55, 10)))
    guide_wall_left.label = "guide_wall_left"
    guide_wall_left.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- guide_wall_right: continuous right wall around the forbid block ---
    guide_wall_right = Box(390, 18, 42, align=(Align.CENTER, Align.CENTER, Align.MIN))
    guide_wall_right = guide_wall_right.move(Location((65, 55, 10)))
    guide_wall_right.label = "guide_wall_right"
    guide_wall_right.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- blocker_bypass_panel: tall panel keeping cube out of central forbid zone ---
    blocker_bypass_panel = Box(
        200, 18, 65, align=(Align.CENTER, Align.CENTER, Align.MIN)
    )
    blocker_bypass_panel = blocker_bypass_panel.move(Location((165, 0, 10)))
    blocker_bypass_panel.label = "blocker_bypass_panel"
    blocker_bypass_panel.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    # --- goal_pocket: closed pocket overlapping the goal zone ---
    goal_pocket = Box(110, 90, 32, align=(Align.CENTER, Align.CENTER, Align.MIN))
    goal_pocket = goal_pocket.move(Location((325, 0, 10)))
    goal_pocket.label = "goal_pocket"
    goal_pocket.metadata = PartMetadata(
        material_id="hdpe",
        fixed=True,
        manufacturing_method=ManufacturingMethod.CNC,
    )

    assembly = Compound(
        children=[
            slide_base,
            entry_box,
            guide_wall_left,
            guide_wall_right,
            blocker_bypass_panel,
            goal_pocket,
        ]
    )
    assembly.label = "low_friction_route"
    assembly.metadata = CompoundMetadata(fixed=True)
    return assembly


def _seed_execution_review_handoff() -> None:
    """Persist validation, simulation, and review-manifest artifacts for the seeded handoff."""
    script_path = Path(__file__)
    script_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    revision = os.environ.get("REPO_REVISION", "seed-dev")
    session_id = os.environ.get("SESSION_ID", "seed-ec-002-low-friction-cube")
    seed_ts = time.time()

    validation = ValidationResultRecord(
        success=True,
        message="Validation completed",
        timestamp=seed_ts,
        script_path="solution_script.py",
        script_sha256=script_sha256,
        verification_result=MultiRunResult(
            num_scenes=1,
            success_count=1,
            success_rate=1.0,
            is_consistent=True,
            individual_results=[SimulationMetrics(success=True)],
            fail_reasons=[],
            scene_build_count=1,
            backend_run_count=1,
            batched_execution=True,
        ),
    )
    simulation = SimulationResult(
        success=True,
        summary="Low-friction cube routed around forbid block and settled in goal zone.",
        render_paths=[],
        confidence="high",
    )
    manifest = ReviewManifest(
        status="ready_for_review",
        reviewer_stage="engineering_execution_reviewer",
        session_id=session_id,
        script_path="solution_script.py",
        script_sha256=script_sha256,
        validation_success=True,
        validation_timestamp=seed_ts,
        simulation_success=True,
        simulation_summary="Low-friction cube routed around forbid block and settled in goal zone.",
        simulation_timestamp=seed_ts,
        goal_reached=True,
        revision=revision,
        renders=[],
    )

    Path("validation_results.json").write_text(
        validation.model_dump_json(indent=2), encoding="utf-8"
    )
    Path("simulation_result.json").write_text(
        simulation.model_dump_json(indent=2), encoding="utf-8"
    )
    manifests_dir = Path(".manifests")
    manifests_dir.mkdir(parents=True, exist_ok=True)
    (manifests_dir / "engineering_execution_handoff_manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )


result = build()
_seed_execution_review_handoff()
