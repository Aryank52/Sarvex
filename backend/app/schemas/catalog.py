"""Catalog and geospatial schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel, UTCDateTime


class AOICreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    geometry: dict[str, Any]
    created_by: str | None = "user"

    @field_validator("geometry")
    @classmethod
    def _geom_is_object(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict) or "type" not in v:
            raise ValueError("geometry must be a GeoJSON geometry object")
        return v


class AOIOut(ORMModel):
    id: str
    name: str
    description: str | None
    geometry: dict[str, Any]
    bbox: list[float]
    area_m2: float | None
    crs: str
    created_at: UTCDateTime
    updated_at: UTCDateTime


class DatasetOut(ORMModel):
    id: str
    dataset_id: str
    provider: str
    product_id: str
    product_type: str
    mission: str
    satellite: str | None
    source_url: str | None
    license: str | None
    citation: str | None
    attribution: str | None
    validation_status: str
    is_demo: bool
    manifest: dict[str, Any]
    created_at: UTCDateTime


class ObservationOut(ORMModel):
    id: str
    dataset_id: str
    product_id: str
    product_type: str
    acquisition_start: UTCDateTime
    acquisition_end: UTCDateTime | None
    orbit: int | None
    pass_direction: str | None
    track: int | None
    frame: int | None
    frequency_band: str | None
    frequency_hz: float | None
    polarization: str | None
    wavelength_m: float | None
    crs: str | None
    bbox: list[float]
    geometry: dict[str, Any] | None
    spatial_resolution_m: float | None
    units: str | None
    processing_baseline: str | None
    quality: dict[str, Any]
    calibration_status: str | None
    provider: str
    is_demo: bool


class ProductOut(ORMModel):
    id: str
    observation_id: str
    product_id: str
    product_type: str
    provider: str
    object_uri: str | None
    file_format: str | None
    file_size: int | None
    checksum: str | None
    source_url: str | None
    normalized_metadata: dict[str, Any]
    manifest: dict[str, Any]
    validation_status: str
    adapter_name: str
    adapter_version: str
    is_demo: bool
    created_at: UTCDateTime


class SearchRequest(BaseModel):
    connector: Literal["asf", "bhoonidhi", "stac", "local", "demo"] = "demo"
    bbox: list[float] | None = None
    start: str | None = None
    end: str | None = None
    product_types: list[str] = Field(default_factory=list)
    max_results: int = Field(default=50, ge=1, le=500)


class CatalogItem(BaseModel):
    provider: str
    product_id: str
    product_type: str
    acquisition_start: str | None
    bbox: list[float] | None = None
    frequency_band: str | None = None
    polarization: str | None = None
    source_url: str | None = None
    file_format: str | None = None
    size_bytes: int | None = None
    is_demo: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class CatalogSearchResponse(BaseModel):
    items: list[CatalogItem]
    connector: str
    demo_fallback: bool
    warning: str | None = None
    data_mode: str
    total: int


class IngestRequest(BaseModel):
    connector: Literal["local", "demo", "stac", "asf", "bhoonidhi"] = "demo"
    product_ref: str | None = None
    path: str | None = None
    product_type: str | None = None
    catalog_item: CatalogItem | None = None


class IngestResponse(BaseModel):
    dataset_id: str
    observation_id: str
    product_db_id: str
    product_type: str
    validation_status: str
    is_demo: bool


class ManifestOut(BaseModel):
    dataset_id: str
    provider: str
    product_id: str
    product_type: str
    source: str | None
    acquisition_time: str | None
    geometry: dict[str, Any] | None
    crs: str | None
    frequency: str | None
    polarization: str | None
    processing_baseline: str | None
    object_uri: str | None
    checksum: str | None
    ingest_time: str
    validation_status: str
    attribution: str | None
    license: str | None
    citation: str | None
    processing_history: list[dict[str, Any]]
    normalized_metadata: dict[str, Any]
    is_demo: bool
