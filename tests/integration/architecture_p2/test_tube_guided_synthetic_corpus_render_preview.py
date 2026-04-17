from __future__ import annotations

import os
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest
import yaml

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.contract import (
    payload_trajectory_dict,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.models import (
    RoutePoint,
)
from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.pipeline import (
    render_simulation_video_preview,
)
from shared.simulation.schemas import SimulatorBackendType

pytestmark = [pytest.mark.integration, pytest.mark.integration_p2]


def _solution_script_content() -> str:
    return """
from build123d import Align, Box

from shared.models.schemas import PartMetadata


def build():
    part = Box(1.0, 1.0, 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "simulation_video_smoke_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
    return part
"""


def _route_points() -> list[RoutePoint]:
    return [
        RoutePoint(name="build_zone_start", pos_mm=(-280.0, 0.0, 180.0), t_s=0.0),
        RoutePoint(name="left_capture_lane", pos_mm=(-240.0, 0.0, 160.0), t_s=1.5),
        RoutePoint(name="bypass_corner", pos_mm=(-240.0, 110.0, 120.0), t_s=2.4),
        RoutePoint(name="goal_lane_entry", pos_mm=(-40.0, 110.0, 70.0), t_s=3.6),
        RoutePoint(name="goal_approach", pos_mm=(240.0, 110.0, 50.0), t_s=4.8),
        RoutePoint(name="goal_zone_contact", pos_mm=(325.0, 0.0, 40.0), t_s=6.0),
    ]


@pytest.mark.asyncio
@pytest.mark.int_id("INT-282")
async def test_tube_guided_synthetic_corpus_render_preview_uses_workspace_payload_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_root = Path(
        "dataset/data/seed/artifacts/engineer_coder/ec-002-low-friction-cube"
    )
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    route_points = _route_points()

    for filename in ("assembly_definition.yaml",):
        shutil.copy2(source_root / filename, workspace_root / filename)

    benchmark_definition = yaml.safe_load(
        (source_root / "benchmark_definition.yaml").read_text(encoding="utf-8")
    )
    benchmark_definition["payload"]["label"] = "slider_ball"
    (workspace_root / "benchmark_definition.yaml").write_text(
        yaml.safe_dump(benchmark_definition, sort_keys=False),
        encoding="utf-8",
    )
    payload_trajectory = payload_trajectory_dict(
        payload_name="slider_ball",
        route_points=route_points,
        first_contacts=[],
        terminal_reference_point=route_points[-1].name,
        backend=SimulatorBackendType.MUJOCO,
        sample_stride_s=0.1,
    )
    (workspace_root / "payload_trajectory_definition.yaml").write_text(
        yaml.safe_dump(payload_trajectory, sort_keys=False),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "WORKER_HEAVY_URL", os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:28002")
    )

    summary = render_simulation_video_preview(
        backend_type=SimulatorBackendType.MUJOCO,
        script_content=_solution_script_content(),
        session_id=f"INT-282-{os.urandom(4).hex()}",
        workspace_root=workspace_root,
    )

    assert summary["success"], summary
    assert summary["local_object_pose_path"], summary

    table = pq.read_table(summary["local_object_pose_path"])
    labels = set(table.column("label").to_pylist())
    body_names = set(table.column("body_name").to_pylist())
    semantic_labels = set(table.column("semantic_label").to_pylist())
    assert "benchmark_payload__slider_ball" in (
        labels | body_names | semantic_labels
    ), table.column_names
