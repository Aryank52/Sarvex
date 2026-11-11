"""Ingestion service: validate -> adapt -> checksum -> object store -> manifest."""
from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.base import RemoteProduct
from app.core.errors import ConflictError, ValidationError
from app.core.geometry import geometry_bbox
from app.db.models import Dataset, Observation, Product
from app.products.registry import get_adapter
from app.storage.object_store import get_object_store

DEFAULT_LICENSE = {
    "NASA ASF": "NASA Earthdata terms - consult ASF",
    "ISRO Bhoonidhi": "ISRO Bhoonidhi authorized-use terms",
    "SARVEX Demo Fixtures": "SARVEX synthetic fixture - not NASA/ISRO data",
    "Local Files": "Operator-supplied local data",
}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _slug(value: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in value).strip("-")[:40] or "provider"


def build_manifest(
    *,
    dataset_id: str,
    provider: str,
    product_id: str,
    product_type: str,
    source: str | None,
    acquisition_time: str | None,
    geometry: dict[str, Any] | None,
    crs: str | None,
    frequency: str | None,
    polarization: str | None,
    processing_baseline: str | None,
    object_uri: str | None,
    checksum: str | None,
    validation_status: str,
    attribution: str | None,
    license_text: str | None,
    citation: str | None,
    normalized_metadata: dict[str, Any],
    is_demo: bool,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "provider": provider,
        "product_id": product_id,
        "product_type": product_type,
        "source": source,
        "acquisition_time": acquisition_time,
        "geometry": geometry,
        "CRS": crs,
        "frequency": frequency,
        "polarization": polarization,
        "processing_baseline": processing_baseline,
        "file_path_object_uri": object_uri,
        "checksum": checksum,
        "ingest_time": datetime.now(timezone.utc).isoformat(),
        "validation_status": validation_status,
        "attribution": attribution,
        "license": license_text,
        "citation": citation,
        "processing_history": [
            {
                "step": "ingest",
                "at": datetime.now(timezone.utc).isoformat(),
                "provider": provider,
                "adapter": normalized_metadata.get("extraction_method"),
            }
        ],
        "normalized_metadata": normalized_metadata,
        "is_demo": is_demo,
    }


