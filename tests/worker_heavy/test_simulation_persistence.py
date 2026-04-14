import json
import os
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="physics_sims")]
from build123d import Box

from shared.models.simulation import SimulationMetrics, StressSummary
from worker_heavy.utils.validation import (
    get_stress_report,
    simulate,
)


@pytest.fixture
def mock_simulation_dependencies():
    with (
        patch("worker_heavy.utils.validation.get_simulation_builder") as mock_builder,
        patch("worker_heavy.simulation.loop.SimulationLoop") as mock_loop_cls,
        patch("worker_heavy.utils.validation.prerender_24_views") as mock_render,
        patch("worker_heavy.utils.validation.calculate_assembly_totals") as mock_totals,
        patch("worker_heavy.utils.validation.validate_and_price"),
    ):
        # Mock builder
        mock_scene_path = MagicMock()
        mock_scene_path.read_text.return_value = "<mujoco/>"
        mock_scene_path.exists.return_value = True
        mock_builder.return_value.build_from_assembly.return_value = mock_scene_path

        # Mock loop
        mock_loop = mock_loop_cls.return_value
        mock_loop.render_provenance = None
        mock_loop.render_object_store_key = None

        stress_summary = StressSummary(
            part_label="part1",
            max_von_mises_pa=100.0,
            mean_von_mises_pa=50.0,
            safety_factor=2.0,
            location_of_max=(0.0, 0.0, 0.0),
            utilization_pct=50.0,
        )

        mock_metrics = SimulationMetrics(
            total_time=10.0,
            total_energy=100.0,
            max_velocity=1.0,
            success=True,
            stress_summaries=[stress_summary],
            stress_fields={
                "part1": {"nodes": [[0, 0, 0], [1, 1, 1]], "stress": [100.0, 50.0]}
            },
            fluid_metrics=[],
        )
        mock_loop.step.return_value = mock_metrics

        # Mock render
        mock_render.return_value = ["render.png"]

        # Mock totals
        mock_totals.return_value = (10.0, 5.0)

        yield


def test_simulation_persistence(tmp_path, mock_simulation_dependencies):
    # Set up environment
    os.environ["RENDERS_DIR"] = str(tmp_path / "renders")

    # Create a dummy component
    component = Box(10, 10, 10)
    component.label = "part1"

    # 1. Run simulation
    # We pass output_dir=tmp_path
    result = simulate(component, output_dir=tmp_path)

    assert result.success
    assert (tmp_path / "simulation_result.json").exists()

    # Verify content
    data = json.loads((tmp_path / "simulation_result.json").read_text())
    assert data["success"] is True
    assert len(data["stress_summaries"]) == 1
    assert data["stress_summaries"][0]["part_label"] == "part1"

    # 3. Call get_stress_report
    # It should look in cwd or RENDERS_DIR parent.
    # Since we set RENDERS_DIR to tmp_path/renders, parent is tmp_path.
    # And simulation_result.json is in tmp_path.

    report = get_stress_report("part1")
    assert report is not None
    assert report.part_label == "part1"
    assert report.max_von_mises_pa == 100.0
