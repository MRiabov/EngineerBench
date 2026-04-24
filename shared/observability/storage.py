import asyncio
import mimetypes
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import boto3
import structlog
from pydantic import BaseModel, Field, StrictInt, StrictStr

logger = structlog.get_logger()


class S3File(BaseModel):
    key: StrictStr
    size: StrictInt
    last_modified: datetime
    content_type: StrictStr | None = None
    etag: StrictStr | None = None


class S3Config(BaseModel):
    endpoint_url: StrictStr | None = Field(
        default=None, description="Custom S3 endpoint URL (e.g. MinIO)"
    )
    access_key_id: StrictStr = Field(..., description="AWS Access Key ID")
    secret_access_key: StrictStr = Field(..., description="AWS Secret Access Key")
    bucket_name: StrictStr = Field(..., description="Target S3 bucket name")
    region_name: StrictStr = Field(default="us-east-1", description="AWS Region")


class S3Client:
    """Wrapper around boto3 S3 client for observability artifacts."""

    def __init__(self, config: S3Config):
        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region_name,
        )
        self.bucket = config.bucket_name

    def upload_file(self, local_path: str | Path, object_key: str) -> str:
        """
        Upload a local file to S3.
        Automatically detects MIME type.
        Returns the object key.
        """
        content_type, _ = mimetypes.guess_type(str(local_path))
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        try:
            self.client.upload_file(
                str(local_path), self.bucket, object_key, ExtraArgs=extra_args
            )
            logger.info(
                "file_uploaded",
                bucket=self.bucket,
                key=object_key,
                path=local_path,
                content_type=content_type,
            )
            return object_key
        except Exception as e:
            logger.error(
                "upload_failed",
                bucket=self.bucket,
                key=object_key,
                error=str(e),
                session_id="system",
            )
            raise

    def upload_files(
        self,
        files: Sequence[tuple[str | Path, str]],
        *,
        max_concurrency: int | None = None,
    ) -> tuple[dict[str, str], dict[str, Exception]]:
        """Upload multiple files in parallel and report per-object outcomes."""
        if not files:
            return {}, {}

        worker_count = max(1, min(max_concurrency or 8, len(files)))
        uploaded: dict[str, str] = {}
        failed: dict[str, Exception] = {}

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self.upload_file, local_path, object_key): object_key
                for local_path, object_key in files
            }
            for future in as_completed(futures):
                object_key = futures[future]
                try:
                    uploaded[object_key] = future.result()
                except Exception as exc:
                    failed[object_key] = exc

        return uploaded, failed

    async def aupload_file(self, local_path: str | Path, object_key: str) -> str:
        """Async version of upload_file."""
        return await asyncio.to_thread(self.upload_file, local_path, object_key)

    async def aupload_files(
        self,
        files: Sequence[tuple[str | Path, str]],
        *,
        max_concurrency: int | None = None,
    ) -> tuple[dict[str, str], dict[str, Exception]]:
        """Async version of upload_files."""
        return await asyncio.to_thread(
            self.upload_files,
            files,
            max_concurrency=max_concurrency,
        )

    def download_file(self, object_key: str, local_path: str | Path):
        """
        Download a file from S3 to a local path.
        """
        try:
            self.client.download_file(self.bucket, object_key, str(local_path))
            logger.info(
                "file_downloaded", bucket=self.bucket, key=object_key, path=local_path
            )
        except Exception as e:
            logger.error(
                "download_failed",
                bucket=self.bucket,
                key=object_key,
                error=str(e),
                session_id="system",
            )
            raise

    async def adownload_file(self, object_key: str, local_path: str | Path):
        """Async version of download_file."""
        return await asyncio.to_thread(self.download_file, object_key, local_path)

    def list_files(self, prefix: str = "") -> list[S3File]:
        """List files in the bucket with optional prefix."""
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            files: list[S3File] = []

            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                if "Contents" in page:
                    for obj in page["Contents"]:
                        files.append(
                            S3File(
                                key=obj["Key"],
                                size=obj["Size"],
                                last_modified=obj["LastModified"],
                                etag=obj.get("ETag"),
                            )
                        )
            return files
        except Exception as e:
            logger.error(
                "list_files_failed",
                bucket=self.bucket,
                prefix=prefix,
                error=str(e),
                session_id="system",
            )
            raise

    def get_presigned_url(self, object_key: str, expiration: int = 3600) -> str:
        """Generate a presigned URL for a file."""
        try:
            url = self.client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.bucket, "Key": object_key},
                ExpiresIn=expiration,
            )
            logger.debug("presigned_url_generated", bucket=self.bucket, key=object_key)
            return url
        except Exception as e:
            logger.error(
                "presigned_url_failed",
                bucket=self.bucket,
                key=object_key,
                error=str(e),
                session_id="system",
            )
            raise
