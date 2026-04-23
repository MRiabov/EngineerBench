import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import worker_heavy.utils.file_validation as file_validation
from controller.agent.node_entry_validation import (
    NodeEntryContract,
    ValidationGraph,
    ValidationScope,
    _run_seed_validation_engineering_gate,
    _validate_seeded_workspace_scope_gates,
    evaluate_node_entry_contract,
    validate_seeded_workspace_handoff_artifacts,
)
from controller.clients.worker import WorkerClient
from evals.logic.models import EvalDatasetItem
from evals.logic.specs import AGENT_SPECS
from evals.logic.workspace import (
    InMemorySeedWorkspaceClient,
    SeededEntryContractError,
    materialize_seed_workspace_snapshot,
    preflight_seeded_entry_contract,
)
from shared.agent_templates import load_role_template_files
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName
from shared.logging import get_logger
from shared.models.schemas import (
    AssemblyConstraints,
    AssemblyDefinition,
    BenchmarkDefinition,
    BenchmarkPartDefinition,
    BenchmarkPartMetadata,
    BoundingBox,
    CoarsePayloadTrajectory,
    Constraints,
    CostTotals,
    ObjectivesSection,
    Payload,
    PayloadTrajectoryAnchor,
    PayloadTrajectoryDefinition,
    PayloadTrajectoryPose,
    StaticRandomization,
)
from shared.script_contracts import (
    BENCHMARK_SCRIPT_PATH,
    SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH,
)
from shared.simulation.schemas import SimulatorBackendType
from shared.utils.agent import validate_engineering
from shared.workers.loader import load_component_from_script
from shared.workers.schema import BenchmarkToolResponse
from tests.integration.agent.helpers import dump_yaml_model

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DATASET_ROOT = (
    ROOT / "tests" / "integration" / "fixtures" / "codex_runner_mode" / "datasets"
)
ROLE_BASED_SEED_DATASET_ROOT = ROOT / "dataset" / "data" / "seed" / "role_based"

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
LOGGER = get_logger(__name__)

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _seeded_planner_item(agent_name: AgentName, item_id: str) -> EvalDatasetItem:
    return EvalDatasetItem(
        id=item_id,
        task=f"{agent_name.value} workspace contract smoke test",
        complexity_level=0,
        seed_dataset=None,
        seed_files=load_role_template_files(agent_name),
    )


def _load_fixture_seed_item(agent_name: AgentName, task_id: str) -> EvalDatasetItem:
    dataset_path = FIXTURE_DATASET_ROOT / f"{agent_name.value}.json"
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)

    rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    row = next((row for row in rows if row["id"] == task_id), None)
    if row is None:
        raise KeyError(f"Row {task_id!r} not found in {dataset_path}")
    seed_artifact_dir = row.get("seed_artifact_dir")
    if isinstance(seed_artifact_dir, str) and seed_artifact_dir:
        row = {
            **row,
            "seed_artifact_dir": str((ROOT / seed_artifact_dir).resolve()),
        }
    return EvalDatasetItem.model_validate(
        {
            **row,
            "seed_dataset": dataset_path.relative_to(ROOT),
        }
    )


def _load_role_based_seed_item(agent_name: AgentName, task_id: str) -> EvalDatasetItem:
    dataset_path = ROLE_BASED_SEED_DATASET_ROOT / f"{agent_name.value}.json"
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)

    rows = json.loads(dataset_path.read_text(encoding="utf-8"))
    row = next((row for row in rows if row["id"] == task_id), None)
    if row is None:
        raise KeyError(f"Row {task_id!r} not found in {dataset_path}")
    seed_artifact_dir = row.get("seed_artifact_dir")
    if isinstance(seed_artifact_dir, str) and seed_artifact_dir:
        row = {
            **row,
            "seed_artifact_dir": str((ROOT / seed_artifact_dir).resolve()),
        }
    return EvalDatasetItem.model_validate(
        {
            **row,
            "seed_dataset": dataset_path.relative_to(ROOT),
        }
    )


def _engineer_starter_assembly_definition() -> AssemblyDefinition:
    return AssemblyDefinition.model_validate(
        yaml.safe_load(
            load_role_template_files(AgentName.ENGINEER_PLANNER)[
                "assembly_definition.yaml"
            ]
        )
    )


