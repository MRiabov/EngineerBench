import os
import shutil
import uuid
from pathlib import Path

import pytest
import yaml

from controller.agent.node_entry_validation import (
    ValidationScope,
    _run_seed_validation_engineering_gate,
    validate_seeded_workspace_handoff_artifacts,
)
from controller.clients.worker import WorkerClient
from evals.logic.models import EvalDatasetItem
from evals.logic.workspace import (
    InMemorySeedWorkspaceClient,
    materialize_seed_workspace_snapshot,
)
from scripts.internal.eval_seed_selection import load_seed_dataset
from shared.agent_templates import load_role_template_files
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName
from shared.utils.agent import validate_engineering
from shared.workers.loader import load_component_from_script
from shared.workers.schema import BenchmarkToolResponse

ROOT = Path(__file__).resolve().parents[3]

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _seeded_planner_item(agent_name: AgentName, item_id: str) -> EvalDatasetItem:
    return EvalDatasetItem(
        id=item_id,
        task=f"{agent_name.value} workspace contract smoke test",
        complexity_level=0,
        seed_dataset=None,
        seed_files=load_role_template_files(agent_name),
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_current_role_manifest_wins_over_mixed_workspace_files():
    session_id = f"INT-CURRENT-ROLE-{uuid.uuid4().hex[:8]}"
    worker = WorkerClient(base_url=WORKER_LIGHT_URL, session_id=session_id)
    try:
        await worker.write_file(
            "benchmark_plan.md",
            "# Benchmark plan\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "engineering_plan.md",
            "# Engineering plan\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "todo.md",
            "- [ ] Mixed workspace\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_definition.yaml",
            yaml.safe_dump(
                {
                    "constraints": {"max_unit_cost": 100.0, "max_weight_g": 1000.0},
                    "objectives": {
                        "goal_zone": {"min": [0, 0, 0], "max": [1, 1, 1]},
                        "forbid_zones": [],
                        "build_zone": {"min": [0, 0, 0], "max": [1, 1, 1]},
                    },
                },
                sort_keys=False,
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "assembly_definition.yaml",
            yaml.safe_dump(
                {
                    "version": "1.0",
                    "constraints": {},
                    "manufactured_parts": [],
                    "final_assembly": [],
                    "totals": {
                        "estimated_unit_cost_usd": 0.0,
                        "estimated_weight_g": 0.0,
                        "estimate_confidence": "high",
                    },
                },
                sort_keys=False,
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_assembly_definition.yaml",
            yaml.safe_dump(
                {
                    "version": "1.0",
                    "constraints": {},
                    "manufactured_parts": [],
                    "final_assembly": [],
                    "totals": {
                        "estimated_unit_cost_usd": 0.0,
                        "estimated_weight_g": 0.0,
                        "estimate_confidence": "high",
                    },
                },
                sort_keys=False,
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_script.py",
            "print('benchmark script')\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "solution_script.py",
            "print('solution script')\n",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_CODER),
            overwrite=True,
            bypass_agent_permissions=True,
        )

        errors = await validate_seeded_workspace_handoff_artifacts(
            worker_client=worker,
            target_node=AgentName.ENGINEER_CODER,
        )
    finally:
        await worker.aclose()

    assert errors, "Expected the mixed workspace to fail for the engineer node."
    assert any(
        error.artifact_path == ".manifests/current_role.json"
        and "mismatch" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_benchmark_planner_seed_rejects_presolved_benchmark_plan():
    item = _seeded_planner_item(AgentName.BENCHMARK_PLANNER, "bp-starter-drift")
    item = item.model_copy(
        update={
            "seed_files": {
                **(item.seed_files or {}),
                "benchmark_plan.md": "# Benchmark plan\n\nSolved output\n",
            }
        }
    )

    session_id = f"INT-STARTER-{uuid.uuid4().hex[:8]}"
    snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
    await materialize_seed_workspace_snapshot(
        item=item,
        session_id=session_id,
        agent_name=AgentName.BENCHMARK_PLANNER,
        root=ROOT,
        workspace_client=snapshot_client,
        update_manifests=True,
    )

    errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=snapshot_client,
        target_node=AgentName.BENCHMARK_PLANNER,
        validation_scope=ValidationScope.CURRENT_NODE,
    )

    assert errors, "Expected the pre-solved benchmark planner seed to fail."
    assert any(
        error.artifact_path == "benchmark_plan.md"
        and "starter template version" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_planner_seed_rejects_presolved_engineering_plan():
    item = _seeded_planner_item(AgentName.ENGINEER_PLANNER, "ep-starter-drift")
    item = item.model_copy(
        update={
            "seed_files": {
                **(item.seed_files or {}),
                "engineering_plan.md": "# Engineering plan\n\nSolved output\n",
            }
        }
    )

    session_id = f"INT-STARTER-{uuid.uuid4().hex[:8]}"
    snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
    await materialize_seed_workspace_snapshot(
        item=item,
        session_id=session_id,
        agent_name=AgentName.ENGINEER_PLANNER,
        root=ROOT,
        workspace_client=snapshot_client,
        update_manifests=True,
    )

    errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=snapshot_client,
        target_node=AgentName.ENGINEER_PLANNER,
        validation_scope=ValidationScope.CURRENT_NODE,
    )

    assert errors, "Expected the pre-solved engineer planner seed to fail."
    assert any(
        error.artifact_path == "engineering_plan.md"
        and "starter template version" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_coder_seed_rejects_presolved_solution_script(
    tmp_path: Path,
):
    seed_item = load_seed_dataset(
        AgentName.ENGINEER_CODER,
        task_id="ec-002",
        limit=1,
        levels=None,
    )[0]
    temp_seed_dir = tmp_path / "engineer_coder_seed"
    shutil.copytree(seed_item.seed_artifact_dir, temp_seed_dir)
    temp_seed_dir.joinpath("solution_script.py").write_text(
        """from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def _make_box(
    label: str,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
):
    part = Box(*size, align=(Align.CENTER, Align.CENTER, Align.CENTER)).move(
        Location(center)
    )
    part.label = label
    part.metadata = PartMetadata(material_id="aluminum_6061", fixed=True)
    return part


def build():
    fixtures = Compound(
        children=[
            _make_box("fixture_box", (10.0, 10.0, 10.0), (0.0, 0.0, 5.0)),
        ]
    )
    fixtures.label = "solution_assembly"
    fixtures.metadata = CompoundMetadata()
    return fixtures


result = build()
""",
        encoding="utf-8",
    )
    item = seed_item.model_copy(update={"seed_artifact_dir": temp_seed_dir})

    session_id = f"INT-STARTER-{uuid.uuid4().hex[:8]}"
    snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
    await materialize_seed_workspace_snapshot(
        item=item,
        session_id=session_id,
        agent_name=AgentName.ENGINEER_CODER,
        root=ROOT,
        workspace_client=snapshot_client,
        update_manifests=True,
    )

    errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=snapshot_client,
        target_node=AgentName.ENGINEER_CODER,
        validation_scope=ValidationScope.CURRENT_NODE,
    )

    assert errors, "Expected the pre-solved engineer seed to fail."
    assert any(
        error.artifact_path == "solution_script.py"
        and "starter template version" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_coder_seed_requires_payload_trajectory_definition():
    seed_item = load_seed_dataset(
        AgentName.ENGINEER_CODER,
        task_id="ec-002",
        limit=1,
        levels=None,
    )[0]

    session_id = f"INT-STARTER-{uuid.uuid4().hex[:8]}"
    snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
    await materialize_seed_workspace_snapshot(
        item=seed_item,
        session_id=session_id,
        agent_name=AgentName.ENGINEER_CODER,
        root=ROOT,
        workspace_client=snapshot_client,
        update_manifests=True,
    )

    assert await snapshot_client.exists("payload_trajectory_definition.yaml")
    snapshot_client._files.pop("payload_trajectory_definition.yaml", None)

    errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=snapshot_client,
        target_node=AgentName.ENGINEER_CODER,
        validation_scope=ValidationScope.CURRENT_NODE,
    )

    assert errors, "Expected the engineer seed to fail when the payload file is absent."
    assert any(
        error.artifact_path == "payload_trajectory_definition.yaml"
        and "missing" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
def test_int_engineer_validate_engineering_rejects_invalid_payload_scaffold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    seed_item = load_seed_dataset(
        AgentName.ENGINEER_CODER,
        task_id="ec-002",
        limit=1,
        levels=None,
    )[0]
    temp_seed_dir = tmp_path / "engineer_coder_seed"
    shutil.copytree(seed_item.seed_artifact_dir, temp_seed_dir)
    temp_seed_dir.joinpath("solution_script.py").write_text(
        """from build123d import Box, BuildPart, Compound


def build() -> Compound:
    with BuildPart() as builder:
        Box(10, 10, 10)
    builder.part.label = "payload_validation_body"
    return Compound(children=[builder.part], label="payload_validation_root")
""",
        encoding="utf-8",
    )

    monkeypatch.chdir(temp_seed_dir)
    component = load_component_from_script(
        temp_seed_dir / "solution_script.py",
        session_root=temp_seed_dir,
    )

    validate_ok, validate_message = validate_engineering(component)

    assert not validate_ok, (
        "Expected the engineer validation helper to reject the scaffolded payload path."
    )
    assert validate_message is not None
    assert "payload_trajectory_definition" in validate_message


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_benchmark_coder_seed_rejects_presolved_benchmark_script(
    tmp_path: Path,
):
    seed_item = load_seed_dataset(
        AgentName.BENCHMARK_CODER,
        task_id="bc-002",
        limit=1,
        levels=None,
    )[0]
    temp_seed_dir = tmp_path / "benchmark_coder_seed"
    shutil.copytree(seed_item.seed_artifact_dir, temp_seed_dir)
    temp_seed_dir.joinpath("benchmark_script.py").write_text(
        """from build123d import Box, BuildPart, Compound


def build() -> Compound:
    with BuildPart() as builder:
        Box(10, 10, 10)
    return Compound(children=[builder.part], label="benchmark_assembly")


result = build()
""",
        encoding="utf-8",
    )
    item = seed_item.model_copy(update={"seed_artifact_dir": temp_seed_dir})

    session_id = f"INT-STARTER-{uuid.uuid4().hex[:8]}"
    snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
    await materialize_seed_workspace_snapshot(
        item=item,
        session_id=session_id,
        agent_name=AgentName.BENCHMARK_CODER,
        root=ROOT,
        workspace_client=snapshot_client,
        update_manifests=True,
    )

    errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=snapshot_client,
        target_node=AgentName.BENCHMARK_CODER,
        validation_scope=ValidationScope.CURRENT_NODE,
    )

    assert errors, "Expected the pre-solved benchmark seed to fail."
    assert any(
        error.artifact_path == "benchmark_script.py"
        and "starter template version" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_benchmark_reviewer_seed_rejects_presolved_todo(tmp_path: Path):
    seed_item = load_seed_dataset(
        AgentName.BENCHMARK_REVIEWER,
        task_id="br-001",
        limit=1,
        levels=None,
    )[0]
    temp_seed_dir = tmp_path / "benchmark_reviewer_seed"
    shutil.copytree(seed_item.seed_artifact_dir, temp_seed_dir)
    temp_seed_dir.joinpath("todo.md").write_text(
        "# TODO\n\n- [ ] Review the benchmark package\n",
        encoding="utf-8",
    )
    item = seed_item.model_copy(update={"seed_artifact_dir": temp_seed_dir})

    session_id = f"INT-STARTER-{uuid.uuid4().hex[:8]}"
    snapshot_client = InMemorySeedWorkspaceClient(session_id=session_id)
    await materialize_seed_workspace_snapshot(
        item=item,
        session_id=session_id,
        agent_name=AgentName.BENCHMARK_REVIEWER,
        root=ROOT,
        workspace_client=snapshot_client,
        update_manifests=True,
    )

    errors = await validate_seeded_workspace_handoff_artifacts(
        worker_client=snapshot_client,
        target_node=AgentName.BENCHMARK_REVIEWER,
        validation_scope=ValidationScope.CURRENT_NODE,
    )

    assert errors, "Expected the pre-solved benchmark reviewer seed to fail."
    assert any(
        error.artifact_path == "todo.md"
        and "starter template version" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_heavy_simulation_scope_replays_engineering_simulation(
    monkeypatch: pytest.MonkeyPatch,
):
    worker = InMemorySeedWorkspaceClient(session_id="scope-3")
    dummy_component = object()

    monkeypatch.setattr(
        "controller.agent.node_entry_validation.load_component_from_script",
        lambda **_: dummy_component,
    )
    monkeypatch.setattr(
        "controller.agent.node_entry_validation.validate_engineering",
        lambda *_, **__: (True, None),
    )
    monkeypatch.setattr(
        "controller.agent.node_entry_validation.simulate_engineering",
        lambda *_, **__: BenchmarkToolResponse(
            success=False,
            message="heavy simulation invoked",
        ),
    )

    scope2_errors = await _run_seed_validation_engineering_gate(
        worker_client=worker,
        gate_name="engineering coder validation",
        validation_scope=ValidationScope.CURRENT_AND_PREVIOUS_NODES,
        gate_role=AgentName.ENGINEER_CODER,
    )
    scope3_errors = await _run_seed_validation_engineering_gate(
        worker_client=worker,
        gate_name="engineering coder validation",
        validation_scope=ValidationScope.CURRENT_AND_PREVIOUS_NODES_WITH_HEAVY_SIMULATION,
        gate_role=AgentName.ENGINEER_CODER,
    )

    assert scope2_errors == []
    assert any(
        error.artifact_path == "simulation_result.json"
        and "heavy simulation invoked" in error.message
        for error in scope3_errors
    ), scope3_errors
