"""Object storage abstraction: local filesystem and S3-compatible (MinIO).

Rasters and report artifacts never enter PostgreSQL; only URIs are stored.
"""
from __future__ import annotations

import shutil
import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.core.geometry import safe_join


class ObjectStore(ABC):
    scheme: str = ""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        ...

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> str:
        return self.put_bytes(key, path.read_bytes(), content_type or "application/octet-stream")

    @abstractmethod
    def get_bytes(self, uri: str) -> bytes:
        ...

    @abstractmethod
    def exists(self, uri: str) -> bool:
        ...

    @abstractmethod
    def delete(self, uri: str) -> None:
        ...

    @abstractmethod
    def materialize(self, uri: str) -> Path:
        """Return a local path for a stored object (download if remote)."""
        ...

    @abstractmethod
    def uri_for(self, key: str) -> str:
        ...

    def ensure_bucket(self) -> None:  # pragma: no cover - backend specific
        return None


class LocalObjectStore(ObjectStore):
    scheme = "local"

    def __init__(self, root: Path, bucket: str = "sarvex") -> None:
        self.root = Path(root).resolve()
        self.bucket = bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = safe_join(self.root, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def uri_for(self, key: str) -> str:
        return f"local://{self.bucket}/{key.lstrip('/')}"

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._path(key).write_bytes(data)
        return self.uri_for(key)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> str:
        self._path(key).write_bytes(path.read_bytes())
        return self.uri_for(key)

    def get_bytes(self, uri: str) -> bytes:
        return self._resolve(uri).read_bytes()

    def _resolve(self, uri: str) -> Path:
        if uri.startswith("local://"):
            _, rest = uri.split("local://", 1)
            _, _, key = rest.partition("/")
            return self._path(key)
        p = Path(uri)
        if p.is_absolute() and self.root in p.resolve().parents:
            return p
        raise ValueError(f"URI does not belong to local object store: {uri}")

    def exists(self, uri: str) -> bool:
        try:
            return self._resolve(uri).exists()
        except ValueError:
            return False

    def delete(self, uri: str) -> None:
        p = self._resolve(uri)
        if p.exists():
            p.unlink()

    def materialize(self, uri: str) -> Path:
        return self._resolve(uri)


class S3ObjectStore(ObjectStore):
    scheme = "s3"

    def __init__(
        self,
        *,
        endpoint: str | None,
        access_key: str | None,
        secret_key: str | None,
        bucket: str,
        region: str,
    ) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
            config=None,
        )

    def uri_for(self, key: str) -> str:
        return f"s3://{self.bucket}/{key.lstrip('/')}"

    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key.lstrip("/"), Body=data, ContentType=content_type)
        return self.uri_for(key)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> str:
        self.client.upload_file(str(path), self.bucket, key.lstrip("/"))
        return self.uri_for(key)

    def get_bytes(self, uri: str) -> bytes:
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        resp = self.client.get_object(Bucket=parsed.netloc or self.bucket, Key=parsed.path.lstrip("/"))
        return resp["Body"].read()

    def exists(self, uri: str) -> bool:
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        try:
            self.client.head_object(Bucket=parsed.netloc or self.bucket, Key=parsed.path.lstrip("/"))
            return True
        except Exception:  # noqa: BLE001
            return False

    def delete(self, uri: str) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        self.client.delete_object(Bucket=parsed.netloc or self.bucket, Key=parsed.path.lstrip("/"))

    def materialize(self, uri: str) -> Path:
        from urllib.parse import urlparse

        parsed = urlparse(uri)
        suffix = Path(parsed.path).suffix
        tmp = Path(tempfile.mkdtemp(prefix="sarvex-s3-")) / f"object{suffix}"
        self.client.download_file(parsed.netloc or self.bucket, parsed.path.lstrip("/"), str(tmp))
        return tmp

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:  # noqa: BLE001
            self.client.create_bucket(Bucket=self.bucket)


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    settings = get_settings()
    if settings.object_storage_backend == "s3":
        store = S3ObjectStore(
            endpoint=settings.object_storage_endpoint,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
            bucket=settings.object_storage_bucket,
            region=settings.object_storage_region,
        )
        store.ensure_bucket()
        return store
    return LocalObjectStore(settings.object_storage_dir, settings.object_storage_bucket)


def reset_object_store_cache() -> None:
    get_object_store.cache_clear()