def _cross_contract_benchmark_definition() -> BenchmarkDefinition:
    benchmark_definition = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(40.1, -10.0, -10.0), max_mm=(500.0, 10.0, 10.0)
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-10.0, -10.0, -10.0), max_mm=(500.0, 10.0, 10.0)
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
        simulation_bounds_mm=BoundingBox(
            min_mm=(-10.0, -10.0, -10.0),
            max_mm=(500.0, 10.0, 10.0),
        ),
        payload=Payload(
            label="payload_body",
            shape="cube",
            material_id="abs",
            static_randomization=StaticRandomization(radius_mm=(0.0, 0.0)),
            start_position_mm=(0.0, 0.0, 0.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=50.0, max_weight_g=980.0),
    )
    benchmark_definition.randomization.runtime_jitter_enabled = False
    benchmark_definition.randomization.static_variation_id = "cross_contract_drift"
    return benchmark_definition


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
            dump_yaml_model(
                BenchmarkDefinition(
                    objectives=ObjectivesSection(
                        goal_zone_mm=BoundingBox(
                            min_mm=(0.0, 0.0, 0.0),
                            max_mm=(1.0, 1.0, 1.0),
                        ),
                        forbid_zones=[],
                        build_zone_mm=BoundingBox(
                            min_mm=(0.0, 0.0, 0.0),
                            max_mm=(1.0, 1.0, 1.0),
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
                    simulation_bounds_mm=BoundingBox(
                        min_mm=(-1.0, -1.0, -1.0), max_mm=(2.0, 2.0, 2.0)
                    ),
                    payload=Payload(
                        label="benchmark_payload",
                        shape="cube",
                        material_id="abs",
                        start_position_mm=(0.0, 0.0, 0.0),
                        runtime_jitter_mm=(0.0, 0.0, 0.0),
                    ),
                    constraints=Constraints(
                        max_unit_cost=100.0,
                        max_weight_g=1000.0,
                    ),
                )
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "assembly_definition.yaml",
            dump_yaml_model(
                AssemblyDefinition(
                    version="1.0",
                    constraints=AssemblyConstraints(
                        benchmark_max_unit_cost_usd=100.0,
                        benchmark_max_weight_g=1000.0,
                        planner_target_max_unit_cost_usd=90.0,
                        planner_target_max_weight_g=900.0,
                    ),
                    manufactured_parts=[],
                    final_assembly=[],
                    totals=CostTotals(
                        estimated_unit_cost_usd=0.0,
                        estimated_weight_g=0.0,
                        estimate_confidence="high",
                    ),
                )
            ),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "benchmark_assembly_definition.yaml",
            dump_yaml_model(
                AssemblyDefinition(
                    version="1.0",
                    constraints=AssemblyConstraints(
                        benchmark_max_unit_cost_usd=100.0,
                        benchmark_max_weight_g=1000.0,
                        planner_target_max_unit_cost_usd=90.0,
                        planner_target_max_weight_g=900.0,
                    ),
                    manufactured_parts=[],
                    final_assembly=[],
                    totals=CostTotals(
                        estimated_unit_cost_usd=0.0,
                        estimated_weight_g=0.0,
                        estimate_confidence="high",
                    ),
                )
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
async def test_int_node_entry_rejects_missing_expected_render_bucket():
    session_id = f"INT-RENDER-BUCKETS-{uuid.uuid4().hex[:8]}"
    worker = InMemorySeedWorkspaceClient(session_id=session_id)
    try:
        await worker.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_REVIEWER),
            overwrite=True,
            bypass_agent_permissions=True,
        )

        result = await evaluate_node_entry_contract(
            contract=NodeEntryContract(node=AgentName.BENCHMARK_REVIEWER),
            state={"worker_client": worker, "session_id": session_id},
            artifact_exists=worker.exists,
            graph=ValidationGraph.BENCHMARK,
            integration_mode=True,
        )
    finally:
        await worker.aclose()

    assert not result.ok
    assert any(
        "renders/benchmark_renders missing" in error.message.lower()
        or "render_manifest.json missing" in error.message.lower()
        for error in result.errors
    ), result.errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_node_entry_rejects_stale_render_bundle_manifest():
    session_id = f"INT-RENDER-STALE-{uuid.uuid4().hex[:8]}"
    worker = InMemorySeedWorkspaceClient(session_id=session_id)
    try:
        await worker.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_REVIEWER),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "renders/benchmark_renders/render_manifest.json",
            '{"preview_evidence_paths":["renders/benchmark_renders/missing.png"],"artifacts":{}}',
            overwrite=True,
            bypass_agent_permissions=True,
        )

        result = await evaluate_node_entry_contract(
            contract=NodeEntryContract(node=AgentName.BENCHMARK_REVIEWER),
            state={"worker_client": worker, "session_id": session_id},
            artifact_exists=worker.exists,
            graph=ValidationGraph.BENCHMARK,
            integration_mode=True,
        )
    finally:
        await worker.aclose()

    assert not result.ok
    assert any(
        "render image 'renders/benchmark_renders/missing.png' is missing"
        in error.message.lower()
        for error in result.errors
    ), result.errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("manifest_content", "expected_fragment"),
    [
        (
            '{"preview_evidence_paths":["renders/engineer_plan_renders/cross_bucket.png"],'
            '"artifacts":{"renders/engineer_plan_renders/cross_bucket.png":'
            '{"modality":"rgb","group_key":"cross_bucket","siblings":{'
            '"rgb":"renders/engineer_plan_renders/cross_bucket.png",'
            '"depth":"renders/engineer_plan_renders/cross_bucket_depth.png",'
            '"segmentation":"renders/engineer_plan_renders/cross_bucket_segmentation.png"}}}}',
            "must stay within renders/benchmark_renders",
        ),
        ("{}", "contains no render images"),
    ],
)
async def test_int_node_entry_rejects_cross_bucket_or_empty_render_manifests(
    manifest_content: str,
    expected_fragment: str,
):
    session_id = f"INT-RENDER-BUCKET-BIND-{uuid.uuid4().hex[:8]}"
    worker = InMemorySeedWorkspaceClient(session_id=session_id)
    try:
        await worker.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_REVIEWER),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        if "cross_bucket.png" in manifest_content:
            await worker.write_file(
                "renders/engineer_plan_renders/cross_bucket.png",
                "not an image, just a path anchor",
                overwrite=True,
                bypass_agent_permissions=True,
            )
        await worker.write_file(
            "renders/benchmark_renders/render_manifest.json",
            manifest_content,
            overwrite=True,
            bypass_agent_permissions=True,
        )

        result = await evaluate_node_entry_contract(
            contract=NodeEntryContract(node=AgentName.BENCHMARK_REVIEWER),
            state={"worker_client": worker, "session_id": session_id},
            artifact_exists=worker.exists,
            graph=ValidationGraph.BENCHMARK,
            integration_mode=True,
        )
    finally:
        await worker.aclose()

    assert not result.ok
    assert any(expected_fragment in error.message.lower() for error in result.errors), (
        result.errors
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_node_entry_rejects_unexpected_render_buckets():
    session_id = f"INT-RENDER-EXTRA-{uuid.uuid4().hex[:8]}"
    worker = InMemorySeedWorkspaceClient(session_id=session_id)
    try:
        await worker.write_file(
            ".manifests/current_role.json",
            current_role_manifest_json(AgentName.BENCHMARK_REVIEWER),
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "renders/benchmark_renders/render_manifest.json",
            "{}",
            overwrite=True,
            bypass_agent_permissions=True,
        )
        await worker.write_file(
            "renders/engineer_plan_renders/render_manifest.json",
            "{}",
            overwrite=True,
            bypass_agent_permissions=True,
        )

        result = await evaluate_node_entry_contract(
            contract=NodeEntryContract(node=AgentName.BENCHMARK_REVIEWER),
            state={"worker_client": worker, "session_id": session_id},
            artifact_exists=worker.exists,
            graph=ValidationGraph.BENCHMARK,
            integration_mode=True,
        )
    finally:
        await worker.aclose()

    assert not result.ok
    assert any(
        "unexpected render bucket 'renders/engineer_plan_renders'"
        in error.message.lower()
        for error in result.errors
    ), result.errors


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
    assert any(error.artifact_path == "benchmark_plan.md" for error in errors), errors


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
    assert any(error.artifact_path == "engineering_plan.md" for error in errors), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_planner_seed_requires_benchmark_definition_under_scope():
    item = _load_role_based_seed_item(AgentName.ENGINEER_PLANNER, "ep-001")

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

    with pytest.raises(SeededEntryContractError) as excinfo:
        await preflight_seeded_entry_contract(
            item=item,
            session_id=session_id,
            agent_name=AgentName.ENGINEER_PLANNER,
            spec=AGENT_SPECS[AgentName.ENGINEER_PLANNER],
            root=ROOT,
            worker_light_url=WORKER_LIGHT_URL,
            logger=LOGGER,
            workspace_client=snapshot_client,
            validation_scope=ValidationScope.CURRENT_NODE,
        )

    report = excinfo.value.report
    assert any(
        error.artifact_path == "benchmark_definition.yaml"
        for error in report.entry_validation_result.errors
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_planner_seed_accepts_complete_handoff_under_scope():
    item = _load_role_based_seed_item(AgentName.ENGINEER_PLANNER, "ep-001")
    benchmark_definition_yaml = dump_yaml_model(_cross_contract_benchmark_definition())
    item = item.model_copy(
        update={
            "seed_files": {
                **(item.seed_files or {}),
                "benchmark_definition.yaml": benchmark_definition_yaml,
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

    await preflight_seeded_entry_contract(
        item=item,
        session_id=session_id,
        agent_name=AgentName.ENGINEER_PLANNER,
        spec=AGENT_SPECS[AgentName.ENGINEER_PLANNER],
        root=ROOT,
        worker_light_url=WORKER_LIGHT_URL,
        logger=LOGGER,
        workspace_client=snapshot_client,
        validation_scope=ValidationScope.CURRENT_NODE,
    )


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_plan_reviewer_seed_rejects_cross_contract_drift():
    item = _seeded_planner_item(AgentName.ENGINEER_PLANNER, "ep-cross-contract-drift")
    benchmark_definition = _cross_contract_benchmark_definition()
    benchmark_definition.constraints.max_unit_cost = 123.0
    benchmark_definition.constraints.max_weight_g = 456.0
    item = item.model_copy(
        update={
            "seed_files": {
                **(item.seed_files or {}),
                "benchmark_definition.yaml": dump_yaml_model(benchmark_definition),
                "benchmark_script.py": "print('benchmark script')\n",
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

    errors = await _validate_seeded_workspace_scope_gates(
        worker_client=snapshot_client,
        target_node=AgentName.ENGINEER_PLAN_REVIEWER,
        validation_scope=ValidationScope.CURRENT_AND_PREVIOUS_NODES,
    )

    assert errors, "Expected the cross-contract drift to fail at plan review."
    assert any(
        "benchmark_definition.constraints.max_unit_cost" in error.message
        or "engineering planner handoff" in error.message.lower()
        for error in errors
    ), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_coder_seed_rejects_presolved_solution_script(
    tmp_path: Path,
):
    seed_item = _load_fixture_seed_item(AgentName.ENGINEER_CODER, "ec-002")
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
    part.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)
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
    assert any(error.artifact_path == "solution_script.py" for error in errors), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_engineer_coder_seed_requires_payload_trajectory_definition():
    seed_item = _load_fixture_seed_item(AgentName.ENGINEER_CODER, "ec-002")

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
def test_int_engineer_coder_payload_path_samples_intermediate_segment(
    tmp_path: Path,
):
    workspace_root = tmp_path / "segment_sampling_workspace"
    workspace_root.mkdir()

    workspace_root.joinpath("benchmark_script.py").write_text(
        """from build123d import Align, Box, Compound, Location

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    fixed_block = Box(
        0.5, 0.5, 0.5, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    ).move(Location((10.25, 0.0, 0.0)))
    fixed_block.label = "fixed_block"
    fixed_block.metadata = PartMetadata(material_id="aluminum_6061", is_fixed=True)

    scene = Compound(children=[fixed_block])
    scene.label = "benchmark_scene"
    scene.metadata = CompoundMetadata()
    return scene


result = build()
""",
        encoding="utf-8",
    )

    workspace_root.joinpath("solution_script.py").write_text(
        """from build123d import Align, Box, Compound

from shared.models.schemas import CompoundMetadata, PartMetadata


def build() -> Compound:
    payload = Box(
        10, 10, 10, align=(Align.CENTER, Align.CENTER, Align.CENTER)
    )
    payload.label = "payload_body"
    payload.metadata = PartMetadata(material_id="abs", is_fixed=False)

    scene = Compound(children=[payload])
    scene.label = "solution_assembly"
    scene.metadata = CompoundMetadata()
    return scene


result = build()
""",
        encoding="utf-8",
    )

    benchmark_definition = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(
                min_mm=(40.1, -10.0, -10.0), max_mm=(500.0, 10.0, 10.0)
            ),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-10.0, -10.0, -10.0), max_mm=(500.0, 10.0, 10.0)
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
        simulation_bounds_mm=BoundingBox(
            min_mm=(-10.0, -10.0, -10.0),
            max_mm=(500.0, 10.0, 10.0),
        ),
        payload=Payload(
            label="payload_body",
            shape="cube",
            material_id="abs",
            static_randomization=StaticRandomization(radius_mm=(0.0, 0.0)),
            start_position_mm=(0.0, 0.0, 0.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=50.0, max_weight_g=980.0),
    )
    benchmark_definition.randomization.static_variation_id = (
        "segment_sampling_regression"
    )
    benchmark_definition.randomization.runtime_jitter_enabled = False
    benchmark_definition_text = dump_yaml_model(benchmark_definition)

    is_valid, benchmark_definition_or_errors = (
        file_validation.validate_benchmark_definition_yaml(benchmark_definition_text)
    )
    assert is_valid, benchmark_definition_or_errors
    benchmark_definition = benchmark_definition_or_errors

    payload_definition_text = dump_yaml_model(
        PayloadTrajectoryDefinition(
            backend=SimulatorBackendType.GENESIS,
            payload_part_names=["solution_assembly"],
            initial_pose=PayloadTrajectoryPose(
                reference_point="build_zone_start",
                pos_mm=(0.0, 0.0, 0.0),
                rot_deg=(0.0, 0.0, 0.0),
            ),
            sample_stride_s=0.3,
            anchors=[
                PayloadTrajectoryAnchor(
                    t_s=0.0,
                    reference_point="build_zone_start",
                    pos_mm=(0.0, 0.0, 0.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.0, 0.0, 0.0),
                    rotation_tolerance_deg=(0.1, 0.1, 0.1),
                    build_zone_valid=True,
                ),
                PayloadTrajectoryAnchor(
                    t_s=0.5,
                    reference_point="build_zone_start",
                    pos_mm=(270.05, 0.0, 0.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.0, 0.0, 0.0),
                    rotation_tolerance_deg=(0.1, 0.1, 0.1),
                    goal_zone_contact=True,
                ),
            ],
            terminal_event=None,
        )
    )

    is_valid, payload_result = (
        file_validation.validate_payload_trajectory_definition_yaml(
            payload_definition_text,
            benchmark_definition=benchmark_definition,
            expected_payload_part_names=["solution_assembly"],
            workspace_root=workspace_root,
            session_id="segment-sampling-regression",
        )
    )

    assert not is_valid, "Expected the segment sampler to reject the crossing path."
    assert any(
        "fixed geometry" in error or "intersects" in error or "goal_zone_mm" in error
        for error in payload_result
    ), payload_result


@pytest.mark.integration_p0
def test_int_engineer_payload_trajectory_rejects_points_above_spawn_height():
    benchmark_definition = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(-5.0, -5.0, -5.0), max_mm=(5.0, 5.0, 5.0)),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-10.0, -10.0, -10.0), max_mm=(10.0, 10.0, 10.0)
            ),
        ),
        benchmark_parts=[],
        simulation_bounds_mm=BoundingBox(
            min_mm=(-20.0, -20.0, -20.0),
            max_mm=(20.0, 20.0, 20.0),
        ),
        payload=Payload(
            label="payload",
            shape="sphere",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 0.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=50.0, max_weight_g=1000.0),
    )
    payload_definition_text = dump_yaml_model(
        PayloadTrajectoryDefinition(
            backend=SimulatorBackendType.GENESIS,
            payload_part_names=["solution_assembly"],
            initial_pose=PayloadTrajectoryPose(
                reference_point="build_zone_start",
                pos_mm=(0.0, 0.0, 0.0),
                rot_deg=(0.0, 0.0, 0.0),
            ),
            sample_stride_s=0.3,
            anchors=[
                PayloadTrajectoryAnchor(
                    t_s=0.0,
                    reference_point="build_zone_start",
                    pos_mm=(0.0, 0.0, 0.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.0, 0.0, 0.0),
                    rotation_tolerance_deg=(0.1, 0.1, 0.1),
                    build_zone_valid=True,
                ),
                PayloadTrajectoryAnchor(
                    t_s=0.5,
                    reference_point="mid_air",
                    pos_mm=(0.0, 0.0, 1.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.0, 0.0, 0.0),
                    rotation_tolerance_deg=(0.1, 0.1, 0.1),
                ),
                PayloadTrajectoryAnchor(
                    t_s=1.0,
                    reference_point="goal_zone_contact",
                    pos_mm=(0.0, 0.0, 0.0),
                    rot_deg=(0.0, 0.0, 0.0),
                    position_tolerance_mm=(0.0, 0.0, 0.0),
                    rotation_tolerance_deg=(0.1, 0.1, 0.1),
                    goal_zone_contact=True,
                ),
            ],
            terminal_event=None,
        )
    )

    is_valid, payload_result = (
        file_validation.validate_payload_trajectory_definition_yaml(
            payload_definition_text,
            benchmark_definition=benchmark_definition,
            expected_payload_part_names=["solution_assembly"],
            session_id="spawn-height-regression",
            validate_clearance=False,
        )
    )

    assert not is_valid
    assert any(
        "may not rise above benchmark_definition.payload.start_position_mm" in error
        for error in payload_result
    ), payload_result


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-276")
def test_int_engineer_planner_payload_clearance_validation_runs(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str | None] = []

    def fake_clearance(**kwargs):
        calls.append(kwargs.get("session_id"))
        return []

    def fake_benchmark_definition_yaml(content, session_id=None):
        return True, object()

    def fake_assembly_definition_yaml(
        content,
        session_id=None,
        manufacturing_config=None,
        exact_weight=False,
    ):
        return True, SimpleNamespace(coarse_payload_trajectory=None, payload_parts=[])

    monkeypatch.setattr(
        file_validation,
        "validate_benchmark_definition_yaml",
        fake_benchmark_definition_yaml,
    )
    monkeypatch.setattr(
        file_validation,
        "validate_assembly_definition_yaml",
        fake_assembly_definition_yaml,
    )
    monkeypatch.setattr(
        file_validation,
        "validate_planner_evidence_script_layout_contract",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        file_validation,
        "validate_plan_md_structure",
        lambda content, plan_type="benchmark", session_id=None, artifact_path=None: (
            True,
            [],
        ),
    )
    monkeypatch.setattr(
        file_validation,
        "validate_planner_handoff_cross_contract",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        file_validation,
        "validate_payload_trajectory_definition_yaml",
        lambda content, **kwargs: (True, object()),
    )
    monkeypatch.setattr(
        file_validation,
        "validate_payload_trajectory_swept_clearance",
        fake_clearance,
    )

    ok, errors = file_validation.validate_node_output(
        AgentName.ENGINEER_PLANNER,
        {
            "engineering_plan.md": (
                "# Engineering Plan\n\n"
                "## 1. Solution Overview\n"
                "- Outline\n\n"
                "## 2. Parts List\n"
                "- Part: payload_carrier\n\n"
                "## 3. Assembly Strategy\n"
                "- Assemble the payload carrier.\n\n"
                "## 4. Assumption Register\n"
                "- Assumption: none.\n\n"
                "## 5. Detailed Calculations\n"
                "- CALC-001\n\n"
                "## 6. Critical Constraints / Operating Envelope\n"
                "- Constraint: stay within bounds.\n\n"
                "## 7. Cost & Weight Budget\n"
                "- Budget: nominal.\n\n"
                "## 8. Risk Assessment\n"
                "- Risk: low.\n"
            ),
            "todo.md": "# TODO List\n\n- [ ] Build the handoff package\n",
            "benchmark_definition.yaml": dump_yaml_model(
                BenchmarkDefinition(
                    objectives=ObjectivesSection(
                        goal_zone_mm=BoundingBox(
                            min_mm=(-5.0, -5.0, -5.0), max_mm=(5.0, 5.0, 5.0)
                        ),
                        forbid_zones=[],
                        build_zone_mm=BoundingBox(
                            min_mm=(-10.0, -10.0, -10.0),
                            max_mm=(10.0, 10.0, 10.0),
                        ),
                    ),
                    benchmark_parts=[],
                    simulation_bounds_mm=BoundingBox(
                        min_mm=(-20.0, -20.0, -20.0),
                        max_mm=(20.0, 20.0, 20.0),
                    ),
                    payload=Payload(
                        label="payload",
                        shape="sphere",
                        material_id="aluminum_6061",
                        start_position_mm=(0.0, 0.0, 0.0),
                        runtime_jitter_mm=(0.0, 0.0, 0.0),
                    ),
                    constraints=Constraints(
                        max_unit_cost=50.0,
                        max_weight_g=1000.0,
                    ),
                )
            ),
            "assembly_definition.yaml": dump_yaml_model(
                AssemblyDefinition(
                    version="1.0",
                    constraints=AssemblyConstraints(
                        planner_target_max_unit_cost_usd=40.0,
                        planner_target_max_weight_g=900.0,
                    ),
                    manufactured_parts=[],
                    final_assembly=[],
                    totals=CostTotals(
                        estimated_unit_cost_usd=0.0,
                        estimated_weight_g=0.0,
                        estimate_confidence="high",
                    ),
                )
            ),
            "solution_plan_evidence_script.py": (
                "from build123d import Box\n\nresult = Box(1, 1, 1)\n"
            ),
            "payload_trajectory_definition.yaml": dump_yaml_model(
                PayloadTrajectoryDefinition(
                    backend=SimulatorBackendType.GENESIS,
                    payload_part_names=["solution_assembly"],
                    initial_pose=PayloadTrajectoryPose(
                        reference_point="build_zone_start",
                        pos_mm=(0.0, 0.0, 0.0),
                        rot_deg=(0.0, 0.0, 0.0),
                    ),
                    sample_stride_s=0.3,
                    anchors=[
                        PayloadTrajectoryAnchor(
                            t_s=0.0,
                            reference_point="build_zone_start",
                            pos_mm=(0.0, 0.0, 0.0),
                            rot_deg=(0.0, 0.0, 0.0),
                            position_tolerance_mm=(0.0, 0.0, 0.0),
                            rotation_tolerance_deg=(0.1, 0.1, 0.1),
                            build_zone_valid=True,
                        ),
                        PayloadTrajectoryAnchor(
                            t_s=0.5,
                            reference_point="goal_zone_contact",
                            pos_mm=(0.0, 0.0, 0.0),
                            rot_deg=(0.0, 0.0, 0.0),
                            position_tolerance_mm=(0.0, 0.0, 0.0),
                            rotation_tolerance_deg=(0.1, 0.1, 0.1),
                            goal_zone_contact=True,
                        ),
                    ],
                )
            ),
        },
        session_id="planner-clearance-test",
    )

    assert ok, errors
    assert errors == []
    assert calls == ["planner-clearance-test"], calls


@pytest.mark.integration_p0
@pytest.mark.int_id("INT-277")
def test_int_engineer_planner_payload_trajectory_clearance_validation_runs(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[dict[str, object]] = []

    def fake_clearance(**kwargs):
        calls.append(kwargs)
        return [
            "payload_trajectory_definition.yaml: planner coarse clearance violation"
        ]

    monkeypatch.setattr(
        file_validation,
        "validate_exact_planner_cost_contract",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        file_validation,
        "validate_payload_trajectory_swept_clearance",
        fake_clearance,
    )

    benchmark_definition = BenchmarkDefinition(
        objectives=ObjectivesSection(
            goal_zone_mm=BoundingBox(min_mm=(-5.0, -5.0, -5.0), max_mm=(5.0, 5.0, 5.0)),
            forbid_zones=[],
            build_zone_mm=BoundingBox(
                min_mm=(-10.0, -10.0, -10.0), max_mm=(10.0, 10.0, 10.0)
            ),
        ),
        benchmark_parts=[],
        simulation_bounds_mm=BoundingBox(
            min_mm=(-20.0, -20.0, -20.0),
            max_mm=(20.0, 20.0, 20.0),
        ),
        payload=Payload(
            label="payload",
            shape="sphere",
            material_id="aluminum_6061",
            start_position_mm=(0.0, 0.0, 0.0),
            runtime_jitter_mm=(0.0, 0.0, 0.0),
        ),
        constraints=Constraints(max_unit_cost=50.0, max_weight_g=1000.0),
    )
    coarse_payload_trajectory = CoarsePayloadTrajectory(
        payload_part_names=["solution_assembly"],
        sample_stride_s=0.2,
        anchors=[
            PayloadTrajectoryAnchor(
                t_s=0.0,
                reference_point="build_zone_start",
                pos_mm=(0.0, 0.0, 0.0),
                rot_deg=(0.0, 0.0, 0.0),
                position_tolerance_mm=(0.0, 0.0, 0.0),
                rotation_tolerance_deg=(0.1, 0.1, 0.1),
                build_zone_valid=True,
            ),
            PayloadTrajectoryAnchor(
                t_s=0.5,
                reference_point="goal_zone_entry",
                pos_mm=(0.0, 0.0, 0.0),
                rot_deg=(0.0, 0.0, 0.0),
                position_tolerance_mm=(0.0, 0.0, 0.0),
                rotation_tolerance_deg=(0.1, 0.1, 0.1),
                goal_zone_contact=True,
            ),
        ],
    )
    assembly_definition = AssemblyDefinition(
        version="1.0",
        constraints=AssemblyConstraints(
            planner_target_max_unit_cost_usd=40.0,
            planner_target_max_weight_g=900.0,
        ),
        manufactured_parts=[],
        coarse_payload_trajectory=coarse_payload_trajectory,
        final_assembly=[],
        totals=CostTotals(
            estimated_unit_cost_usd=10.0,
            estimated_weight_g=100.0,
            estimate_confidence="high",
        ),
    )

    errors = file_validation.validate_planner_handoff_cross_contract(
        benchmark_definition=benchmark_definition,
        assembly_definition=assembly_definition,
        manufacturing_config=SimpleNamespace(),
        planner_node_type=AgentName.ENGINEER_PLANNER,
        files_content_map={
            BENCHMARK_SCRIPT_PATH: (
                "from build123d import Box\n\nresult = Box(1, 1, 1)\n"
            ),
            SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH: (
                "from build123d import Box\n\nresult = Box(1, 1, 1)\n"
            ),
        },
        session_id="planner-clearance-test",
    )

    assert errors == [
        "assembly_definition.yaml.coarse_payload_trajectory: planner coarse clearance violation"
    ], errors
    assert len(calls) == 1, calls
    assert calls[0]["moving_script_path"] == SOLUTION_PLAN_EVIDENCE_SCRIPT_PATH, calls
    assert calls[0]["session_id"] == "planner-clearance-test", calls


@pytest.mark.integration_p0
def test_int_engineer_validate_engineering_rejects_invalid_payload_scaffold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    seed_item = _load_fixture_seed_item(AgentName.ENGINEER_CODER, "ec-002")
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
    seed_item = _load_fixture_seed_item(AgentName.BENCHMARK_CODER, "bc-002")
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
    assert any(error.artifact_path == "benchmark_script.py" for error in errors), errors


@pytest.mark.integration_p0
@pytest.mark.asyncio
async def test_int_benchmark_reviewer_seed_rejects_presolved_todo(tmp_path: Path):
    seed_item = _load_fixture_seed_item(AgentName.BENCHMARK_REVIEWER, "br-001")
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
    assert any(error.artifact_path == "todo.md" for error in errors), errors


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
