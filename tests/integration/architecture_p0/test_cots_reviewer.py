import os
import uuid

import httpx
import pytest
from pydantic import TypeAdapter

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    CotsSearchItem,
    EpisodeResponse,
    ReviewResponse,
)
from shared.workers.schema import FsFileEntry

# Constants
WORKER_LIGHT_URL = os.getenv("WORKER_LIGHT_URL", "http://127.0.0.1:18001")
WORKER_HEAVY_URL = os.getenv("WORKER_HEAVY_URL", "http://127.0.0.1:18002")
CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")


@pytest.fixture
def session_id():
    return f"INT-012-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def base_headers(session_id):
    return {"X-Session-ID": session_id}


@pytest.mark.integration_p0
@pytest.mark.asyncio
@pytest.mark.int_id("INT-012")
async def test_int_012_013_cots_search_contract_and_readonly(session_id, base_headers):
    """INT-012, INT-013: Verify COTS search output contract and read-only behavior."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        before_ls_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/ls", json={"path": "."}, headers=base_headers
        )
        assert before_ls_resp.status_code == 200
        before_entries = {
            FsFileEntry.model_validate(entry).path for entry in before_ls_resp.json()
        }

        # COTS subagent or tool is usually invoked via a runtime script or endpoint.
        # Let's test via the COTS indexer/search endpoint if available,
        # or via a subagent call if the controller exposes it.

        # Scenario: Query for a common part
        query = "M3 screw"
        resp = await client.get(f"{CONTROLLER_URL}/cots/search", params={"q": query})

        assert resp.status_code == 200
        search_results = TypeAdapter(list[CotsSearchItem]).validate_python(resp.json())
        assert isinstance(search_results, list)

        if len(search_results) > 0:
            part = search_results[0]
            # INT-013: Required fields — validate via model
            assert part.part_id is not None
            assert part.manufacturer is not None
            assert part.price is not None
            assert part.source is not None

        # INT-012: Read-only check
        # Verify that the query path did not mutate the session workspace.
        ls_resp = await client.post(
            f"{WORKER_LIGHT_URL}/fs/ls", json={"path": "."}, headers=base_headers
        )
        assert ls_resp.status_code == 200
        after_entries = {
            FsFileEntry.model_validate(entry).path for entry in ls_resp.json()
        }
        assert after_entries == before_entries


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "review_frontmatter_validation_error",
        "node_entry_validation_rejected",
        "missing_artifact",
        "reviewer_entry_blocked",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-016")
async def test_int_016_reviewer_decision_schema_gate(
    session_id, base_headers, controller_client, worker_heavy_client
):
    """INT-016: Verify reviewer rejects malformed frontmatter decisions."""
    # Use controller_client fixture
    client = controller_client

    # Create a real episode first
    session_id = f"INT-016-{uuid.uuid4().hex[:8]}"
    req = AgentRunRequest(task="Test Review Schema", session_id=session_id)
    run_resp = await client.post(
        "/agent/run",
        json=req.model_dump(mode="json"),
    )
    assert run_resp.status_code == 202
    episode_id = AgentRunResponse.model_validate(run_resp.json()).episode_id

    # Scenario: Post a review with invalid 'decision' value
    malformed_review = """---
decision: MOCK_DECISION
evidence:
  files_checked: ["solution.py"]
---
This should be rejected.
"""
    # Reviewer output usually goes to a specific path or endpoint
    resp = await client.post(
        f"/episodes/{episode_id}/review",
        json={"review_content": malformed_review},
    )

    if resp.status_code == 404:
        # Fallback: Maybe it's a worker-side tool?
        # Use worker_heavy_client
        resp = await worker_heavy_client.post(
            "/benchmark/review",
            json={"content": malformed_review},
            headers=base_headers,
        )

    assert resp.status_code in [400, 422]
    assert "decision" in resp.text.lower()


@pytest.mark.integration_p0
@pytest.mark.allow_backend_errors(
    regexes=[
        "node_entry_validation_rejected",
        "missing_artifact",
        "reviewer_entry_blocked",
    ]
)
@pytest.mark.asyncio
@pytest.mark.int_id("INT-017")
async def test_int_017_plan_refusal_loop(session_id, base_headers, controller_client):
    """INT-017: Verify plan refusal loop (rejection leads to FAILED state)."""
    # Use controller_client fixture
    client = controller_client

    # 1. Start agent run
    session_id = f"INT-017-{uuid.uuid4().hex[:8]}"
    req = AgentRunRequest(task="Test Refusal Loop", session_id=session_id)
    run_resp = await client.post(
        "/agent/run",
        json=req.model_dump(mode="json"),
    )
    assert run_resp.status_code == 202
    episode_id = AgentRunResponse.model_validate(run_resp.json()).episode_id

    # 2. Inject a 'rejected' decision via review endpoint
    # We need a valid review payload
    review_content = """---
decision: rejected
comments: ["Not good enough"]
evidence:
  files_checked: ["engineering_plan.md"]
  stability_summary:
    batchWidth: 1
    successCount: 0
    successRate: 0.0
    isConsistent: false
    sceneBuildCount: 1
    backendRunCount: 1
    batchedExecution: false
    sceneSummaries: []
  stability_summary_source: validation_results.json
---
Refusing this plan.
"""
    resp = await client.post(
        f"/episodes/{episode_id}/review",
        json={"review_content": review_content},
    )
    assert resp.status_code == 200
    review_resp = ReviewResponse.model_validate(resp.json())
    assert review_resp.status == "success"
    assert review_resp.decision == "rejected"

    # 3. Verify the agent/episode status is FAILED
    # (Architecture might eventually require a loop/retry, but current impl fails it)
    status_resp = await client.get(f"/episodes/{episode_id}")
    assert status_resp.status_code == 200
    ep_data = EpisodeResponse.model_validate(status_resp.json())
    assert ep_data.status.value == "FAILED"
