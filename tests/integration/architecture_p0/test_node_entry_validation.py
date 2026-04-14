import os
import uuid

import pytest

from controller.agent.node_entry_validation import (
    validate_seeded_workspace_handoff_artifacts,
)
from controller.clients.worker import WorkerClient
from shared.current_role import current_role_manifest_json
from shared.enums import AgentName

WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


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
                    "cots_parts": [],
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
                    "cots_parts": [],
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
