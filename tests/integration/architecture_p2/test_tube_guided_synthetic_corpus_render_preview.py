from __future__ import annotations

import uuid
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
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName, ManufacturingMethod
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    CostTotals,
    ManufacturedPartEstimate,
    ObjectivesSection,
    Payload,
    PhysicsConfig,
)
from shared.models.serialization import dump_yaml_model
from shared.models.simulation import SimulationResult
from shared.simulation.schemas import SimulatorBackendType
from worker_heavy.utils.validation import simulate_subprocess

pytestmark = [
    pytest.mark.integration,
    pytest.mark.integration_p2,
    pytest.mark.xdist_group(name="physics_sims"),
]


def _route_points() -> list[RoutePoint]:
    return [
        RoutePoint(name="build_zone_start", pos_mm=(-280.0, 0.0, 180.0), t_s=0.0),
        RoutePoint(name="left_capture_lane", pos_mm=(-240.0, 0.0, 160.0), t_s=1.5),
        RoutePoint(name="bypass_corner", pos_mm=(-240.0, 110.0, 120.0), t_s=2.4),
        RoutePoint(name="goal_lane_entry", pos_mm=(-40.0, 110.0, 70.0), t_s=3.6),
        RoutePoint(name="goal_approach", pos_mm=(240.0, 110.0, 50.0), t_s=4.8),
        RoutePoint(name="goal_zone_contact", pos_mm=(325.0, 0.0, 40.0), t_s=6.0),
    ]


def _solution_script_content() -> str:
    return """
from build123d import Align, Box

from shared.models.schemas import PartMetadata


def build():
    part = Box(1.0, 1.0, 1.0, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part.label = "fixture_box"
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=False)
    return part
"""


def _benchmark_definition(route_points: list[RoutePoint]) -> BenchmarkDefinition:
    route_start = tuple(float(value) for value in route_points[0].pos_mm)
    route_goal = tuple(float(value) for value in route_points[-1].pos_mm)
    return BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(route_goal[0] - 30.0, route_goal[1] - 30.0, 0.0),
                max_mm=(route_goal[0] + 30.0, route_goal[1] + 30.0, 140.0),
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-360.0, -160.0, 0.0),
                max_mm=(380.0, 220.0, 260.0),
            ),
        ),
        benchmark_parts=[
            BenchmarkPartDefinition(
                part_id="environment_fixture",
                label="environment_fixture",
                metadata=BenchmarkPartMetadata(
                    is_fixed=True,
                    material_id="aluminum_6061",
                ),
            )
        ],
        physics=PhysicsConfig(backend=SimulatorBackendType.MUJOCO),
        simulation_bounds_mm=BoundingBox(
            min_mm=(-420.0, -220.0, -40.0),
            max_mm=(420.0, 260.0, 320.0),
        ),
        payload=Payload(
            label="slider_ball",
            shape="sphere",
            material_id="abs",
            start_position_mm=route_start,
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )


def _assembly_definition() -> AssemblyDefinition:
    return AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            benchmark_max_unit_cost_usd=100.0,
            benchmark_max_weight_g=1000.0,
            planner_target_max_unit_cost_usd=90.0,
            planner_target_max_weight_g=900.0,
        ),
        manufactured_parts=[
            ManufacturedPartEstimate(
                part_name="fixture_box",
                part_id="fixture_box",
                manufacturing_method=ManufacturingMethod.THREE_DP,
                material_id="aluminum_6061",
                quantity=1,
                part_volume_mm3=1000.0,
                stock_bbox_mm={"x": 10.0, "y": 10.0, "z": 10.0},
                stock_volume_mm3=1000.0,
                removed_volume_mm3=0.0,
                estimated_unit_cost_usd=10.0,
            )
        ],
        final_assembly=[],
        totals=CostTotals(
            estimated_unit_cost_usd=10.0,
            estimated_weight_g=100.0,
            estimate_confidence="high",
        ),
    )


