"""Connector contracts.

Provider-specific logic lives only in connector modules. Ingest, processing and
API layers depend exclusively on these interfaces.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.products.metadata import NormalizedProductMetadata, ValidationReport


@dataclass
class SearchQuery:
    bbox: list[float] | None = None
    start: str | None = None
    end: str | None = None
    product_types: list[str] = field(default_factory=list)
    max_results: int = 50
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemoteProduct:
    provider: str
    product_id: str
    product_type: str
    acquisition_start: str | None = None
    acquisition_end: str | None = None
    bbox: list[float] | None = None
    geometry: dict[str, Any] | None = None
    frequency_band: str | None = None
    frequency_hz: float | None = None
    polarization: str | None = None
    wavelength_m: float | None = None
    source_url: str | None = None
    download_url: str | None = None
    file_format: str | None = None
    size_bytes: int | None = None
    orbit: int | None = None
    track: int | None = None
    frame: int | None = None
    pass_direction: str | None = None
    is_demo: bool = False
    local_path: str | None = None
    license: str | None = None
    citation: str | None = None
    attribution: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def catalog_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "product_id": self.product_id,
            "product_type": self.product_type,
            "acquisition_start": self.acquisition_start,
            "bbox": self.bbox,
            "frequency_band": self.frequency_band,
            "polarization": self.polarization,
            "source_url": self.source_url,
            "file_format": self.file_format,
            "size_bytes": self.size_bytes,
            "is_demo": self.is_demo,
            "extra": {
                "download_url": self.download_url,
                "orbit": self.orbit,
                "track": self.track,
                "frame": self.frame,
                "pass_direction": self.pass_direction,
                **self.extra,
            },
        }


@dataclass
class ConnectorHealth:
    connector: str
    status: str  # ok | degraded | unconfigured | unavailable
    mode: str  # live | local | demo
    message: str
    latency_ms: float | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "status": self.status,
            "mode": self.mode,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "capabilities": self.capabilities,
        }


class DataSource(ABC):
    name: str = "base"
    mode: str = "live"

    @abstractmethod
    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        ...

    @abstractmethod
    def get_metadata(self, product_id: str) -> RemoteProduct:
        ...

    @abstractmethod
    def download(self, product_id: str, dest_dir: Path) -> Path:
        ...

    def stream(self, product_id: str, chunk_size: int = 1024 * 1024) -> Iterable[bytes]:
        """Stream a remote product. Default implementation materializes locally."""
        import tempfile

        path = self.download(product_id, Path(tempfile.mkdtemp(prefix="sarvex-stream-")))
        with path.open("rb") as fh:
            while chunk := fh.read(chunk_size):
                yield chunk

    def validate(self, path: Path, product_type: str | None = None) -> ValidationReport:
        from app.products.registry import get_adapter

        return get_adapter(path, product_type).validate(path)

    def register(
        self,
        path: Path,
        *,
        product_id: str,
        product_type: str | None = None,
        source_url: str | None = None,
    ) -> NormalizedProductMetadata:
        from app.products.registry import get_adapter

        return get_adapter(path, product_type).extract(
            path,
            provider=self.name,
            product_id=product_id,
            product_type=product_type,
            source_url=source_url,
        )

    @abstractmethod
    def health_check(self) -> ConnectorHealth:
        ...


def bbox_intersects(a: list[float] | None, b: list[float] | None) -> bool:
    if not a or not b:
        return True
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])
