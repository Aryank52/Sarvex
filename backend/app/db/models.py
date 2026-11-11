"""SARVEX domain model.

Entities carry provenance-bearing identifiers and units. Spatial geometry is
PostGIS in production; see ``app.db.types`` for the SQLite fallback. Large
rasters and reports live in object storage and are referenced by URI.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin, new_uuid, utcnow
from app.db.types import GeoJSONGeometry, VectorEmbedding


# ---------------------------------------------------------------------------
# Geospatial and catalog
# ---------------------------------------------------------------------------
class AOI(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "aois"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[dict[str, Any]] = mapped_column(GeoJSONGeometry, nullable=False)
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    area_m2: Mapped[float | None] = mapped_column(Float)
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4326")
    created_by: Mapped[str | None] = mapped_column(String(120))

    analyses: Mapped[list["ProcessingJob"]] = relationship(back_populates="aoi")


class Dataset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "datasets"

    dataset_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    product_id: Mapped[str] = mapped_column(String(200), index=True)
    product_type: Mapped[str] = mapped_column(String(16), index=True)
    mission: Mapped[str] = mapped_column(String(40), default="NISAR")
    satellite: Mapped[str | None] = mapped_column(String(40))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_identifier: Mapped[str | None] = mapped_column(String(200))
    license: Mapped[str | None] = mapped_column(String(120))
    citation: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    processing_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    validation_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    observations: Mapped[list["Observation"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class Observation(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "observations"

    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[str] = mapped_column(String(200), index=True)
    product_type: Mapped[str] = mapped_column(String(16), index=True)
    acquisition_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    acquisition_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    orbit: Mapped[int | None] = mapped_column(Integer)
    pass_direction: Mapped[str | None] = mapped_column(String(12))
    track: Mapped[int | None] = mapped_column(Integer)
    frame: Mapped[int | None] = mapped_column(Integer)
    frequency_band: Mapped[str | None] = mapped_column(String(4))
    frequency_hz: Mapped[float | None] = mapped_column(Float)
    polarization: Mapped[str | None] = mapped_column(String(32))
    wavelength_m: Mapped[float | None] = mapped_column(Float)
    crs: Mapped[str | None] = mapped_column(String(64))
    bbox: Mapped[list[float]] = mapped_column(JSON, default=list)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(GeoJSONGeometry)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float)
    units: Mapped[str | None] = mapped_column(String(32))
    processing_baseline: Mapped[str | None] = mapped_column(String(80))
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    calibration_status: Mapped[str | None] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(80))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    dataset: Mapped[Dataset] = relationship(back_populates="observations")
    products: Mapped[list["Product"]] = relationship(
        back_populates="observation", cascade="all, delete-orphan"
    )


class Product(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "products"

    observation_id: Mapped[str] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[str] = mapped_column(String(200), index=True)
    product_type: Mapped[str] = mapped_column(String(16), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    object_uri: Mapped[str | None] = mapped_column(Text)
    file_format: Mapped[str | None] = mapped_column(String(40))
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str | None] = mapped_column(Text)
    normalized_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    adapter_name: Mapped[str] = mapped_column(String(80), default="geotiff")
    adapter_version: Mapped[str] = mapped_column(String(20), default="1.0")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    observation: Mapped[Observation] = relationship(back_populates="products")


# ---------------------------------------------------------------------------
# Processing and results
# ---------------------------------------------------------------------------
class ProcessingJob(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "processing_jobs"

    analysis_type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("aois.id"), index=True)
    product_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    time_range_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    time_range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    requested_by: Mapped[str | None] = mapped_column(String(120))
    logs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    aoi: Mapped[AOI | None] = relationship(back_populates="analyses")
    run: Mapped["ProcessingRun | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )


class ProcessingRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "processing_runs"

    job_id: Mapped[str] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), unique=True, index=True
    )
    analysis_type: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(120))
    algorithm_version: Mapped[str] = mapped_column(String(32))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_product_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    observation_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    dataset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_id: Mapped[str | None] = mapped_column(String(36))
    model_name: Mapped[str | None] = mapped_column(String(120))
    model_version: Mapped[str | None] = mapped_column(String(60))
    feature_version: Mapped[str | None] = mapped_column(String(60))
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4326")
    units: Mapped[str | None] = mapped_column(String(32))
    code_version: Mapped[str] = mapped_column(String(64), default="unknown")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[ProcessingJob] = relationship(back_populates="run")
    results: Mapped[list["AnalysisResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class AnalysisResult(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "analysis_results"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("processing_runs.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("processing_jobs.id"), index=True)
    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("aois.id"), index=True)
    result_type: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    layer_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    units: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    run: Mapped[ProcessingRun] = relationship(back_populates="results")
    features: Mapped[list["SARFeature"]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )
    change_maps: Mapped[list["ChangeMap"]] = relationship(
        back_populates="result", cascade="all, delete-orphan"
    )


class SARFeature(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "sar_features"

    result_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="CASCADE"), index=True
    )
    feature_type: Mapped[str] = mapped_column(String(60), index=True)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(GeoJSONGeometry)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(32))
    uncertainty: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    result: Mapped[AnalysisResult] = relationship(back_populates="features")


class ChangeMap(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "change_maps"

    result_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_results.id", ondelete="CASCADE"), index=True
    )
    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("aois.id"), index=True)
    method: Mapped[str] = mapped_column(String(120))
    threshold: Mapped[float | None] = mapped_column(Float)
    change_fraction: Mapped[float] = mapped_column(Float, default=0.0)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    result: Mapped[AnalysisResult] = relationship(back_populates="change_maps")


class TimeSeries(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "time_series"

    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("aois.id"), index=True)
    result_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_results.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("change_events.id"), index=True)
    series_type: Mapped[str] = mapped_column(String(60), index=True)
    unit: Mapped[str] = mapped_column(String(32))
    points: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    trend: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    change_points: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Events and context
# ---------------------------------------------------------------------------
class ChangeEvent(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "change_events"

    event_type: Mapped[str] = mapped_column(String(40), default="UNCLASSIFIED_CHANGE", index=True)
    taxonomy_stage: Mapped[str] = mapped_column(String(24), default="DETECTED", index=True)
    classification_method: Mapped[str | None] = mapped_column(String(120))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[dict[str, Any]] = mapped_column(GeoJSONGeometry, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    area_m2: Mapped[float | None] = mapped_column(Float)
    magnitude: Mapped[float | None] = mapped_column(Float)
    magnitude_unit: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    persistence: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="UNREVIEWED", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    run_id: Mapped[str | None] = mapped_column(ForeignKey("processing_runs.id"), index=True)
    model_run_id: Mapped[str | None] = mapped_column(ForeignKey("model_runs.id"))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    observation_links: Mapped[list["EventObservationLink"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    evidence_links: Mapped[list["EventEvidenceLink"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    context_links: Mapped[list["EventContextLink"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    exposures: Mapped[list["EventExposure"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventCluster(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "event_clusters"

    name: Mapped[str | None] = mapped_column(String(200))
    geometry: Mapped[dict[str, Any] | None] = mapped_column(GeoJSONGeometry)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class ConfidenceScore(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "confidence_scores"

    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    score: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(120))
    components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class UncertaintyEstimate(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "uncertainty_estimates"

    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(120))
    components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class GeospatialContext(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "geospatial_context"

    layer_type: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(200))
    geometry: Mapped[dict[str, Any] | None] = mapped_column(GeoJSONGeometry)
    provider: Mapped[str] = mapped_column(String(120))
    license: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(String(60))
    crs: Mapped[str] = mapped_column(String(32), default="EPSG:4326")
    layer_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class InfrastructureAsset(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "infrastructure_assets"

    asset_type: Mapped[str] = mapped_column(String(60), index=True)
    name: Mapped[str] = mapped_column(String(200))
    geometry: Mapped[dict[str, Any]] = mapped_column(GeoJSONGeometry, nullable=False)
    provider: Mapped[str] = mapped_column(String(120))
    license: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(Text)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class EventObservationLink(UUIDMixin, Base):
    __tablename__ = "event_observation_links"
    __table_args__ = (UniqueConstraint("event_id", "observation_id"),)

    event_id: Mapped[str] = mapped_column(
        ForeignKey("change_events.id", ondelete="CASCADE"), index=True
    )
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"), index=True)
    event: Mapped[ChangeEvent] = relationship(back_populates="observation_links")


class EventContextLink(UUIDMixin, Base):
    __tablename__ = "event_context_links"
    __table_args__ = (UniqueConstraint("event_id", "context_id"),)

    event_id: Mapped[str] = mapped_column(
        ForeignKey("change_events.id", ondelete="CASCADE"), index=True
    )
    context_id: Mapped[str] = mapped_column(ForeignKey("geospatial_context.id"), index=True)
    relation: Mapped[str | None] = mapped_column(String(60))
    event: Mapped[ChangeEvent] = relationship(back_populates="context_links")


class EventExposure(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "event_exposures"
    __table_args__ = (UniqueConstraint("event_id", "asset_id"),)

    event_id: Mapped[str] = mapped_column(
        ForeignKey("change_events.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("infrastructure_assets.id"), index=True)
    distance_m: Mapped[float] = mapped_column(Float)
    overlap_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    exposure_score: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, default="")
    event: Mapped[ChangeEvent] = relationship(back_populates="exposures")


# ---------------------------------------------------------------------------
# Evidence, documents and RAG
# ---------------------------------------------------------------------------
class EvidenceItem(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "evidence_items"

    source_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text)
    citation: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    evidence_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class EventEvidenceLink(UUIDMixin, Base):
    __tablename__ = "event_evidence_links"
    __table_args__ = (UniqueConstraint("event_id", "evidence_id"),)

    event_id: Mapped[str] = mapped_column(
        ForeignKey("change_events.id", ondelete="CASCADE"), index=True
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"), index=True)
    event: Mapped[ChangeEvent] = relationship(back_populates="evidence_links")


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(400), index=True)
    author: Mapped[str | None] = mapped_column(String(300))
    publisher: Mapped[str | None] = mapped_column(String(300))
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    url: Mapped[str | None] = mapped_column(Text)
    document_type: Mapped[str] = mapped_column(String(60), index=True)
    scientific_topic: Mapped[str | None] = mapped_column(String(120))
    mission: Mapped[str | None] = mapped_column(String(40))
    product_type: Mapped[str | None] = mapped_column(String(16))
    license: Mapped[str | None] = mapped_column(String(120))
    source_priority: Mapped[int] = mapped_column(Integer, default=7)
    checksum: Mapped[str | None] = mapped_column(String(128))
    source_uri: Mapped[str | None] = mapped_column(Text)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentChunk(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_chunks"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(400))
    page: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    embedding_version: Mapped[str | None] = mapped_column(String(60))
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")
    embeddings: Mapped[list["EmbeddingRecord"]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )


class EmbeddingRecord(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "embedding_records"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True
    )
    model_name: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(60))
    dimension: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[float]] = mapped_column(VectorEmbedding(1536))
    chunk: Mapped[DocumentChunk] = relationship(back_populates="embeddings")


# ---------------------------------------------------------------------------
# Model registry, copilot, reports, audit
# ---------------------------------------------------------------------------
class Model(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "models"
    __table_args__ = (UniqueConstraint("category", "name", "version"),)

    category: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(60))
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    task: Mapped[str | None] = mapped_column(String(120))
    framework: Mapped[str | None] = mapped_column(String(80))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    versions: Mapped[list["ModelVersion"]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class ModelVersion(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version"),)

    model_id: Mapped[str] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(60))
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model: Mapped[Model] = relationship(back_populates="versions")


class ModelRun(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "model_runs"

    model_id: Mapped[str | None] = mapped_column(ForeignKey("models.id"), index=True)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"))
    purpose: Mapped[str] = mapped_column(String(60), index=True)
    model_name: Mapped[str | None] = mapped_column(String(160))
    model_version: Mapped[str | None] = mapped_column(String(60))
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), default="COMPLETED")
    error: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)


class PromptTemplate(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("name", "version"),)

    name: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[str] = mapped_column(String(24))
    template: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CopilotSession(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "copilot_sessions"

    aoi_id: Mapped[str | None] = mapped_column(ForeignKey("aois.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("change_events.id"), index=True)
    result_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_results.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(300))
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class Report(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reports"

    title: Mapped[str] = mapped_column(String(400))
    report_type: Mapped[str] = mapped_column(String(40), default="ANALYSIS")
    result_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_results.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("change_events.id"), index=True)
    format: Mapped[str] = mapped_column(String(20), default="markdown")
    content: Mapped[str] = mapped_column(Text)
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    actor: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SystemConfiguration(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "system_configuration"

    key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text)


# Spatial indexes are created by PostGIS (geoalchemy2) for geometry columns;
# these btree indexes cover common filter paths on every backend.
Index("ix_observations_acq_type", Observation.acquisition_start, Observation.product_type)
Index("ix_events_type_time", ChangeEvent.event_type, ChangeEvent.start_time)
Index("ix_jobs_status_queued", ProcessingJob.status, ProcessingJob.queued_at)

class EvidenceEdge(UUIDMixin, TimestampMixin, Base):
    """Scientific evidence graph edge: links questions, analyses, datasets,
    observations, runs, features, model runs, events, context and evidence.
    """

    __tablename__ = "evidence_edges"

    source_type: Mapped[str] = mapped_column(String(60), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(60), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    edge_type: Mapped[str] = mapped_column(String(60), index=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
