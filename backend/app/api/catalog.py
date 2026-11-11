"""Catalog, dataset, observation, product and ingestion endpoints."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.config import BACKEND_DIR, get_settings
from app.connectors.base import SearchQuery
from app.connectors.local import LocalFileConnector
from app.connectors.registry import get_connector_registry
from app.core.errors import NotFoundError, ValidationError
from app.core.geometry import sanitize_filename
from app.db.models import Dataset, Observation, Product
from app.schemas.catalog import (
    CatalogItem,
    CatalogSearchResponse,
    DatasetOut,
    IngestRequest,
    IngestResponse,
    ManifestOut,
    ObservationOut,
    ProductOut,
    SearchRequest,
)
from app.schemas.common import Page
from app.services.ingest import ingest_file, ingest_remote

router = APIRouter(tags=["catalog"], dependencies=[Depends(rate_limit)])


def _product_matches_bbox(obs: Observation, bbox: list[float]) -> bool:
    if not obs.bbox or len(obs.bbox) != 4:
        return True
    return not (
        obs.bbox[2] < bbox[0]
        or obs.bbox[0] > bbox[2]
        or obs.bbox[3] < bbox[1]
        or obs.bbox[1] > bbox[3]
    )


@router.get("/datasets", response_model=Page[DatasetOut])
def list_datasets(
    provider: str | None = None,
    product_type: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[DatasetOut]:
    stmt = select(Dataset)
    if provider:
        stmt = stmt.where(Dataset.provider == provider)
    if product_type:
        stmt = stmt.where(Dataset.product_type == product_type.upper())
    if demo is not None:
        stmt = stmt.where(Dataset.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(Dataset.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[DatasetOut](
        items=[DatasetOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: str, db: Session = Depends(get_db)) -> DatasetOut:
    dataset = db.scalar(select(Dataset).where(Dataset.dataset_id == dataset_id))
    if not dataset:
        dataset = db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    return DatasetOut.model_validate(dataset)


@router.get("/datasets/{dataset_id}/manifest", response_model=ManifestOut)
def get_manifest(dataset_id: str, db: Session = Depends(get_db)) -> ManifestOut:
    dataset = db.scalar(select(Dataset).where(Dataset.dataset_id == dataset_id)) or db.get(Dataset, dataset_id)
    if not dataset:
        raise NotFoundError(f"Dataset {dataset_id} not found")
    manifest = dataset.manifest or {}
    return ManifestOut(
        dataset_id=manifest.get("dataset_id", dataset.dataset_id),
        provider=manifest.get("provider", dataset.provider),
        product_id=manifest.get("product_id", dataset.product_id),
        product_type=manifest.get("product_type", dataset.product_type),
        source=manifest.get("source"),
        acquisition_time=manifest.get("acquisition_time"),
        geometry=manifest.get("geometry"),
        crs=manifest.get("CRS"),
        frequency=manifest.get("frequency"),
        polarization=manifest.get("polarization"),
        processing_baseline=manifest.get("processing_baseline"),
        object_uri=manifest.get("file_path_object_uri"),
        checksum=manifest.get("checksum"),
        ingest_time=manifest.get("ingest_time", dataset.created_at.isoformat()),
        validation_status=manifest.get("validation_status", dataset.validation_status),
        attribution=manifest.get("attribution", dataset.attribution),
        license=manifest.get("license", dataset.license),
        citation=manifest.get("citation", dataset.citation),
        processing_history=manifest.get("processing_history", dataset.processing_history or []),
        normalized_metadata=manifest.get("normalized_metadata", {}),
        is_demo=bool(manifest.get("is_demo", dataset.is_demo)),
    )


@router.get("/observations", response_model=Page[ObservationOut])
def list_observations(
    bbox: str | None = Query(default=None, description="minx,miny,maxx,maxy"),
    start: str | None = None,
    end: str | None = None,
    product_type: str | None = None,
    frequency_band: str | None = None,
    polarization: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[ObservationOut]:
    stmt = select(Observation)
    if product_type:
        stmt = stmt.where(Observation.product_type == product_type.upper())
    if frequency_band:
        stmt = stmt.where(Observation.frequency_band == frequency_band.upper())
    if polarization:
        stmt = stmt.where(Observation.polarization.contains(polarization.upper()))
    if demo is not None:
        stmt = stmt.where(Observation.is_demo.is_(demo))
    if start:
        stmt = stmt.where(Observation.acquisition_start >= _parse_date(start))
    if end:
        stmt = stmt.where(Observation.acquisition_start <= _parse_date(end))
    stmt = stmt.order_by(Observation.acquisition_start)
    rows = db.scalars(stmt).all()
    if bbox:
        box = _parse_bbox(bbox)
        rows = [r for r in rows if _product_matches_bbox(r, box)]
    total = len(rows)
    rows = rows[offset : offset + limit]
    return Page[ObservationOut](
        items=[ObservationOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/observations/{observation_id}", response_model=ObservationOut)
def get_observation(observation_id: str, db: Session = Depends(get_db)) -> ObservationOut:
    obs = db.get(Observation, observation_id)
    if not obs:
        obs = db.scalar(select(Observation).where(Observation.product_id == observation_id))
    if not obs:
        raise NotFoundError(f"Observation {observation_id} not found")
    return ObservationOut.model_validate(obs)


@router.get("/products", response_model=Page[ProductOut])
def list_products(
    product_type: str | None = None,
    provider: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[ProductOut]:
    stmt = select(Product)
    if product_type:
        stmt = stmt.where(Product.product_type == product_type.upper())
    if provider:
        stmt = stmt.where(Product.provider == provider)
    if demo is not None:
        stmt = stmt.where(Product.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(stmt.order_by(Product.created_at.desc()).limit(limit).offset(offset)).all()
    return Page[ProductOut](
        items=[ProductOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: str, db: Session = Depends(get_db)) -> ProductOut:
    product = db.get(Product, product_id) or db.scalar(
        select(Product).where(Product.product_id == product_id)
    )
    if not product:
        raise NotFoundError(f"Product {product_id} not found")
    return ProductOut.model_validate(product)


@router.post("/catalog/search", response_model=CatalogSearchResponse)
def catalog_search(request: SearchRequest, db: Session = Depends(get_db)) -> CatalogSearchResponse:
    registry = get_connector_registry()
    query = SearchQuery(
        bbox=request.bbox,
        start=request.start,
        end=request.end,
        product_types=[p.upper() for p in request.product_types],
        max_results=request.max_results,
    )
    products, connector, demo_fallback, warning = registry.search_with_fallback(
        request.connector, query
    )
    items = [
        CatalogItem(
            provider=p.provider,
            product_id=p.product_id,
            product_type=p.product_type,
            acquisition_start=p.acquisition_start,
            bbox=p.bbox,
            frequency_band=p.frequency_band,
            polarization=p.polarization,
            source_url=p.source_url,
            file_format=p.file_format,
            size_bytes=p.size_bytes,
            is_demo=p.is_demo,
            extra=p.extra,
        )
        for p in products
    ]
    return CatalogSearchResponse(
        items=items,
        connector=connector,
        demo_fallback=demo_fallback,
        warning=warning,
        data_mode="DEMO" if any(i.is_demo for i in items) or demo_fallback else "LIVE",
        total=len(items),
    )


@router.post("/catalog/ingest", response_model=IngestResponse, status_code=201)
def catalog_ingest(request: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    registry = get_connector_registry()
    if request.connector == "local":
        if not request.path:
            raise ValidationError("A path is required for local ingestion")
        connector = LocalFileConnector()
        path = connector.resolve_path(request.path)
        product = ingest_file(
            db,
            path=path,
            provider="Local Files",
            product_type=request.product_type,
        )
    elif request.connector == "demo":
        reference = request.product_ref or (
            request.catalog_item.product_id if request.catalog_item else None
        )
        if not reference:
            raise ValidationError("A demo product_ref or catalog_item is required")
        remote = registry.demo.get_metadata(reference)
        product = ingest_remote(db, registry.demo, remote, _ingest_dir())
    else:
        connector = registry.get(request.connector)
        reference = request.product_ref or (
            request.catalog_item.product_id if request.catalog_item else None
        )
        if not reference:
            raise ValidationError("A product_ref or catalog_item is required")
        try:
            remote = connector.get_metadata(reference)
        except NotFoundError:
            if request.catalog_item:
                from app.connectors.base import RemoteProduct

                remote = RemoteProduct(
                    provider=request.catalog_item.provider,
                    product_id=request.catalog_item.product_id,
                    product_type=request.catalog_item.product_type,
                    acquisition_start=request.catalog_item.acquisition_start,
                    bbox=request.catalog_item.bbox,
                    frequency_band=request.catalog_item.frequency_band,
                    polarization=request.catalog_item.polarization,
                    source_url=request.catalog_item.source_url,
                    file_format=request.catalog_item.file_format,
                    size_bytes=request.catalog_item.size_bytes,
                    is_demo=request.catalog_item.is_demo,
                )
            else:
                raise
        product = ingest_remote(db, connector, remote, _ingest_dir())
    return IngestResponse(
        dataset_id=product.observation.dataset.dataset_id,
        observation_id=product.observation_id,
        product_db_id=product.id,
        product_type=product.product_type,
        validation_status=product.validation_status,
        is_demo=product.is_demo,
    )


@router.post("/catalog/upload", response_model=IngestResponse, status_code=201)
async def upload_product(
    file: UploadFile = File(...),
    product_type: str | None = Form(default=None),
    provider: str = Form(default="Local Uploads"),
    db: Session = Depends(get_db),
) -> IngestResponse:
    settings = get_settings()
    if not file.filename:
        raise ValidationError("Uploaded file has no filename")
    name = sanitize_filename(file.filename)
    suffix = Path(name).suffix.lower()
    if suffix not in {".tif", ".tiff", ".cog", ".h5", ".hdf5", ".he5", ".nc", ".img", ".vrt"}:
        raise ValidationError(
            f"Unsupported upload format '{suffix}'",
            detail={"supported": [".tif", ".tiff", ".cog", ".h5", ".hdf5", ".he5", ".nc"]},
        )
    max_bytes = settings.max_upload_mb * 1024 * 1024
    upload_dir = BACKEND_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / name
    written = 0
    with target.open("wb") as fh:
        while chunk := await file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                fh.close()
                target.unlink(missing_ok=True)
                raise ValidationError(
                    f"Upload exceeds maximum size of {settings.max_upload_mb} MB"
                )
            fh.write(chunk)
    if written == 0:
        target.unlink(missing_ok=True)
        raise ValidationError("Uploaded file is empty")
    product = ingest_file(
        db,
        path=target,
        provider=provider,
        product_type=product_type.upper() if product_type else None,
    )
    return IngestResponse(
        dataset_id=product.observation.dataset.dataset_id,
        observation_id=product.observation_id,
        product_db_id=product.id,
        product_type=product.product_type,
        validation_status=product.validation_status,
        is_demo=product.is_demo,
    )


@router.get("/catalog/adapters")
def adapter_catalog() -> dict[str, Any]:
    from app.products.registry import adapter_catalog as catalog

    return {"adapters": catalog()}


def _parse_date(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"Invalid ISO date: {value}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_bbox(value: str) -> list[float]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise ValidationError("bbox must be 'minx,miny,maxx,maxy'")
    try:
        return [float(p) for p in parts]
    except ValueError as exc:
        raise ValidationError("bbox values must be numeric") from exc


def _ingest_dir() -> Path:
    path = BACKEND_DIR / "data" / "ingested"
    path.mkdir(parents=True, exist_ok=True)
    return path
