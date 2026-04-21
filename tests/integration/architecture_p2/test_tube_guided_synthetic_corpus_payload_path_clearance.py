from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dataset.synthetic.tube_guided_synthetic_rigid_body_corpus.pipeline import (
    assert_payload_path_workspace_clear,
)
from shared.models.schemas import (
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    Constraints,
    ObjectivesSection,
    Payload,
    PayloadTrajectoryAnchor,
    PayloadTrajectoryDefinition,
    PayloadTrajectoryPose,
    PhysicsConfig,
)
from shared.models.serialization import dump_yaml_model
from shared.simulation.schemas import SimulatorBackendType

pytestmark = [pytest.mark.integration, pytest.mark.integration_p2]


def _benchmark_definition() -> BenchmarkDefinition:
    return BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(19.5, -0.5, -0.5),
                max_mm=(20.5, 0.5, 0.5),
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-5.0, -5.0, -5.0),
                max_mm=(25.0, 5.0, 5.0),
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
            min_mm=(-10.0, -10.0, -10.0),
            max_mm=(30.0, 10.0, 10.0),
        ),
        payload=Payload(
            label="payload_ball",
            shape="sphere",
            material_id="abs",
            start_position_mm=(0.0, 0.0, 0.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=100.0, max_weight_g=1000.0),
    )


def _payload_definition() -> PayloadTrajectoryDefinition:
    return PayloadTrajectoryDefinition(
        backend=SimulatorBackendType.MUJOCO,
        payload_part_names=["payload_ball"],
        initial_pose=PayloadTrajectoryPose(
            reference_point="payload_ball",
            pos_mm=(0.0, 0.0, 0.0),
            rot_deg=(0.0, 0.0, 0.0),
        ),
        sample_stride_s=1.0,
        anchors=[
            PayloadTrajectoryAnchor(
                t_s=0.0,
                reference_point="payload_ball",
                pos_mm=(0.0, 0.0, 0.0),
                rot_deg=(0.0, 0.0, 0.0),
                position_tolerance_mm=(0.0, 0.0, 0.0),
                build_zone_valid=True,
            ),
            PayloadTrajectoryAnchor(
                t_s=1.0,
                reference_point="payload_ball",
                pos_mm=(20.0, 0.0, 0.0),
                rot_deg=(0.0, 0.0, 0.0),
                position_tolerance_mm=(0.0, 0.0, 0.0),
                goal_zone_contact=True,
            ),
        ],
    )


def _write_workspace_script(
    path: Path,
    *,
    role: str,
    extra_blocker: bool,
) -> None:
    if role == "benchmark":
        script = """
from build123d import Box, Location

from shared.models.schemas import PartMetadata


def build():
    fixture = Box(1.0, 1.0, 1.0).move(Location((10.0, 4.0, 0.0)))
    fixture.label = "environment_fixture"
    fixture.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
    return fixture
"""
    elif extra_blocker:
        script = """
from build123d import Box, Compound, Location

from shared.models.schemas import PartMetadata


def build():
    payload = Box(1.0, 1.0, 1.0)
    payload.label = "payload_ball"
    payload.metadata = PartMetadata(material_id="abs", is_fixed=False)

    blocker = Box(1.0, 1.0, 1.0)
    blocker.label = "spawned_blocker"
    blocker.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    scene = Compound(children=[payload, blocker])
    scene.label = "solution_scene"
    return scene
"""
    else:
        script = """
from build123d import Box

from shared.models.schemas import PartMetadata


def build():
    payload = Box(1.0, 1.0, 1.0)
    payload.label = "payload_ball"
    payload.metadata = PartMetadata(material_id="abs", is_fixed=False)
    return payload
"""
    path.write_text(script.strip() + "\n", encoding="utf-8")


@pytest.mark.int_id("INT-288")
def test_tube_guided_synthetic_corpus_payload_path_clearance_rejects_spawned_overlap(
    tmp_path: Path,
):
    benchmark_definition = _benchmark_definition()
    payload_definition = _payload_definition()
    payload_yaml = dump_yaml_model(payload_definition)
    payload_model = PayloadTrajectoryDefinition.model_validate(
        yaml.safe_load(payload_yaml)
    )
    assert payload_model == payload_definition

    clean_workspace = tmp_path / "workspace_clean"
    clean_workspace.mkdir(parents=True, exist_ok=True)
    _write_workspace_script(
        clean_workspace / "benchmark_script.py", role="benchmark", extra_blocker=False
    )
    _write_workspace_script(
        clean_workspace / "solution_script.py", role="solution", extra_blocker=False
    )
    (clean_workspace / "payload_trajectory_definition.yaml").write_text(
        payload_yaml, encoding="utf-8"
    )

    assert_payload_path_workspace_clear(
        workspace_root=clean_workspace,
        benchmark_definition=benchmark_definition,
        payload_definition=payload_model,
        session_id="INT-288-clean",
    )

    dirty_workspace = tmp_path / "workspace_dirty"
    dirty_workspace.mkdir(parents=True, exist_ok=True)
    _write_workspace_script(
        dirty_workspace / "benchmark_script.py", role="benchmark", extra_blocker=False
    )
    _write_workspace_script(
        dirty_workspace / "solution_script.py", role="solution", extra_blocker=True
    )
    (dirty_workspace / "payload_trajectory_definition.yaml").write_text(
        payload_yaml, encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="moved payload intersects fixed geometry"):
        assert_payload_path_workspace_clear(
            workspace_root=dirty_workspace,
            benchmark_definition=benchmark_definition,
            payload_definition=payload_model,
            session_id="INT-288-dirty",
        )
