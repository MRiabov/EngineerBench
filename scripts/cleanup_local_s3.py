#!/usr/bin/env python3
"""Purge local MinIO buckets before integration or eval runs."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import boto3
import structlog
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.ops.backup import get_s3_config

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class S3CleanupTarget:
    bucket_name: str


_DEFAULT_BUCKETS = (
    ("ASSET_S3_BUCKET", "problemologist"),
    ("BACKUP_S3_BUCKET", "problemologist-backup"),
    ("BENCHMARK_SOURCE_BUCKET", "benchmarks-source"),
    ("BENCHMARK_ASSETS_BUCKET", "benchmarks-assets"),
)


def _resolve_cleanup_targets() -> list[S3CleanupTarget]:
    seen: set[str] = set()
    targets: list[S3CleanupTarget] = []
    for env_var, default_bucket in _DEFAULT_BUCKETS:
        bucket_name = os.getenv(env_var, default_bucket).strip()
        if not bucket_name or bucket_name in seen:
            continue
        seen.add(bucket_name)
        targets.append(S3CleanupTarget(bucket_name=bucket_name))
    return targets


def _is_missing_bucket_error(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    code = str(error.get("Code") or "").strip()
    return code in {"NoSuchBucket", "404", "NotFound", "NoSuchKey"}


def _bucket_exists(client, bucket_name: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as exc:
        if _is_missing_bucket_error(exc):
            return False
        raise


def _delete_objects(client, bucket_name: str, objects: list[dict[str, str]]) -> int:
    deleted = 0
    for start in range(0, len(objects), 1000):
        chunk = objects[start : start + 1000]
        if not chunk:
            continue
        response = client.delete_objects(
            Bucket=bucket_name, Delete={"Objects": chunk, "Quiet": True}
        )
        deleted += len(chunk)
        if response.get("Errors"):
            errors = response["Errors"]
            raise RuntimeError(
                f"Failed to delete some objects from {bucket_name}: {errors}"
            )
    return deleted


def _purge_current_objects(client, bucket_name: str) -> int:
    paginator = client.get_paginator("list_objects_v2")
    keys: list[dict[str, str]] = []
    for page in paginator.paginate(Bucket=bucket_name):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if isinstance(key, str) and key:
                keys.append({"Key": key})
    if not keys:
        return 0
    return _delete_objects(client, bucket_name, keys)


def _purge_versioned_objects(client, bucket_name: str) -> int:
    paginator = client.get_paginator("list_object_versions")
    versioned: list[dict[str, str]] = []
    for page in paginator.paginate(Bucket=bucket_name):
        for item in page.get("Versions", []):
            key = item.get("Key")
            version_id = item.get("VersionId")
            if (
                isinstance(key, str)
                and key
                and isinstance(version_id, str)
                and version_id
            ):
                versioned.append({"Key": key, "VersionId": version_id})
        for item in page.get("DeleteMarkers", []):
            key = item.get("Key")
            version_id = item.get("VersionId")
            if (
                isinstance(key, str)
                and key
                and isinstance(version_id, str)
                and version_id
            ):
                versioned.append({"Key": key, "VersionId": version_id})
    if not versioned:
        return 0
    return _delete_objects(client, bucket_name, versioned)


def _abort_multipart_uploads(client, bucket_name: str) -> int:
    paginator = client.get_paginator("list_multipart_uploads")
    aborted = 0
    try:
        for page in paginator.paginate(Bucket=bucket_name):
            for upload in page.get("Uploads", []):
                key = upload.get("Key")
                upload_id = upload.get("UploadId")
                if not (
                    isinstance(key, str)
                    and key
                    and isinstance(upload_id, str)
                    and upload_id
                ):
                    continue
                client.abort_multipart_upload(
                    Bucket=bucket_name, Key=key, UploadId=upload_id
                )
                aborted += 1
    except ClientError as exc:
        if _is_missing_bucket_error(exc):
            return 0
        raise
    return aborted


def purge_bucket(client, bucket_name: str) -> None:
    if not _bucket_exists(client, bucket_name):
        logger.info("s3_bucket_missing", bucket=bucket_name)
        return
    aborted = _abort_multipart_uploads(client, bucket_name)
    versioned_deleted = _purge_versioned_objects(client, bucket_name)
    current_deleted = _purge_current_objects(client, bucket_name)
    logger.info(
        "s3_bucket_purged",
        bucket=bucket_name,
        aborted_multipart_uploads=aborted,
        versioned_objects_deleted=versioned_deleted,
        current_objects_deleted=current_deleted,
    )


def main() -> int:
    s3_config = get_s3_config()
    if "endpoint_url" not in s3_config:
        raise RuntimeError(
            "Missing S3_ENDPOINT or S3_ENDPOINT_URL for local cleanup; cannot clear local object storage."
        )

    client = boto3.client("s3", **s3_config)
    targets = _resolve_cleanup_targets()
    if not targets:
        print("No S3 cleanup targets configured; nothing to purge.")
        return 0

    print(
        "Purging local S3 buckets: "
        + ", ".join(target.bucket_name for target in targets)
    )
    for target in targets:
        print(f"Purging bucket {target.bucket_name}...")
        purge_bucket(client, target.bucket_name)

    print("Local S3 cleanup completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
