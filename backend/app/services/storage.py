"""Raw-file storage: S3 (SSE-KMS) in deployed environments, local disk for development."""

from pathlib import Path
from typing import Protocol

from ..core.config import get_settings
from ..core.errors import AppError, NotFoundError, UpstreamError

settings = get_settings()


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise AppError("Invalid file location.", code="invalid_storage_key")
        return p

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        except OSError as exc:
            raise UpstreamError("Couldn't save the file to local storage (disk full or not writable?).",
                                code="storage_write_failed") from exc

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise NotFoundError("The original file is missing from storage.", code="file_missing") from exc
        except OSError as exc:
            raise UpstreamError("Couldn't read the file from local storage.", code="storage_read_failed") from exc


class S3Storage:
    def __init__(self, bucket: str, region: str, kms_key_id: str = "") -> None:
        import boto3

        self.bucket = bucket
        self.kms_key_id = kms_key_id
        self.client = boto3.client("s3", region_name=region)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        extra = {"ServerSideEncryption": "aws:kms"}
        if self.kms_key_id:
            extra["SSEKMSKeyId"] = self.kms_key_id
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, **extra)
        except (ClientError, BotoCoreError) as exc:
            raise UpstreamError("Couldn't save the file to S3. Please try again.", code="storage_write_failed") from exc

    def get(self, key: str) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise NotFoundError("The original file is missing from storage.", code="file_missing") from exc
            raise UpstreamError("Couldn't read the file from S3. Please try again.", code="storage_read_failed") from exc
        except BotoCoreError as exc:
            raise UpstreamError("Couldn't reach S3. Please try again.", code="storage_read_failed") from exc


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        if settings.storage_backend == "s3":
            _storage = S3Storage(settings.s3_bucket, settings.aws_region, settings.s3_kms_key_id)
        else:
            _storage = LocalStorage(str(settings.resolved_storage_dir))
    return _storage
