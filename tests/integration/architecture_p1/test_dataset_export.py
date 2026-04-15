import os
import uuid
from pathlib import Path

import boto3
import pytest
from httpx import AsyncClient

from controller.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    BenchmarkGenerateRequest,
    BenchmarkGenerateResponse,
    ConfirmRequest,
    DatasetExportRequest,
    DatasetExportResponse,
    EpisodeCreateResponse,
    EpisodeResponse,
)
from shared.enums import EpisodeStatus
from shared.models.schemas import DatasetRowArchiveManifest
from shared.simulation.schemas import SimulatorBackendType
from tests.integration.agent.helpers import (
    wait_for_benchmark_state,
    wait_for_episode_terminal,
)

CONTROLLER_URL = os.getenv("CONTROLLER_URL", "http://127.0.0.1:18000")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://127.0.0.1:19000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin")
ASSET_BUCKET = os.getenv("ASSET_S3_BUCKET", "problemologist")

pytestmark = pytest.mark.xdist_group(name="physics_sims")


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
    )


async def _wait_for_benchmark_completion(
    client: AsyncClient, session_id: str
) -> tuple[BenchmarkGenerateResponse, EpisodeResponse]:
    benchmark_resp = BenchmarkGenerateResponse.model_validate(
        {
            "status": "accepted",
            "message": "Benchmark generation started",
            "session_id": session_id,
            "episode_id": session_id,
        }
    )

    planned_episode = EpisodeResponse.model_validate(
        await wait_for_benchmark_state(
            client,
            session_id,
            timeout_s=150.0,
            terminal_statuses={
                EpisodeStatus.PLANNED,
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
                EpisodeStatus.CANCELLED,
            },
        )
    )
    if planned_episode.status == EpisodeStatus.FAILED:
        pytest.fail(f"Benchmark generation failed for session {session_id}")

    if planned_episode.status == EpisodeStatus.PLANNED:
        confirm_resp = await client.post(
            f"/benchmark/{session_id}/confirm",
            json=ConfirmRequest(comment="Proceed").model_dump(),
        )
        assert confirm_resp.status_code == 200, confirm_resp.text
        planned_episode = EpisodeResponse.model_validate(
            await wait_for_benchmark_state(
                client,
                session_id,
                timeout_s=150.0,
                terminal_statuses={
                    EpisodeStatus.COMPLETED,
                    EpisodeStatus.FAILED,
                    EpisodeStatus.CANCELLED,
                },
            )
        )

    if planned_episode.status == EpisodeStatus.FAILED:
        pytest.fail(f"Benchmark generation failed for session {session_id}")

    return benchmark_resp, planned_episode


async def _wait_for_episode_terminal(
    client: AsyncClient, episode_id: str
) -> EpisodeResponse:
    return EpisodeResponse.model_validate(
        await wait_for_episode_terminal(
            client,
            episode_id,
            timeout_s=180.0,
            terminal_statuses={
                EpisodeStatus.COMPLETED,
                EpisodeStatus.FAILED,
                EpisodeStatus.CANCELLED,
            },
        )
    )


def _approve_review_content() -> str:
    return """---
decision: approved
comments:
  - Approved for dataset export coverage.
evidence:
  files_checked:
    - benchmark_plan.md
---
Approved.
"""


