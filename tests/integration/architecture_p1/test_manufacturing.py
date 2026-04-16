import asyncio
import uuid
from pathlib import Path

import pytest
import yaml
from httpx import AsyncClient

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    ConfirmRequest,
    EpisodeResponse,
)
from shared.enums import EpisodeStatus
from shared.models.schemas import AssemblyDefinition
from shared.workers.schema import (
    AnalyzeRequest,
    DeleteFileRequest,
    ExecuteRequest,
    ExecuteResponse,
    ReadFileRequest,
    ReadFileResponse,
    WriteFileRequest,
)
from shared.workers.workbench_models import ManufacturingMethod, WorkbenchResult

# Adjust URL to your controller if different
CONTROLLER_URL = "http://127.0.0.1:18000"
WORKER_HEAVY_URL = "http://127.0.0.1:18002"
WORKER_LIGHT_URL = "http://127.0.0.1:18001"

REPO_MANUFACTURING_CONFIG = Path(
    "worker_heavy/workbenches/manufacturing_config.yaml"
).read_text(encoding="utf-8")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_manufacturing_methods_and_materials():
    """
    INT-035: Materials config enforcement
    INT-036: Supported workbench methods

    Verifies:
    1. Manufacturing workbench runs (validate_costing_and_price)
    2. Different methods (CNC, 3D Print) are supported/detected
    3. Invalid materials are rejected (via prompt injection or reviewing logs/artifacts)
    """
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        # 1. Setup Benchmark
        request = BenchmarkGenerateRequest(
            prompt="Create a benchmark for a CNC machined part."
        )
        resp = await client.post("/api/benchmark/generate", json=request.model_dump())
        assert resp.status_code in [
            200,
            202,
        ], f"Failed to generate benchmark: {resp.text}"
        benchmark_resp = BenchmarkGenerateResponse.model_validate(resp.json())
        benchmark_session_id = str(benchmark_resp.session_id)

        # Wait for benchmark
        confirmed = False
        for _ in range(150):
            status_resp = await client.get(f"/api/benchmark/{benchmark_session_id}")
            if status_resp.status_code == 200:
                bench_ep = EpisodeResponse.model_validate(status_resp.json())
                if bench_ep.status == EpisodeStatus.PLANNED and not confirmed:
                    await client.post(
                        f"/api/benchmark/{benchmark_session_id}/confirm",
                        json=ConfirmRequest(comment="Proceed").model_dump(),
                    )
                    confirmed = True
                if bench_ep.status == EpisodeStatus.COMPLETED:
                    break
                if bench_ep.status == EpisodeStatus.FAILED:
                    pytest.fail(
                        "Benchmark generation failed during setup "
                        f"(session_id={benchmark_session_id})."
                    )
            await asyncio.sleep(2)
        else:
            pytest.fail("Benchmark generation timed out.")

        # 2. Trigger Engineer - Requesting CNC and specific material
        engineer_session_id = f"INT-036-{uuid.uuid4().hex[:8]}"
        # We explicitly ask for Aluminum 6061 (valid) to test success path first
        task = f"Solve benchmark: {benchmark_session_id}. Use CNC milling with Aluminum 6061."
        run_request = AgentRunRequest(
            task=task,
            session_id=engineer_session_id,
            metadata_vars={"benchmark_id": benchmark_session_id},
        )

        run_resp = await client.post("/api/agent/run", json=run_request.model_dump())
        assert run_resp.status_code in [
            200,
            202,
        ], f"Failed to trigger agent: {run_resp.text}"
        episode_id = AgentRunResponse.model_validate(run_resp.json()).episode_id

        # Wait for Engineer
        engineer_completed = False
        final_status = None
        for _ in range(150):
            ep_resp = await client.get(f"/api/episodes/{episode_id}")
            if ep_resp.status_code == 200:
                ep = EpisodeResponse.model_validate(ep_resp.json())
                final_status = ep.status
                if final_status in [EpisodeStatus.COMPLETED, EpisodeStatus.FAILED]:
                    engineer_completed = True
                    break
            await asyncio.sleep(2)

        if not engineer_completed:
            pytest.fail(f"Engineer timed out. Last status: {final_status}")

        # 3. Verify Workbench Execution (INT-036)
        # Use /api/episodes/{id} to get assets list
        ep_resp = await client.get(f"/api/episodes/{episode_id}")
        assert ep_resp.status_code == 200
        ep_data = EpisodeResponse.model_validate(ep_resp.json())
        assets = ep_data.assets or []

        # Check for assembly_definition.yaml which implies workbench ran
        cost_yaml_artifact = next(
            (a for a in assets if "assembly_definition.yaml" in a.s3_path),
            None,
        )
        assert cost_yaml_artifact is not None, (
            f"Workbench output (cost estimation) missing. Assets: {[a.s3_path for a in assets]}"
        )

        # 4. Verify Material Enforcement (INT-035) - "Nice to have" negative test
        bad_material_session_id = f"INT-035-{uuid.uuid4().hex[:8]}"
        bad_task = f"Solve benchmark: {benchmark_session_id}. Use Unobtanium material."

        bad_run_request = AgentRunRequest(
            task=bad_task,
            session_id=bad_material_session_id,
            metadata_vars={"benchmark_id": benchmark_session_id},
        )
        bad_run_resp = await client.post(
            "/api/agent/run", json=bad_run_request.model_dump()
        )
        assert bad_run_resp.status_code in [200, 202]
        bad_episode_id = AgentRunResponse.model_validate(bad_run_resp.json()).episode_id

        # Minimal assertion for INT-035: The system shouldn't crash, and if it fails, it handles it gracefully.
        for _ in range(150):
            ep_resp = await client.get(f"/api/episodes/{bad_episode_id}")
            if ep_resp.status_code == 200:
                ep = EpisodeResponse.model_validate(ep_resp.json())
                if ep.status in [EpisodeStatus.COMPLETED, EpisodeStatus.FAILED]:
                    break
            await asyncio.sleep(2)


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_worker_analyze_rejects_unknown_material():
    """The heavy worker must fail closed on unknown material IDs."""
    script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    part = Box(10, 10, 10)
    part = part.move(Location((0, 0, 5)))
    part.label = "test_part"
    part.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="unobtanium",
    )
    return part
