"""Demo fixture connector.

Everything returned here is synthetic and labelled ``is_demo``. It is the
explicit fallback when live NISAR access is unavailable; it never masquerades
as NASA/ISRO data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.connectors.base import ConnectorHealth, DataSource, RemoteProduct, SearchQuery, bbox_intersects
from app.core.errors import NotFoundError
from app.fixtures.demo_raster import AOI_BOUNDS, DEMO_SCENES, ensure_demo_fixtures

DEMO_PROVIDER = "SARVEX Demo Fixtures"
DEMO_LICENSE = "SARVEX synthetic fixture - not NASA/ISRO data"
DEMO_CITATION = (
    "SARVEX demo fixture generator (synthetic). Not an official NISAR observation."
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _catalog() -> list[RemoteProduct]:
    from app.products.metadata import NormalizedProductMetadata

    items: list[RemoteProduct] = []
    for scene_key, spec in DEMO_SCENES.items():
        tags = spec["tags"]
        meta = NormalizedProductMetadata(
            provider=DEMO_PROVIDER,
            mission="SARVEX-DEMO",
            satellite="DEMO-SAR",
            product_type=spec["product_type"],
            product_id=Path(spec["file"]).stem,
            acquisition_start=tags["SARVEX_ACQUISITION_START"],
            frequency_band=tags.get("SARVEX_FREQUENCY_BAND"),
            frequency_hz=float(tags["SARVEX_FREQUENCY_HZ"]) if tags.get("SARVEX_FREQUENCY_HZ") else None,
            polarization=spec["polarization"],
            wavelength_m=float(tags["SARVEX_WAVELENGTH_M"]) if tags.get("SARVEX_WAVELENGTH_M") else None,
            crs="EPSG:4326",
            bbox=list(AOI_BOUNDS),
            units="dB" if spec["product_type"] != "GUNW" else "rad+coherence",
            orbit=int(tags["SARVEX_ORBIT"]),
            track=int(tags["SARVEX_TRACK"]),
            frame=int(tags["SARVEX_FRAME"]),
            pass_direction=tags["SARVEX_PASS_DIRECTION"],
            file_format="GTiff",
            is_demo=True,
        )
        items.append(
            RemoteProduct(
                provider=DEMO_PROVIDER,
                product_id=meta.product_id,
                product_type=meta.product_type,
                acquisition_start=meta.acquisition_start,
                bbox=list(AOI_BOUNDS),
                frequency_band=meta.frequency_band,
                frequency_hz=meta.frequency_hz,
                polarization=meta.polarization,
                wavelength_m=meta.wavelength_m,
                file_format="GTiff",
                size_bytes=None,
                orbit=meta.orbit,
                track=meta.track,
                frame=meta.frame,
                pass_direction=meta.pass_direction,
                is_demo=True,
                license=DEMO_LICENSE,
                citation=DEMO_CITATION,
                attribution="SARVEX synthetic fixture. Not NASA or ISRO data.",
                local_path=None,
                extra={"scene_key": scene_key, "demo": True},
            )
        )
    return items


class DemoFixtureConnector(DataSource):
    name = DEMO_PROVIDER
    mode = "demo"

    def __init__(self) -> None:
        self._paths = ensure_demo_fixtures()
        self._catalog = _catalog()
        # Attach generated paths so download() and ingestion share one source.
        for item in self._catalog:
            key = item.extra.get("scene_key")
            if key and key in self._paths:
                item.local_path = str(self._paths[key])
                item.size_bytes = self._paths[key].stat().st_size

    def search(self, query: SearchQuery) -> list[RemoteProduct]:
        results = []
        for item in self._catalog:
            if query.product_types and item.product_type not in query.product_types:
                continue
            if not bbox_intersects(query.bbox, item.bbox):
                continue
            start = _parse(query.start)
            end = _parse(query.end)
            acq = _parse(item.acquisition_start)
            if start and acq and acq < start:
                continue
            if end and acq and acq > end:
                continue
            results.append(item)
        return results[: query.max_results]

    def get_metadata(self, product_id: str) -> RemoteProduct:
        for item in self._catalog:
            if item.product_id == product_id or item.extra.get("scene_key") == product_id:
                return item
        raise NotFoundError(f"Demo product '{product_id}' not found")

    def download(self, product_id: str, dest_dir: Path) -> Path:
        item = self.get_metadata(product_id)
        if not item.local_path:
            raise NotFoundError("Demo fixture path is unavailable")
        path = Path(item.local_path)
        dest_dir.mkdir(parents=True, exist_ok=True)
        target = dest_dir / path.name
        if target.resolve() != path.resolve():
            target.write_bytes(path.read_bytes())
        return target

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector=self.name,
            status="ok",
            mode="demo",
            message=f"{len(self._catalog)} synthetic fixtures available (clearly labelled DEMO)",
            capabilities={"search": True, "download": True, "live": False, "synthetic": True},
        )


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
