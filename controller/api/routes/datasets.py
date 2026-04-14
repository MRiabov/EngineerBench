from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import uuid
from pathlib import Path

import boto3
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from controller.api.schemas import (
    DatasetExportRequest,
    DatasetExportResponse,
    ObjectStoragePointer,
)
from controller.persistence.db import get_db
from controller.persistence.models import (
    Asset,
    BenchmarkAsset,
    DatasetRowArchive,
    Episode,
    Trace,
)
from shared.enums import EpisodeStatus, EpisodeType, ResponseStatus
from shared.models.schemas import (
    DatasetRowArchiveManifest,
    DatasetRowArtifactReference,
    DatasetRowBenchmarkAsset,
    DatasetRowLineage,
    EpisodeMetadata,
    TraceMetadata,
)
from shared.script_contracts import BENCHMARK_SCRIPT_PATH, SOLUTION_SCRIPT_PATH
from shared.workers.schema import RenderManifest, ReviewManifest

router = APIRouter(prefix="/datasets", tags=["datasets"])

_ASSET_BUCKET = os.getenv("ASSET_S3_BUCKET", "problemologist")
_S3_ENDPOINT = os.getenv("S3_ENDPOINT")
_S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
_S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
_EXPORT_PREFIX = "dataset-exports"
_REVIEW_ROUND_RE = re.compile(
    r"^(?P<prefix>reviews/.+-round-)(?P<round>\d+)(?P<suffix>\.yaml)$"
)

_ALLOWED_EXACT_FILES = {
    "benchmark_plan.md",
    "engineering_plan.md",
    "todo.md",
    "journal.md",
    "script.py",
    SOLUTION_SCRIPT_PATH,
    BENCHMARK_SCRIPT_PATH,
    "assembly_definition.yaml",
    "benchmark_definition.yaml",
    "benchmark_assembly_definition.yaml",
    "validation_results.json",
    "simulation_result.json",
    "plan_refusal.md",
}

_ALLOWED_TEXT_SUFFIXES = (
    ".json",
    ".md",
    ".py",
    ".yaml",
    ".yml",
    ".xml",
    ".mjcf",
    ".txt",
    ".step",
    ".stp",
)

_ALLOWED_BINARY_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".obj",
    ".stl",
    ".glb",
)

_REVISION_MANIFEST_PRIORITY = (
    "renders/benchmark_renders/render_manifest.json",
    "renders/engineer_plan_renders/render_manifest.json",
    "renders/final_solution_submission_renders/render_manifest.json",
    ".manifests/benchmark_review_manifest.json",
    ".manifests/engineering_execution_handoff_manifest.json",
    ".manifests/engineering_plan_review_manifest.json",
    ".manifests/benchmark_plan_review_manifest.json",
)


def _get_s3_client():
    if not (_S3_ENDPOINT and _S3_ACCESS_KEY and _S3_SECRET_KEY):
        raise HTTPException(
            status_code=500,
            detail="S3 configuration missing for dataset export",
        )
    return boto3.client(
        "s3",
        endpoint_url=_S3_ENDPOINT,
        aws_access_key_id=_S3_ACCESS_KEY,
        aws_secret_access_key=_S3_SECRET_KEY,
        region_name="us-east-1",
    )


def _normalize_path(path: str) -> str:
    return Path(path).as_posix().lstrip("/")


def _should_include_asset(path: str) -> bool:
    normalized = _normalize_path(path)
    if not normalized:
        return False
    if normalized == "plan.md":
        return False
    if normalized.startswith(("renders/", "reviews/", ".manifests/")):
        return True
    if normalized in _ALLOWED_EXACT_FILES:
        return True
    if normalized.endswith(_ALLOWED_TEXT_SUFFIXES):
        return True
    if normalized.endswith(_ALLOWED_BINARY_SUFFIXES):
        return True
    return False