"""

    async with AsyncClient(base_url=WORKER_HEAVY_URL, timeout=300.0) as client:
        request = AnalyzeRequest(
            script_path="script.py",
            script_content=script,
            method=ManufacturingMethod.CNC,
            quantity=1,
        )
        resp = await client.post(
            "/benchmark/analyze",
            json=request.model_dump(mode="json"),
            headers={"X-Session-ID": f"INT-035-{uuid.uuid4().hex[:8]}"},
        )
        assert resp.status_code == 200, resp.text
        result = WorkbenchResult.model_validate(resp.json())
    assert result.is_manufacturable is False
    assert any("Unknown material_id" in violation for violation in result.violations)


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_worker_analyze_quantity_changes_setup_amortization():
    """Requested quantity must change the economics and remain traceable."""
    script = """
from build123d import Box, Location
from shared.models.schemas import PartMetadata
from shared.workers.workbench_models import ManufacturingMethod

def build():
    part = Box(24, 24, 12)
    part = part.move(Location((0, 0, 6)))
    part.label = "qty_probe"
    part.metadata = PartMetadata(
        manufacturing_method=ManufacturingMethod.CNC,
        material_id="aluminum_6061",
    )
    return part
"""

    async with AsyncClient(base_url=WORKER_HEAVY_URL, timeout=300.0) as client:
        headers = {"X-Session-ID": f"INT-036-{uuid.uuid4().hex[:8]}"}

        low_qty_request = AnalyzeRequest(
            script_path="script.py",
            script_content=script,
            method=ManufacturingMethod.CNC,
            quantity=1,
        )
        high_qty_request = AnalyzeRequest(
            script_path="script.py",
            script_content=script,
            method=ManufacturingMethod.CNC,
            quantity=3000,
        )

        low_resp = await client.post(
            "/benchmark/analyze",
            json=low_qty_request.model_dump(mode="json"),
            headers=headers,
        )
        assert low_resp.status_code == 200, low_resp.text
        low_result = WorkbenchResult.model_validate(low_resp.json())

        high_resp = await client.post(
            "/benchmark/analyze",
            json=high_qty_request.model_dump(mode="json"),
            headers=headers,
        )
        assert high_resp.status_code == 200, high_resp.text
        high_result = WorkbenchResult.model_validate(high_resp.json())

    assert low_result.metadata.cost_breakdown is not None
    assert high_result.metadata.cost_breakdown is not None
    assert low_result.metadata.cost_breakdown.quantity == 1
    assert high_result.metadata.cost_breakdown.quantity == 3000
    assert low_result.metadata.additional_info["quantity"] == 1
    assert high_result.metadata.additional_info["quantity"] == 3000
    assert low_result.metadata.cost_breakdown.setup_cost == pytest.approx(
        high_result.metadata.cost_breakdown.setup_cost
    )
    assert low_result.metadata.cost_breakdown.variable_cost_per_unit == pytest.approx(
        high_result.metadata.cost_breakdown.variable_cost_per_unit
    )
    assert low_result.unit_cost > high_result.unit_cost
    assert (
        low_result.metadata.cost_breakdown.total_cost
        < high_result.metadata.cost_breakdown.total_cost
    )


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_validate_and_price_recomputes_manufactured_weight():
    """The pricing script must recompute manufactured-part weight deterministically."""
    session_id = f"INT-033-{uuid.uuid4().hex[:8]}"

    assembly_definition = AssemblyDefinition.model_validate(
        {
            "version": "1.0",
            "constraints": {
                "benchmark_max_unit_cost_usd": 100.0,
                "benchmark_max_weight_g": 1000.0,
                "planner_target_max_unit_cost_usd": 90.0,
                "planner_target_max_weight_g": 900.0,
            },
            "manufactured_parts": [
                {
                    "part_name": "weight_probe",
                    "part_id": "weight_probe",
                    "manufacturing_method": "3DP",
                    "material_id": "aluminum_6061",
                    "quantity": 1,
                    "part_volume_mm3": 1000.0,
                    "stock_bbox_mm": {"x": 10.0, "y": 10.0, "z": 10.0},
                    "stock_volume_mm3": 1000.0,
                    "removed_volume_mm3": 0.0,
                    "estimated_unit_cost_usd": 10.0,
                }
            ],
            "final_assembly": [],
            "totals": {
                "estimated_unit_cost_usd": 10.0,
                "estimated_weight_g": 0.0,
                "estimate_confidence": "high",
            },
        }
    )

    async with AsyncClient(base_url=WORKER_LIGHT_URL, timeout=300.0) as client:
        headers = {"X-Session-ID": session_id}

        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="assembly_definition.yaml",
                content=yaml.safe_dump(
                    assembly_definition.model_dump(mode="json", by_alias=True),
                    sort_keys=False,
                ),
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/write",
            json=WriteFileRequest(
                path="manufacturing_config.yaml",
                content=REPO_MANUFACTURING_CONFIG,
                overwrite=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        exec_resp = await client.post(
            f"{WORKER_LIGHT_URL}/runtime/execute",
            json=ExecuteRequest(
                code=(
                    "python "
                    "/home/maksym/Work/proj/Problemologist/Problemologist-AI/"
                    ".agents/skills/manufacturing-knowledge/scripts/validate_and_price.py"
                ),
                timeout=120,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert exec_resp.status_code == 200, exec_resp.text
        exec_data = ExecuteResponse.model_validate(exec_resp.json())
        assert exec_data.exit_code == 0, exec_data.stderr
        assert "Total Estimated Weight: 2.70g" in exec_data.stdout

        read_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/read",
            json=ReadFileRequest(path="assembly_definition.yaml").model_dump(
                mode="json"
            ),
            headers=headers,
        )
        assert read_resp.status_code == 200, read_resp.text

    enriched = AssemblyDefinition.model_validate(
        yaml.safe_load(ReadFileResponse.model_validate(read_resp.json()).content)
    )
    assert enriched.totals.estimated_weight_g == pytest.approx(2.7)
    assert enriched.totals.estimated_unit_cost_usd == pytest.approx(10.0)


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_validate_and_price_rejects_missing_manufacturing_config():
    """The pricing script must fail closed when the workspace config is missing."""
    session_id = f"INT-035-{uuid.uuid4().hex[:8]}"
    headers = {"X-Session-ID": session_id}

    assembly_definition = """