def _workspace_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.mark.int_id("INT-282")
def test_tube_guided_synthetic_corpus_render_preview_uses_workspace_payload_definition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    route_points = _route_points()
    session_id = f"INT-282-{uuid.uuid4().hex[:8]}"

    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

    benchmark_definition = _benchmark_definition(route_points)
    payload_trajectory = payload_trajectory_dict(
        payload_name="slider_ball",
        route_points=route_points,
        first_contacts=[],
        terminal_reference_point=route_points[-1].name,
        backend=SimulatorBackendType.MUJOCO,
        sample_stride_s=0.1,
    )

    _workspace_write(
        workspace_root / ".manifests" / "current_role.json",
        current_role_manifest_json(AgentName.BENCHMARK_CODER),
    )
    _workspace_write(
        workspace_root / "benchmark_script.py",
        _solution_script_content(),
    )
    _workspace_write(
        workspace_root / "assembly_definition.yaml",
        dump_yaml_model(_assembly_definition()),
    )
    _workspace_write(
        workspace_root / "benchmark_definition.yaml",
        dump_yaml_model(benchmark_definition),
    )
    _workspace_write(
        workspace_root / "payload_trajectory_definition.yaml",
        yaml.safe_dump(payload_trajectory, sort_keys=False),
    )

    simulation_result = simulate_subprocess(
        script_path=workspace_root / "benchmark_script.py",
        session_root=workspace_root,
        output_dir=workspace_root,
        smoke_test_mode=True,
        backend=SimulatorBackendType.MUJOCO,
        session_id=session_id,
        skip_preview_rendering=True,
    )

    simulation_result = SimulationResult.model_validate(simulation_result)
    assert simulation_result.render_provenance is not None, simulation_result
    assert simulation_result.render_provenance.resolved_camera_name == "main", (
        simulation_result.render_provenance.model_dump(mode="json")
    )
    assert not simulation_result.render_provenance.used_default_view, (
        simulation_result.render_provenance.model_dump(mode="json")
    )
    assert "main" in simulation_result.render_provenance.available_camera_names, (
        simulation_result.render_provenance.model_dump(mode="json")
    )
    assert simulation_result.render_provenance.camera_candidates[:1] == ["main"], (
        simulation_result.render_provenance.model_dump(mode="json")
    )
    assert simulation_result.render_provenance.captured_frame_count > 0, (
        simulation_result.render_provenance.model_dump(mode="json")
    )
    assert simulation_result.mjcf_content is not None, simulation_result.model_dump(
        mode="json"
    )
    assert 'camera name="main"' in simulation_result.mjcf_content, (
        simulation_result.mjcf_content
    )
    assert 'target="zone_build"' in simulation_result.mjcf_content, (
        simulation_result.mjcf_content
    )
    assert simulation_result.payload_trajectory_monitor is not None, (
        simulation_result.model_dump(mode="json")
    )
    assert any(
        "slider_ball" in name
        for name in simulation_result.payload_trajectory_monitor.tracked_body_names
    ), simulation_result.payload_trajectory_monitor.model_dump(mode="json")

    video_path = next(
        (path for path in simulation_result.render_paths if path.endswith(".mp4")),
        None,
    )
    assert video_path is not None, simulation_result.render_paths
    objects_path = next(
        (
            path
            for path in simulation_result.render_paths
            if Path(path).name == "objects.parquet"
        ),
        None,
    )
    assert objects_path is not None, simulation_result.render_paths

    local_video_path = workspace_root / Path(video_path)
    local_object_pose_path = workspace_root / Path(objects_path)
    assert local_video_path.exists(), local_video_path
    assert local_object_pose_path.exists(), local_object_pose_path

    table = pq.read_table(local_object_pose_path)
    labels = set(table.column("label").to_pylist())
    body_names = set(table.column("body_name").to_pylist())
    semantic_labels = set(table.column("semantic_label").to_pylist())
    assert "benchmark_payload__slider_ball" in (
        labels | body_names | semantic_labels
    ), table.column_names
