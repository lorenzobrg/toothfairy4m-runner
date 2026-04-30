import os
from dataclasses import dataclass
from typing import Dict, Generator, Optional
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

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
                "OBJECT_STORAGE_ENDPOINT_URL must include scheme and host, e.g. http://garage:3900"
            )

        secure = parsed.scheme == "https" or bool(cfg.object_storage_use_ssl)
        verify = bool(cfg.object_storage_verify_ssl) if secure else False
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg.object_storage_endpoint_url,
            aws_access_key_id=cfg.object_storage_access_key_id,
            aws_secret_access_key=cfg.object_storage_secret_access_key,
            region_name=cfg.object_storage_region or None,
            use_ssl=secure,
            verify=verify,
            config=Config(
                s3={"addressing_style": cfg.object_storage_addressing_style or "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _client_error_code(self, exc: ClientError) -> str:
        return str((exc.response or {}).get("Error", {}).get("Code", ""))

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
            self._client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as exc:
            code = self._client_error_code(exc)
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise ObjectStorageError(str(exc)) from exc

        try:
            kwargs: Dict[str, object] = {"Bucket": self.bucket}
            region = getattr(self._client.meta, "region_name", None)
            if region and region not in {"us-east-1"}:
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
            self._client.create_bucket(**kwargs)
        except ClientError as exc:
            code = self._client_error_code(exc)
            if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
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
            resp = self._client.head_object(Bucket=self.bucket, Key=key_n)
        except ClientError as exc:
            code = self._client_error_code(exc)
            if code in {"NoSuchKey", "NotFound", "404"}:
                raise FileNotFoundError(key) from exc
            raise ObjectStorageError(str(exc)) from exc

        etag = resp.get("ETag")
        if isinstance(etag, str):
            etag = etag.strip('"')
        return ObjectInfo(
            key=key,
            content_length=resp.get("ContentLength"),
            content_type=resp.get("ContentType"),
            etag=etag,
        )

    def list_keys(self, prefix: str) -> Generator[str, None, None]:
        prefix_n = self.normalize_key(prefix)
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix_n):
            for obj in page.get("Contents", []) or []:
                key_n = obj.get("Key")
                if not key_n:
                    continue
                yield self.denormalize_key(key_n)

    def download_file(self, key: str, dest_path: str) -> None:
        self.ensure_bucket_exists()
        key_n = self.normalize_key(key)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            self._client.download_file(self.bucket, key_n, dest_path)
        except ClientError as exc:
            raise ObjectStorageError(str(exc)) from exc

    def upload_file(
        self, local_path: str, *, key: str, content_type: Optional[str] = None
    ) -> ObjectInfo:
        self.ensure_bucket_exists()
        key_n = self.normalize_key(key)
        try:
            extra: Dict[str, str] = {}
            if content_type:
                extra["ContentType"] = content_type
            self._client.upload_file(
                local_path, self.bucket, key_n, ExtraArgs=extra or None
            )
        except ClientError as exc:
            raise ObjectStorageError(str(exc)) from exc
        return self.head(key)