def _assert_manifest_contains(
    manifest: DatasetRowArchiveManifest, required_paths: list[str]
) -> None:
    artifact_paths = [Path(ref.path) for ref in manifest.artifact_references]
    assert len(artifact_paths) == len(set(artifact_paths)), artifact_paths
    for required_path in required_paths:
        assert any(path == Path(required_path) for path in artifact_paths), (
            f"Missing {required_path}. Paths: {artifact_paths}"
        )


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_dataset_export_benchmark_row_round_trip():
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        benchmark_request = BenchmarkGenerateRequest(
            prompt="Create a simple benchmark for dataset export coverage.",
            backend=SimulatorBackendType.GENESIS,
        )
        resp = await client.post(
            "/benchmark/generate", json=benchmark_request.model_dump()
        )
        assert resp.status_code in (200, 202), resp.text
        benchmark_session_id = str(
            BenchmarkGenerateResponse.model_validate(resp.json()).session_id
        )

        benchmark_create, benchmark_episode = await _wait_for_benchmark_completion(
            client, benchmark_session_id
        )

        export_resp = await client.post(
            "/api/datasets/export",
            json=DatasetExportRequest(
                episode_id=benchmark_create.episode_id
            ).model_dump(mode="json"),
        )
        assert export_resp.status_code == 200, export_resp.text
        export_data = DatasetExportResponse.model_validate(export_resp.json())

        get_resp = await client.get(f"/api/datasets/exports/{export_data.export_id}")
        assert get_resp.status_code == 200, get_resp.text
        loaded_export = DatasetExportResponse.model_validate(get_resp.json())
        assert loaded_export == export_data

        manifest = export_data.manifest
        assert manifest.lineage.episode_type == "benchmark"
        assert manifest.lineage.episode_id == str(benchmark_create.episode_id)
        assert manifest.lineage.benchmark_id == str(benchmark_create.episode_id)
        assert manifest.lineage.worker_session_id is not None
        assert manifest.lineage.revision_hash
        assert manifest.lineage.artifact_hash
        assert manifest.lineage.review_id is not None

        _assert_manifest_contains(
            manifest,
            [
                "benchmark_plan.md",
                "todo.md",
                "journal.md",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
                "renders/render_manifest.json",
            ],
        )
        assert any(
            Path(ref.path).parent.name == "renders" and Path(ref.path).suffix == ".png"
            for ref in manifest.artifact_references
        ), [ref.path for ref in manifest.artifact_references]
        assert any(
            ref.path.startswith("reviews/") for ref in manifest.artifact_references
        )
        assert any(
            ref.path.startswith(".manifests/") for ref in manifest.artifact_references
        )

        s3 = _s3_client()
        archive_head = s3.head_object(
            Bucket=export_data.archive.bucket, Key=export_data.archive.key
        )
        assert archive_head["ContentLength"] == export_data.archive.size_bytes

        manifest_head = s3.head_object(
            Bucket=export_data.archive.bucket,
            Key=f"dataset-exports/{export_data.export_id}/dataset-row-manifest.json",
        )
        assert manifest_head["ContentLength"] > 0
        manifest_body = s3.get_object(
            Bucket=export_data.archive.bucket,
            Key=f"dataset-exports/{export_data.export_id}/dataset-row-manifest.json",
        )["Body"].read()
        manifest_from_store = DatasetRowArchiveManifest.model_validate_json(
            manifest_body
        )
        assert manifest_from_store == manifest

        assert benchmark_episode.status == EpisodeStatus.COMPLETED


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_dataset_export_solution_row_round_trip():
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=300.0) as client:
        benchmark_request = BenchmarkGenerateRequest(
            prompt="Create a simple benchmark for solution export coverage.",
            backend=SimulatorBackendType.GENESIS,
        )
        resp = await client.post(
            "/benchmark/generate", json=benchmark_request.model_dump()
        )
        assert resp.status_code in (200, 202), resp.text
        benchmark_session_id = str(
            BenchmarkGenerateResponse.model_validate(resp.json()).session_id
        )
        benchmark_create, _ = await _wait_for_benchmark_completion(
            client, benchmark_session_id
        )

        engineer_session_id = f"INT-016-{uuid.uuid4().hex[:8]}"
        run_request = AgentRunRequest(
            task=f"Solve benchmark: {benchmark_session_id}",
            session_id=engineer_session_id,
            metadata_vars={"benchmark_id": str(benchmark_create.episode_id)},
        )
        run_resp = await client.post("/api/agent/run", json=run_request.model_dump())
        assert run_resp.status_code in (200, 202), run_resp.text
        engineer_episode_id = str(
            AgentRunResponse.model_validate(run_resp.json()).episode_id
        )

        engineer_episode = await _wait_for_episode_terminal(client, engineer_episode_id)
        assert engineer_episode.status == EpisodeStatus.COMPLETED, engineer_episode

        export_resp = await client.post(
            "/api/datasets/export",
            json=DatasetExportRequest(
                episode_id=uuid.UUID(engineer_episode_id)
            ).model_dump(mode="json"),
        )
        assert export_resp.status_code == 200, export_resp.text
        export_data = DatasetExportResponse.model_validate(export_resp.json())
        manifest = export_data.manifest

        assert manifest.lineage.episode_type == "engineer"
        assert manifest.lineage.episode_id == engineer_episode_id
        assert manifest.lineage.benchmark_id == str(benchmark_create.episode_id)
        assert manifest.lineage.worker_session_id == engineer_session_id
        assert manifest.lineage.review_id is not None
        assert manifest.lineage.revision_hash
        assert manifest.lineage.artifact_hash
        assert manifest.lineage.simulation_run_id is not None

        _assert_manifest_contains(
            manifest,
            [
                "engineering_plan.md",
                "todo.md",
                "journal.md",
                "script.py",
                "assembly_definition.yaml",
                "benchmark_definition.yaml",
                "benchmark_assembly_definition.yaml",
            ],
        )
        assert any(
            Path(ref.path) == Path("validation_results.json")
            for ref in manifest.artifact_references
        )
        assert any(
            Path(ref.path) == Path("simulation_result.json")
            for ref in manifest.artifact_references
        )
        assert any(
            Path(ref.path) == Path("renders/render_manifest.json")
            for ref in manifest.artifact_references
        )
        assert any(
            ref.path.startswith("reviews/") for ref in manifest.artifact_references
        )
        assert any(
            ref.path.startswith(".manifests/") for ref in manifest.artifact_references
        )

        s3 = _s3_client()
        archive_head = s3.head_object(
            Bucket=export_data.archive.bucket, Key=export_data.archive.key
        )
        assert archive_head["ContentLength"] == export_data.archive.size_bytes

        manifest_body = s3.get_object(
            Bucket=export_data.archive.bucket,
            Key=f"dataset-exports/{export_data.export_id}/dataset-row-manifest.json",
        )["Body"].read()
        manifest_from_store = DatasetRowArchiveManifest.model_validate_json(
            manifest_body
        )
        assert manifest_from_store == manifest