def _asset_family(path: str) -> str:
    normalized = _normalize_path(path)
    if normalized.startswith("renders/"):
        if normalized.endswith("render_manifest.json"):
            return "render_manifest"
        return "render_media"
    if normalized.startswith("reviews/"):
        match = _REVIEW_ROUND_RE.match(normalized)
        if match:
            return match.group("prefix").removeprefix("reviews/")
        return "review_yaml"
    if normalized.startswith(".manifests/"):
        return "review_manifest"
    if normalized.endswith("plan.md"):
        return "plan"
    if normalized.endswith("todo.md"):
        return "todo"
    if normalized.endswith("journal.md"):
        return "journal"
    if normalized.endswith("script.py"):
        return "implementation"
    if normalized.endswith("assembly_definition.yaml"):
        return "assembly_definition"
    if normalized.endswith("benchmark_assembly_definition.yaml"):
        return "benchmark_assembly_definition"
    if normalized.endswith("benchmark_definition.yaml"):
        return "benchmark_definition"
    if normalized.endswith("validation_results.json"):
        return "validation_results"
    if normalized.endswith("simulation_result.json"):
        return "simulation_result"
    if normalized.endswith("plan_refusal.md"):
        return "plan_refusal"
    return "other"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _asset_bytes(asset: Asset, *, s3_client, bucket: str) -> bytes:
    if asset.content is not None:
        return asset.content.encode("utf-8")

    normalized = _normalize_path(asset.s3_path)
    try:
        return s3_client.get_object(Bucket=bucket, Key=normalized)["Body"].read()
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"failed to read persisted artifact {normalized}: {exc}",
        ) from exc


async def _load_episode(db: AsyncSession, episode_id: uuid.UUID) -> Episode | None:
    stmt = (
        select(Episode)
        .where(Episode.id == episode_id)
        .options(selectinload(Episode.assets), selectinload(Episode.traces))
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def _select_latest_assets(assets: list[Asset]) -> list[Asset]:
    latest_by_family: dict[str, Asset] = {}
    latest_round_by_family: dict[str, tuple[int, Asset]] = {}

    for asset in sorted(assets, key=lambda item: (item.created_at, item.id)):
        path = _normalize_path(asset.s3_path)
        if not _should_include_asset(path):
            continue

        match = _REVIEW_ROUND_RE.match(path)
        if match:
            family = match.group("prefix").removeprefix("reviews/")
            round_index = int(match.group("round"))
            current = latest_round_by_family.get(family)
            if current is None or round_index >= current[0]:
                latest_round_by_family[family] = (round_index, asset)
            continue

        latest_by_family[path] = asset

    selected: list[Asset] = list(latest_by_family.values())
    selected.extend(asset for _, asset in latest_round_by_family.values())
    selected.sort(key=lambda item: (_asset_family(item.s3_path), item.s3_path))
    return selected


def _missing_required_artifacts(
    *,
    episode_type: EpisodeType,
    selected_assets: list[Asset],
) -> list[str]:
    selected_paths = {_normalize_path(asset.s3_path) for asset in selected_assets}

    def _has(prefix_or_path: str) -> bool:
        if prefix_or_path.endswith("/"):
            return any(path.startswith(prefix_or_path) for path in selected_paths)
        return any(
            path == prefix_or_path
            or path.endswith(f"/{prefix_or_path}")
            or path.endswith(prefix_or_path)
            for path in selected_paths
        )

    if episode_type == EpisodeType.BENCHMARK:
        required = [
            "benchmark_plan.md",
            "todo.md",
            "journal.md",
            BENCHMARK_SCRIPT_PATH,
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "validation_results.json",
            "simulation_result.json",
            ".manifests/benchmark_plan_review_manifest.json",
            ".manifests/benchmark_review_manifest.json",
        ]
        review_prefixes = [
            "reviews/benchmark-plan-review-decision-round-",
            "reviews/benchmark-plan-review-comments-round-",
            "reviews/benchmark-execution-review-decision-round-",
            "reviews/benchmark-execution-review-comments-round-",
        ]
    else:
        required = [
            "engineering_plan.md",
            "todo.md",
            "journal.md",
            SOLUTION_SCRIPT_PATH,
            "assembly_definition.yaml",
            "benchmark_definition.yaml",
            "benchmark_assembly_definition.yaml",
            "validation_results.json",
            "simulation_result.json",
            ".manifests/benchmark_review_manifest.json",
            ".manifests/benchmark_plan_review_manifest.json",
            ".manifests/engineering_plan_review_manifest.json",
            ".manifests/engineering_execution_handoff_manifest.json",
        ]
        review_prefixes = [
            "reviews/engineering-plan-review-decision-round-",
            "reviews/engineering-plan-review-comments-round-",
            "reviews/engineering-execution-review-decision-round-",
            "reviews/engineering-execution-review-comments-round-",
        ]

    missing: list[str] = [path for path in required if not _has(path)]
    for prefix in review_prefixes:
        if not any(path.startswith(prefix) for path in selected_paths):
            missing.append(prefix)
    render_bundle_manifest_paths = sorted(
        {
            str(Path(path).parent / "render_manifest.json")
            for path in selected_paths
            if path.startswith("renders/")
            and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".mp4"}
        }
    )
    for manifest_path in render_bundle_manifest_paths:
        if not _has(manifest_path):
            missing.append(manifest_path)
    return missing


