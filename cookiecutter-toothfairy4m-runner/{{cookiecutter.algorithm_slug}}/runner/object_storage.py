import os
from dataclasses import dataclass
from typing import Generator, Optional
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from .config import RunnerConfig


class ObjectStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    content_length: Optional[int] = None
    content_type: Optional[str] = None
    etag: Optional[str] = None


class ObjectStorage:
    def __init__(self, cfg: RunnerConfig):
        self.bucket = cfg.object_storage_bucket
        self.key_prefix = cfg.object_storage_key_prefix

        parsed = urlparse(cfg.object_storage_endpoint_url)
        if not parsed.scheme or not parsed.netloc:
            raise ObjectStorageError(
                "OBJECT_STORAGE_ENDPOINT_URL must include scheme and host, e.g. http://minio:9000"
            )

        secure = parsed.scheme == "https" or bool(cfg.object_storage_use_ssl)
        self._client = Minio(
            parsed.netloc,
            access_key=cfg.object_storage_access_key_id,
            secret_key=cfg.object_storage_secret_access_key,
            secure=secure,
        )

    def normalize_key(self, key: str) -> str:
        key = (key or "").lstrip("/")
        if ".." in key.split("/"):
            raise ObjectStorageError("Invalid object key")
        if self.key_prefix:
            return f"{self.key_prefix}/{key}" if key else self.key_prefix
        return key

    def denormalize_key(self, normalized_key: str) -> str:
        k = (normalized_key or "").lstrip("/")
        if self.key_prefix and k.startswith(self.key_prefix + "/"):
            return k[len(self.key_prefix) + 1 :]
        return k

    def ensure_bucket_exists(self) -> None:
        try:
            if self._client.bucket_exists(self.bucket):
                return
            self._client.make_bucket(self.bucket)
        except S3Error as exc:
            if exc.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise ObjectStorageError(str(exc)) from exc

    def exists(self, key: str) -> bool:
        try:
            self.head(key)
            return True
        except FileNotFoundError:
            return False

    def head(self, key: str) -> ObjectInfo:
        key_n = self.normalize_key(key)
        try:
            stat = self._client.stat_object(self.bucket, key_n)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NotFound"}:
                raise FileNotFoundError(key) from exc
            raise ObjectStorageError(str(exc)) from exc
        return ObjectInfo(
            key=key,
            content_length=getattr(stat, "size", None),
            content_type=getattr(stat, "content_type", None),
            etag=getattr(stat, "etag", None),
        )

    def list_keys(self, prefix: str) -> Generator[str, None, None]:
        prefix_n = self.normalize_key(prefix)
        for obj in self._client.list_objects(
            self.bucket, prefix=prefix_n, recursive=True
        ):
            key_n = getattr(obj, "object_name", None)
            if not key_n:
                continue
            yield self.denormalize_key(key_n)

    def download_file(self, key: str, dest_path: str) -> None:
        self.ensure_bucket_exists()
        key_n = self.normalize_key(key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            self._client.fget_object(self.bucket, key_n, dest_path)
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc

    def upload_file(
        self, local_path: str, *, key: str, content_type: Optional[str] = None
    ) -> ObjectInfo:
        self.ensure_bucket_exists()
        key_n = self.normalize_key(key)
        try:
            self._client.fput_object(
                self.bucket, key_n, local_path, content_type=content_type
            )
        except S3Error as exc:
            raise ObjectStorageError(str(exc)) from exc
        return self.head(key)