@pytest.mark.integration_p1
@pytest.mark.asyncio
async def test_dataset_export_invalid_lineage_fails_closed():
    async with AsyncClient(base_url=CONTROLLER_URL, timeout=120.0) as client:
        session_id = f"INT-EXPORT-BAD-{uuid.uuid4().hex[:8]}"
        create_resp = await client.post(
            "/api/test/episodes",
            json={
                "task": "Invalid lineage export test",
                "session_id": session_id,
                "metadata_vars": {
                    "episode_type": "benchmark",
                    "benchmark_id": "not-a-uuid",
                },
                "agent_name": "engineer_coder",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        episode_id = EpisodeCreateResponse.model_validate(create_resp.json()).episode_id

        review_resp = await client.post(
            f"/api/episodes/{episode_id}/review",
            json={"review_content": _approve_review_content()},
        )
        assert review_resp.status_code == 200, review_resp.text

        export_resp = await client.post(
            "/api/datasets/export",
            json=DatasetExportRequest(episode_id=episode_id).model_dump(mode="json"),
        )
        assert export_resp.status_code == 422, export_resp.text
        assert "benchmark_id" in export_resp.text

        lookup_resp = await client.get(f"/api/datasets/episodes/{episode_id}")
        assert lookup_resp.status_code == 404, lookup_resp.text