def _benchmark_asset_manifest(
    benchmark_asset: BenchmarkAsset,
) -> DatasetRowBenchmarkAsset:
    random_variants = benchmark_asset.random_variants or []
    if isinstance(random_variants, dict):
        random_variants = list(random_variants.values())
    return DatasetRowBenchmarkAsset(
        benchmark_id=str(benchmark_asset.benchmark_id),
        mjcf_url=benchmark_asset.mjcf_url,
        build123d_url=benchmark_asset.build123d_url,
        preview_bundle_url=benchmark_asset.preview_bundle_url,
        random_variants=[str(variant) for variant in random_variants],
        difficulty_score=benchmark_asset.difficulty_score,
        benchmark_metadata=benchmark_asset.benchmark_metadata or {},
    )


def _trace_metadata_lookup(traces: list[Trace], field_name: str) -> str | None:
    for trace in sorted(traces, key=lambda item: item.id, reverse=True):
        metadata = TraceMetadata.model_validate(trace.metadata_vars or {})
        value = getattr(metadata, field_name)
        if value:
            return str(value)
        trace_value = getattr(trace, field_name, None)
        if trace_value:
            return str(trace_value)
    return None


def _collect_revision_markers(
    *,
    s3_client,
    bucket: str,
    selected_assets: list[Asset],
) -> tuple[str, dict[str, str]]:
    revisions: dict[str, str] = {}
    candidate_paths = [
        path
        for path in _REVISION_MANIFEST_PRIORITY
        if path in {_normalize_path(asset.s3_path) for asset in selected_assets}
    ]

    def _extract_manifest_revision(manifest: object) -> str | None:
        for field_name in ("revision", "benchmark_revision", "solution_revision"):
            value = getattr(manifest, field_name, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    for candidate_path in candidate_paths:
        candidate_asset = next(
            (
                asset
                for asset in selected_assets
                if _normalize_path(asset.s3_path) == candidate_path
            ),
            None,
        )
        if candidate_asset is None:
            continue

        try:
            payload = _asset_bytes(candidate_asset, s3_client=s3_client, bucket=bucket)
        except HTTPException:
            continue

        if candidate_path.endswith("render_manifest.json"):
            manifest = RenderManifest.model_validate_json(payload)
            manifest_revision = _extract_manifest_revision(manifest)
            if manifest_revision:
                revisions[candidate_path] = manifest_revision
        else:
            try:
                manifest = ReviewManifest.model_validate_json(payload)
            except Exception:
                continue
            manifest_revision = _extract_manifest_revision(manifest)
            if manifest_revision:
                revisions[candidate_path] = manifest_revision

    if not revisions:
        raise HTTPException(
            status_code=422,
            detail="dataset export requires a revision-bearing review or render manifest",
        )

    unique_revisions = {revision.strip() for revision in revisions.values() if revision}
    if len(unique_revisions) != 1:
        raise HTTPException(
            status_code=422,
            detail=f"stale or cross-revision manifests detected: {sorted(unique_revisions)}",
        )

    return unique_revisions.pop(), revisions


def _source_artifact_hash(
    *, revision: str, artifact_refs: list[DatasetRowArtifactReference]
) -> str:
    payload = {
        "revision": revision,
        "artifacts": [
            {
                "path": ref.path,
                "family": ref.family,
                "sha256": ref.sha256,
                "size_bytes": ref.size_bytes,
            }
            for ref in sorted(artifact_refs, key=lambda item: item.path)
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _archive_members(
    *,
    archive_manifest: DatasetRowArchiveManifest,
    selected_assets: list[Asset],
    s3_client,
    bucket: str,
) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(mode="w:gz", fileobj=buffer) as archive:
        for asset in selected_assets:
            path = _normalize_path(asset.s3_path)
            body = _asset_bytes(asset, s3_client=s3_client, bucket=bucket)

            info = tarfile.TarInfo(name=path)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))

        manifest_bytes = archive_manifest.model_dump_json(
            by_alias=True, exclude_none=False, indent=2
        ).encode("utf-8")
        manifest_info = tarfile.TarInfo(name="dataset_row_manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))

    buffer.seek(0)
    return buffer.read()


async def _materialize_dataset_export(
    db: AsyncSession, episode_id: uuid.UUID
) -> DatasetExportResponse:
    episode = await _load_episode(db, episode_id)
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    if episode.status != EpisodeStatus.COMPLETED:
        raise HTTPException(
            status_code=422,
            detail=f"episode must be completed before export, found {episode.status}",
        )

    metadata = EpisodeMetadata.model_validate(episode.metadata_vars or {})
    if metadata.episode_type is None:
        raise HTTPException(
            status_code=422,
            detail="episode metadata is missing episode_type",
        )

    source_benchmark_id = (metadata.benchmark_id or "").strip()
    if metadata.episode_type == EpisodeType.BENCHMARK and not source_benchmark_id:
        source_benchmark_id = str(episode.id)
    if not source_benchmark_id:
        raise HTTPException(
            status_code=422,
            detail="dataset export requires benchmark_id lineage",
        )

    try:
        benchmark_uuid = uuid.UUID(source_benchmark_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"benchmark_id must be a valid UUID: {source_benchmark_id}",
        ) from exc

    benchmark_asset = await db.get(BenchmarkAsset, benchmark_uuid)
    if benchmark_asset is None:
        raise HTTPException(
            status_code=422,
            detail=f"benchmark asset record missing for benchmark_id={source_benchmark_id}",
        )

    selected_assets = _select_latest_assets(list(episode.assets))
    if not selected_assets:
        raise HTTPException(
            status_code=422,
            detail="dataset export requires persisted artifacts",
        )

    missing_artifacts = _missing_required_artifacts(
        episode_type=metadata.episode_type,
        selected_assets=selected_assets,
    )
    if missing_artifacts:
        raise HTTPException(
            status_code=422,
            detail=f"dataset export missing required artifact families: {sorted(missing_artifacts)}",
        )

    s3_client = _get_s3_client()
    revision_hash, _ = _collect_revision_markers(
        s3_client=s3_client,
        bucket=_ASSET_BUCKET,
        selected_assets=selected_assets,
    )

    artifact_refs: list[DatasetRowArtifactReference] = []
    for asset in selected_assets:
        normalized = _normalize_path(asset.s3_path)
        payload = _asset_bytes(asset, s3_client=s3_client, bucket=_ASSET_BUCKET)
        artifact_refs.append(
            DatasetRowArtifactReference(
                path=normalized,
                family=_asset_family(normalized),
                asset_type=asset.asset_type,
                source_surface="episode_assets",
                sha256=_sha256_bytes(payload),
                size_bytes=len(payload),
            )
        )

    source_artifact_hash = _source_artifact_hash(
        revision=revision_hash, artifact_refs=artifact_refs
    )

    simulation_run_id = _trace_metadata_lookup(
        list(episode.traces), "simulation_run_id"
    )
    cots_query_id = _trace_metadata_lookup(list(episode.traces), "cots_query_id")
    review_id = _trace_metadata_lookup(list(episode.traces), "review_id")
    if not review_id:
        raise HTTPException(
            status_code=422,
            detail="dataset export requires review_id lineage",
        )

    lineage = DatasetRowLineage(
        episode_id=str(episode.id),
        benchmark_id=str(benchmark_uuid),
        user_session_id=str(episode.user_session_id)
        if episode.user_session_id
        else None,
        worker_session_id=metadata.worker_session_id,
        episode_type=metadata.episode_type,
        seed_id=metadata.seed_id,
        seed_dataset=metadata.seed_dataset,
        seed_match_method=metadata.seed_match_method,
        generation_kind=metadata.generation_kind,
        parent_seed_id=metadata.parent_seed_id,
        is_integration_test=metadata.is_integration_test,
        integration_test_id=metadata.integration_test_id,
        simulation_run_id=simulation_run_id,
        cots_query_id=cots_query_id,
        review_id=review_id,
        revision_hash=revision_hash,
        artifact_hash=source_artifact_hash,
    )

    benchmark_asset_manifest = _benchmark_asset_manifest(benchmark_asset)
    validation_notes = [
        f"selected_latest_assets={len(selected_assets)}",
        f"benchmark_asset_record={benchmark_asset_manifest.benchmark_id}",
    ]
    manifest = DatasetRowArchiveManifest(
        export_id=str(uuid.uuid4()),
        created_at=episode.updated_at,
        lineage=lineage,
        source_benchmark_asset=benchmark_asset_manifest,
        artifact_references=artifact_refs,
        artifact_families=sorted({ref.family for ref in artifact_refs}),
        validation_notes=validation_notes,
    )

    archive_bytes = _archive_members(
        archive_manifest=manifest,
        selected_assets=selected_assets,
        s3_client=s3_client,
        bucket=_ASSET_BUCKET,
    )
    archive_sha256 = _sha256_bytes(archive_bytes)
    manifest_bytes = manifest.model_dump_json(
        by_alias=True, exclude_none=False, indent=2
    ).encode("utf-8")
    manifest_sha256 = _sha256_bytes(manifest_bytes)

    export_id = uuid.UUID(manifest.export_id)
    archive_key = f"{_EXPORT_PREFIX}/{export_id}/dataset-row.tar.gz"
    manifest_key = f"{_EXPORT_PREFIX}/{export_id}/dataset-row-manifest.json"

    try:
        s3_client.put_object(
            Bucket=_ASSET_BUCKET,
            Key=archive_key,
            Body=archive_bytes,
            ContentType="application/gzip",
        )
        s3_client.put_object(
            Bucket=_ASSET_BUCKET,
            Key=manifest_key,
            Body=manifest_bytes,
            ContentType="application/json",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"failed to persist dataset export artifacts: {exc}",
        ) from exc

    record = DatasetRowArchive(
        id=export_id,
        episode_id=episode.id,
        user_session_id=episode.user_session_id,
        worker_session_id=metadata.worker_session_id,
        benchmark_id=benchmark_uuid,
        episode_type=metadata.episode_type,
        seed_id=metadata.seed_id,
        seed_dataset=metadata.seed_dataset,
        seed_match_method=metadata.seed_match_method,
        generation_kind=metadata.generation_kind,
        parent_seed_id=metadata.parent_seed_id,
        is_integration_test=metadata.is_integration_test,
        integration_test_id=metadata.integration_test_id,
        simulation_run_id=simulation_run_id,
        cots_query_id=cots_query_id,
        review_id=review_id,
        revision_hash=revision_hash,
        artifact_hash=source_artifact_hash,
        archive_bucket=_ASSET_BUCKET,
        archive_key=archive_key,
        archive_sha256=archive_sha256,
        archive_size_bytes=len(archive_bytes),
        manifest_bucket=_ASSET_BUCKET,
        manifest_key=manifest_key,
        manifest_sha256=manifest_sha256,
        manifest_size_bytes=len(manifest_bytes),
    )
    db.add(record)
    await db.commit()

    return DatasetExportResponse(
        status=ResponseStatus.COMPLETED,
        message="Dataset export materialized",
        export_id=export_id,
        episode_id=episode.id,
        archive=ObjectStoragePointer(
            bucket=_ASSET_BUCKET,
            key=archive_key,
            sha256=archive_sha256,
            size_bytes=len(archive_bytes),
        ),
        manifest=manifest,
    )


@router.post("/export", response_model=DatasetExportResponse)
async def export_dataset(
    request: DatasetExportRequest,
    db: AsyncSession = Depends(get_db),
):
    return await _materialize_dataset_export(db, request.episode_id)


@router.post("/{episode_id}/export", response_model=DatasetExportResponse)
async def export_dataset_for_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    return await _materialize_dataset_export(db, episode_id)


@router.get("/exports/{export_id}", response_model=DatasetExportResponse)
async def get_dataset_export(
    export_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(DatasetRowArchive, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Dataset export not found")

    s3_client = _get_s3_client()
    try:
        manifest_raw = s3_client.get_object(
            Bucket=record.manifest_bucket, Key=record.manifest_key
        )["Body"].read()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"dataset export manifest missing from object storage: {exc}",
        ) from exc

    manifest = DatasetRowArchiveManifest.model_validate_json(manifest_raw)
    return DatasetExportResponse(
        status=ResponseStatus.COMPLETED,
        message="Dataset export materialized",
        export_id=record.id,
        episode_id=record.episode_id,
        archive=ObjectStoragePointer(
            bucket=record.archive_bucket,
            key=record.archive_key,
            sha256=record.archive_sha256,
            size_bytes=record.archive_size_bytes,
        ),
        manifest=manifest,
    )


@router.get("/episodes/{episode_id}", response_model=DatasetExportResponse)
async def get_dataset_export_by_episode(
    episode_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(DatasetRowArchive)
        .where(DatasetRowArchive.episode_id == episode_id)
        .order_by(DatasetRowArchive.created_at.desc(), DatasetRowArchive.id.desc())
    )
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="Dataset export not found")

    s3_client = _get_s3_client()
    manifest_raw = s3_client.get_object(
        Bucket=record.manifest_bucket, Key=record.manifest_key
    )["Body"].read()
    manifest = DatasetRowArchiveManifest.model_validate_json(manifest_raw)
    return DatasetExportResponse(
        status=ResponseStatus.COMPLETED,
        message="Dataset export materialized",
        export_id=record.id,
        episode_id=record.episode_id,
        archive=ObjectStoragePointer(
            bucket=record.archive_bucket,
            key=record.archive_key,
            sha256=record.archive_sha256,
            size_bytes=record.archive_size_bytes,
        ),
        manifest=manifest,
    )