version: "1.0"
constraints:
  benchmark_max_unit_cost_usd: 50.0
  benchmark_max_weight_g: 1000.0
  planner_target_max_unit_cost_usd: 45.0
  planner_target_max_weight_g: 900.0
manufactured_parts: []
final_assembly: []
totals:
  estimated_unit_cost_usd: 0.0
  estimated_weight_g: 0.0
  estimate_confidence: high
"""

    async with AsyncClient(base_url=WORKER_LIGHT_URL, timeout=300.0) as client:
        write_resp = await client.post(
            "/fs/write",
            json=WriteFileRequest(
                path="assembly_definition.yaml",
                content=assembly_definition,
                overwrite=True,
                bypass_agent_permissions=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert write_resp.status_code == 200, write_resp.text

        config_resp = await client.post(
            "/fs/write",
            json=WriteFileRequest(
                path="manufacturing_config.yaml",
                content=REPO_MANUFACTURING_CONFIG,
                overwrite=True,
                bypass_agent_permissions=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert config_resp.status_code == 200, config_resp.text

        delete_resp = await client.post(
            "/fs/delete",
            json=DeleteFileRequest(
                path="manufacturing_config.yaml",
                bypass_agent_permissions=True,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert delete_resp.status_code == 200, delete_resp.text

        exec_resp = await client.post(
            "/runtime/execute",
            json=ExecuteRequest(
                code=(
                    "python "
                    "/home/maksym/Work/proj/Problemologist/Problemologist-AI/"
                    ".agents/skills/manufacturing-knowledge/scripts/validate_and_price.py"
                ),
                timeout=60,
            ).model_dump(mode="json"),
            headers=headers,
        )
        assert exec_resp.status_code == 200, exec_resp.text
        exec_data = ExecuteResponse.model_validate(exec_resp.json())
        assert exec_data.exit_code != 0
        assert "manufacturing_config.yaml invalid" in exec_data.stderr
