"""Local file connector with traversal-safe roots."""
from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.connectors.base import ConnectorHealth, DataSource, RemoteProduct, SearchQuery, bbox_intersects
from app.core.errors import NotFoundError, ValidationError
from app.core.geometry import sanitize_filename
from app.products.registry import get_adapter

SUPPORTED_SUFFIXES = {".tif", ".tiff", ".cog", ".h5", ".hdf5", ".he5", ".nc", ".img", ".vrt"}


class LocalFileConnector(DataSource):
    name = "Local Files"
    mode = "local"

    def __init__(self, roots: list[Path] | None = None) -> None:
        self.roots = [r.resolve() for r in (roots or get_settings().local_ingest_paths)]
        for root in self.roots:
            root.mkdir(parents=True, exist_ok=True)

    def _all_files(self) -> list[Path]:
        files: list[Path] = []
        for root in self.roots:
            if root.exists():
                files.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)
        return sorted(set(files))

    def _metadata_for(self, path: Path) -> RemoteProduct:
        adapter = get_adapter(path)
        meta = adapter.extract(path, provider=self.name)
        return RemoteProduct(
            provider=self.name,
            product_id=meta.product_id,
            product_type=meta.product_type,
            acquisition_start=meta.acquisition_start,
            bbox=meta.bbox,
            geometry=meta.geometry,
            frequency_band=meta.frequency_band,
            frequency_hz=meta.frequency_hz,
            polarization=meta.polarization,
            wavelength_m=meta.wavelength_m,
            file_format=meta.file_format,
            size_bytes=meta.file_size,
            orbit=meta.orbit,
            track=meta.track,
            frame=meta.frame,
            pass_direction=meta.pass_direction,
            is_demo=False,
            local_path=str(path),
            license="Operator-supplied local data",
            citation="Local ingestion",
            attribution="Local file supplied by the operator.",
            extra={"adapter": adapter.name},
        )

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        results: list[RemoteProduct] = []
        for path in self._all_files():
            try:
                item = self._metadata_for(path)
            except Exception:  # noqa: BLE001 - one bad file must not break discovery
                continue
            if query.product_types and item.product_type not in query.product_types:
                continue
            if not bbox_intersects(query.bbox, item.bbox):
                continue
            results.append(item)
            if len(results) >= query.max_results:
                break
        return results

    def get_metadata(self, product_id: str) -> RemoteProduct:
        for path in self._all_files():
            if path.stem == product_id or path.name == product_id:
                return self._metadata_for(path)
        raise NotFoundError(f"Local product '{product_id}' not found in configured roots")

    def resolve_path(self, raw: str) -> Path:
        """Resolve an operator path and reject anything outside configured roots."""
        name = sanitize_filename(raw)
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.roots[0] / raw
        resolved = candidate.resolve()
        if not any(resolved == root or root in resolved.parents for root in self.roots):
            raise ValidationError(
                "Path is outside configured ingestion roots",
                detail={"roots": [str(r) for r in self.roots], "filename": name},
            )
        if not resolved.exists() or not resolved.is_file():
            raise NotFoundError("Local file does not exist")
        if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValidationError(f"Unsupported file type: {resolved.suffix}")
        return resolved

    def download(self, product_id: str, dest_dir: Path) -> Path:
        item = self.get_metadata(product_id)
        path = self.resolve_path(item.local_path or product_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / path.name
        if target.resolve() != path.resolve():
            target.write_bytes(path.read_bytes())
        return target

    def health_check(self) -> ConnectorHealth:
        exists = [str(r) for r in self.roots if r.exists()]
        return ConnectorHealth(
            connector=self.name,
            status="ok" if exists else "degraded",
            mode="local",
            message=f"{len(self._all_files())} local files under {len(exists)} root(s)",
            capabilities={"search": True, "download": True, "live": False},
        )