def ingest_file(
    session: Session,
    *,
    path: Path,
    provider: str,
    product_type: str | None = None,
    product_id: str | None = None,
    source_url: str | None = None,
    remote: RemoteProduct | None = None,
    is_demo: bool | None = None,
) -> Product:
    """Ingest one local file and return the persisted Product.

    Duplicate content (same checksum) is rejected with a conflict rather than
    silently duplicated, preserving observational integrity.
    """
    if not path.exists() or not path.is_file():
        raise ValidationError("Ingestion file does not exist")
    adapter = get_adapter(path, product_type)
    report = adapter.validate(path)
    report.raise_if_invalid()
    meta = adapter.extract(path, provider=provider, product_id=product_id, product_type=product_type, source_url=source_url)

    # Catalog metadata may fill fields the file itself does not carry.
    if remote:
        meta.acquisition_start = meta.acquisition_start or remote.acquisition_start
        meta.acquisition_end = meta.acquisition_end or remote.acquisition_end
        meta.bbox = meta.bbox or remote.bbox
        meta.geometry = meta.geometry or remote.geometry
        meta.frequency_band = meta.frequency_band or remote.frequency_band
        meta.frequency_hz = meta.frequency_hz or remote.frequency_hz
        meta.polarization = meta.polarization or remote.polarization
        meta.wavelength_m = meta.wavelength_m or remote.wavelength_m
        meta.orbit = meta.orbit if meta.orbit is not None else remote.orbit
        meta.track = meta.track if meta.track is not None else remote.track
        meta.frame = meta.frame if meta.frame is not None else remote.frame
        meta.pass_direction = meta.pass_direction or remote.pass_direction
        source_url = source_url or remote.source_url
    demo_flag = (
        bool(is_demo)
        or "demo" in provider.lower()
        or str(meta.extra.get("raster", {}).get("tags", {}).get("SARVEX_IS_DEMO", "")).upper() == "TRUE"
        or (remote.is_demo if remote else False)
    )
    if not meta.checksum:
        meta.checksum = _sha(path)

    existing = session.scalar(select(Product).where(Product.checksum == meta.checksum))
    if existing:
        raise ConflictError(
            "A product with identical content has already been ingested",
            detail={"product_id": existing.product_id, "existing_db_id": existing.id},
        )

    dataset_id = f"DS-{meta.checksum[:16].upper()}"
    dataset = session.scalar(select(Dataset).where(Dataset.dataset_id == dataset_id))
    if dataset is None:
        dataset = Dataset(
            dataset_id=dataset_id,
            provider=provider,
            product_id=meta.product_id,
            product_type=meta.product_type,
            mission=meta.mission or "NISAR",
            satellite=meta.satellite,
            source_url=source_url,
            source_identifier=meta.source_identifier,
            license=(remote.license if remote else None) or DEFAULT_LICENSE.get(provider, "Unspecified"),
            citation=(remote.citation if remote else None) or "See provider documentation.",
            attribution=(remote.attribution if remote else None) or "See provider attribution.",
            validation_status="VALID" if not report.warnings else "VALID_WITH_WARNINGS",
            is_demo=demo_flag,
            processing_history=[],
        )
        session.add(dataset)
        session.flush()

    # Object storage upload (large binary never stored in PostgreSQL).
    store = get_object_store()
    key = f"datasets/{dataset_id}/{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    object_uri = store.put_file(key, path, content_type)

    acq_start = _parse_dt(meta.acquisition_start)
    if acq_start is None:
        raise ValidationError(
            "Acquisition start time is missing and could not be established",
            detail={"product": meta.product_id},
        )
    acq_end = _parse_dt(meta.acquisition_end)
    geometry = meta.geometry
    if geometry is None and meta.bbox:
        minx, miny, maxx, maxy = meta.bbox
        geometry = {
            "type": "Polygon",
            "coordinates": [[[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]],
        }
    bbox = meta.bbox or (geometry_bbox(geometry) if geometry else [])
    observation = Observation(
        dataset_id=dataset.id,
        product_id=meta.product_id,
        product_type=meta.product_type,
        acquisition_start=acq_start,
        acquisition_end=acq_end,
        orbit=meta.orbit,
        pass_direction=meta.pass_direction,
        track=meta.track,
        frame=meta.frame,
        frequency_band=meta.frequency_band,
        frequency_hz=meta.frequency_hz,
        polarization=meta.polarization,
        wavelength_m=meta.wavelength_m,
        crs=meta.crs,
        bbox=bbox,
        geometry=geometry,
        spatial_resolution_m=meta.spatial_resolution_m,
        units=meta.units,
        processing_baseline=meta.processing_baseline,
        quality=meta.quality_indicators,
        calibration_status=meta.calibration_status,
        provider=provider,
        is_demo=demo_flag,
    )
    session.add(observation)
    session.flush()

    normalized = meta.model_dump()
    normalized["extraction_notes"] = meta.extraction_notes
    manifest = build_manifest(
        dataset_id=dataset.dataset_id,
        provider=provider,
        product_id=meta.product_id,
        product_type=meta.product_type,
        source=source_url,
        acquisition_time=acq_start.isoformat(),
        geometry=geometry,
        crs=meta.crs,
        frequency=meta.frequency_band,
        polarization=meta.polarization,
        processing_baseline=meta.processing_baseline,
        object_uri=object_uri,
        checksum=meta.checksum,
        validation_status="VALID" if not report.warnings else "VALID_WITH_WARNINGS",
        attribution=dataset.attribution,
        license_text=dataset.license,
        citation=dataset.citation,
        normalized_metadata=normalized,
        is_demo=demo_flag,
    )
    product = Product(
        observation_id=observation.id,
        product_id=meta.product_id,
        product_type=meta.product_type,
        provider=provider,
        object_uri=object_uri,
        file_format=meta.file_format,
        file_size=meta.file_size,
        checksum=meta.checksum,
        source_url=source_url,
        normalized_metadata=normalized,
        manifest=manifest,
        validation_status="VALID" if not report.warnings else "VALID_WITH_WARNINGS",
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        is_demo=demo_flag,
    )
    session.add(product)
    dataset.manifest = manifest
    dataset.processing_history = list(dataset.processing_history or []) + manifest["processing_history"]
    session.commit()
    return product


def _sha(path: Path) -> str:
    from app.core.geometry import sha256_file

    return sha256_file(path)


def ingest_remote(
    session: Session,
    connector: Any,
    remote: RemoteProduct,
    dest_dir: Path,
) -> Product:
    path = connector.download(remote.product_id, dest_dir)
    product = ingest_file(
        session,
        path=path,
        provider=remote.provider,
        product_type=remote.product_type,
        product_id=remote.product_id,
        source_url=remote.source_url,
        remote=remote,
        is_demo=remote.is_demo,
    )
    # Fill missing geometry at dataset scope when a catalog supplied it.
    if remote.geometry and product.observation and not product.observation.geometry:
        product.observation.geometry = remote.geometry
        session.commit()
    return product
