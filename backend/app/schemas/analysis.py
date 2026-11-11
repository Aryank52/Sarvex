"""Analysis, jobs, results, events, timeseries and context schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel, UTCDateTime

AnalysisType = Literal[
    "backscatter",
    "deformation",
    "polarimetric",
    "offsets",
    "change_detection",
    "timeseries",
]


class TimeRange(BaseModel):
    start: UTCDateTime
    end: UTCDateTime

    @model_validator(mode="after")
    def _ordered(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError("time_range.end must be after time_range.start")
        return self


class AnalysisRequest(BaseModel):
    aoi_id: str | None = None
    aoi: dict[str, Any] | None = None
    aoi_name: str | None = "Analysis AOI"
    product_ids: list[str] = Field(default_factory=list)
    analysis_type: AnalysisType
    time_range: TimeRange | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: str | None = "user"

    @model_validator(mode="after")
    def _aoi_present(self) -> "AnalysisRequest":
        if not self.aoi_id and not self.aoi:
            raise ValueError("Either aoi_id or aoi geometry is required")
        return self


class JobOut(ORMModel):
    id: str
    analysis_type: str
    status: str
    aoi_id: str | None
    product_ids: list[str]
    parameters: dict[str, Any]
    progress: float
    current_stage: str | None
    error: str | None
    correlation_id: str
    logs: list[dict[str, Any]]
    queued_at: UTCDateTime
    started_at: UTCDateTime | None
    finished_at: UTCDateTime | None
    is_demo: bool
    created_at: UTCDateTime


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    correlation_id: str
    demo_mode: bool


class RunOut(ORMModel):
    id: str
    job_id: str
    analysis_type: str
    algorithm: str
    algorithm_version: str
    parameters: dict[str, Any]
    input_product_ids: list[str]
    observation_ids: list[str]
    dataset_ids: list[str]
    model_name: str | None
    model_version: str | None
    crs: str
    units: str | None
    code_version: str
    provenance: dict[str, Any]
    status: str
    started_at: UTCDateTime
    finished_at: UTCDateTime | None


class ResultOut(ORMModel):
    id: str
    run_id: str
    job_id: str
    aoi_id: str | None
    result_type: str
    summary: str
    statistics: dict[str, Any]
    artifacts: dict[str, Any]
    layer_metadata: dict[str, Any]
    units: str | None
    confidence: float | None
    uncertainty: float | None
    is_demo: bool
    created_at: UTCDateTime


class ResultDetail(ResultOut):
    run: RunOut | None = None
    events: list["EventOut"] = Field(default_factory=list)


class FeatureOut(ORMModel):
    id: str
    result_id: str
    feature_type: str
    geometry: dict[str, Any] | None
    value: float | None
    unit: str | None
    uncertainty: float | None
    confidence: float | None
    properties: dict[str, Any]


class EventOut(ORMModel):
    id: str
    event_type: str
    taxonomy_stage: str
    classification_method: str | None
    classification_confidence: float | None
    geometry: dict[str, Any]
    start_time: UTCDateTime | None
    end_time: UTCDateTime | None
    area_m2: float | None
    magnitude: float | None
    magnitude_unit: str | None
    confidence: float | None
    uncertainty: float | None
    persistence: float | None
    severity: float | None
    priority: int | None
    status: str
    summary: str
    run_id: str | None
    model_run_id: str | None
    properties: dict[str, Any]
    is_demo: bool
    created_at: UTCDateTime


class EventDetail(EventOut):
    observation_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    exposures: list["ExposureOut"] = Field(default_factory=list)


class EventStatusUpdate(BaseModel):
    status: Literal["UNREVIEWED", "UNDER_REVIEW", "CORROBORATED", "REJECTED", "ARCHIVED"]
    rationale: str | None = None
    external_evidence_url: str | None = None


class ConfirmEventRequest(BaseModel):
    """Independent external evidence required to promote an event to CONFIRMED.

    A model or an algorithm may never confirm its own detection. The caller must
    supply an authoritative source (official report, seismic catalogue, gauge
    record, field validation) with a title and a resolvable reference.
    """

    evidence_title: str = Field(min_length=3, max_length=300)
    source_type: Literal[
        "OFFICIAL_REPORT",
        "SEISMIC_CATALOGUE",
        "HYDROLOGICAL_GAUGE",
        "FIELD_VALIDATION",
        "PEER_REVIEWED_STUDY",
        "OPERATIONAL_RECORD",
    ]
    url: str | None = Field(default=None, max_length=2000)
    citation: str | None = Field(default=None, max_length=4000)
    publisher: str | None = Field(default=None, max_length=300)
    rationale: str = Field(min_length=20, max_length=4000)
    observed_at: datetime | None = None
    is_demo_evidence: bool = False


class EventReviewOut(BaseModel):
    event_id: str
    status: str
    taxonomy_stage: str
    evidence_id: str | None = None
    message: str


class TimeSeriesOut(ORMModel):
    id: str
    aoi_id: str | None
    result_id: str | None
    event_id: str | None
    series_type: str
    unit: str
    points: list[dict[str, Any]]
    trend: dict[str, Any]
    change_points: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    confidence: float | None
    is_demo: bool
    created_at: UTCDateTime


class ContextOut(ORMModel):
    id: str
    layer_type: str
    name: str
    geometry: dict[str, Any] | None
    provider: str
    license: str
    source: str
    version: str | None
    crs: str
    layer_date: UTCDateTime | None
    properties: dict[str, Any]
    is_demo: bool


class AssetOut(ORMModel):
    id: str
    asset_type: str
    name: str
    geometry: dict[str, Any]
    provider: str
    license: str
    source: str
    properties: dict[str, Any]
    is_demo: bool


class ExposureOut(ORMModel):
    id: str
    event_id: str
    asset_id: str
    distance_m: float
    overlap_ratio: float
    exposure_score: float
    rationale: str
    asset: AssetOut | None = None


class EvidenceOut(ORMModel):
    id: str
    source_type: str
    title: str
    url: str | None
    citation: str | None
    snippet: str | None
    evidence_metadata: dict[str, Any]
    confidence: float | None
    is_demo: bool


class EvidenceCreate(BaseModel):
    source_type: Literal[
        "OFFICIAL_REPORT",
        "SEISMIC_CATALOGUE",
        "HYDROLOGICAL_GAUGE",
        "FIELD_VALIDATION",
        "PEER_REVIEWED_STUDY",
        "OPERATIONAL_RECORD",
        "CONTEXT_DATASET",
        "OTHER",
    ]
    title: str = Field(min_length=3, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    citation: str | None = Field(default=None, max_length=4000)
    snippet: str | None = Field(default=None, max_length=4000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    event_id: str | None = None
    evidence_metadata: dict[str, Any] = Field(default_factory=dict)
    is_demo: bool = False


class PaginatedResults(BaseModel):
    items: list[ResultOut]
    total: int


ResultDetail.model_rebuild()
EventDetail.model_rebuild()
