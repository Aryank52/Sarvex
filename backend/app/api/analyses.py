"""Processing job, analysis result, artifact and timeseries endpoints."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.db.models import AnalysisResult, ProcessingJob, SARFeature, TimeSeries
from app.processing.engine import TERMINAL_STATES, execute_job
from app.schemas.analysis import (
    AnalysisRequest,
    FeatureOut,
    JobCreateResponse,
    JobOut,
    ResultDetail,
    ResultOut,
    RunOut,
    TimeSeriesOut,
)
from app.schemas.common import Page
from app.services.jobs import create_job, launch_inline
from app.storage.object_store import get_object_store

router = APIRouter(tags=["analysis"], dependencies=[Depends(rate_limit)])


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
@router.post("/analyses", response_model=JobCreateResponse, status_code=202)
def start_analysis(request: AnalysisRequest, db: Session = Depends(get_db)) -> JobCreateResponse:
    job = create_job(db, request)
    settings = get_settings()
    if settings.run_inline_worker:
        launch_inline(job.id)
    return JobCreateResponse(
        job_id=job.id,
        status=job.status,
        correlation_id=job.correlation_id,
        demo_mode=job.is_demo,
    )


@router.get("/analyses", response_model=Page[JobOut])
def list_analyses(
    status: str | None = None,
    analysis_type: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[JobOut]:
    stmt = select(ProcessingJob)
    if status:
        stmt = stmt.where(ProcessingJob.status == status.upper())
    if analysis_type:
        stmt = stmt.where(ProcessingJob.analysis_type == analysis_type)
    if demo is not None:
        stmt = stmt.where(ProcessingJob.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(ProcessingJob.queued_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[JobOut](
        items=[JobOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/{job_id}", response_model=JobOut)
def get_analysis(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    return JobOut.model_validate(_get_job(db, job_id))


@router.get("/analyses/{job_id}/logs")
def get_analysis_logs(job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    job = _get_job(db, job_id)
    return {
        "job_id": job.id,
        "status": job.status,
        "progress": job.progress,
        "current_stage": job.current_stage,
        "logs": job.logs or [],
    }


@router.post("/analyses/{job_id}/cancel", response_model=JobOut)
def cancel_analysis(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    job = _get_job(db, job_id)
    if job.status in TERMINAL_STATES:
        raise ConflictError(
            f"Job is already in terminal state {job.status}",
            detail={"status": job.status},
        )
    job.status = "CANCELLED"
    job.current_stage = "CANCELLED"
    job.progress = 100.0
    job.logs = list(job.logs or []) + [
        {
            "level": "WARNING",
            "message": "Cancellation requested by API client",
            "correlation_id": job.correlation_id,
        }
    ]
    from app.core.provenance import utcnow

    job.finished_at = utcnow()
    db.commit()
    return JobOut.model_validate(job)


@router.post("/analyses/{job_id}/run", response_model=JobOut)
def run_analysis_sync(job_id: str, db: Session = Depends(get_db)) -> JobOut:
    """Execute a QUEUED job synchronously.

    This exists for deployments without a separate worker and for evaluation.
    In production the worker runner claims queued jobs instead.
    """
    job = _get_job(db, job_id)
    if job.status not in {"QUEUED"}:
        raise ConflictError(
            f"Only QUEUED jobs can be executed; current status is {job.status}",
            detail={"status": job.status},
        )
    # End the read transaction before the worker writes from another session.
    db.rollback()
    execute_job(job.id)
    db.expire_all()
    return JobOut.model_validate(_get_job(db, job_id))


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@router.get("/results", response_model=Page[ResultOut])
def list_results(
    analysis_type: str | None = None,
    aoi_id: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[ResultOut]:
    stmt = select(AnalysisResult)
    if analysis_type:
        stmt = stmt.where(AnalysisResult.result_type == analysis_type)
    if aoi_id:
        stmt = stmt.where(AnalysisResult.aoi_id == aoi_id)
    if demo is not None:
        stmt = stmt.where(AnalysisResult.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(AnalysisResult.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[ResultOut](
        items=[ResultOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/results/{result_id}", response_model=ResultDetail)
def get_result(result_id: str, db: Session = Depends(get_db)) -> ResultDetail:
    result = _get_result(db, result_id)
    from app.db.models import ChangeEvent

    events = db.scalars(
        select(ChangeEvent)
        .where(ChangeEvent.run_id == result.run_id)
        .order_by(ChangeEvent.severity.desc())
    ).all()
    detail = ResultDetail.model_validate(result)
    detail.run = RunOut.model_validate(result.run) if result.run else None
    from app.schemas.analysis import EventOut

    detail.events = [EventOut.model_validate(event) for event in events]
    return detail


@router.get("/results/{result_id}/features", response_model=list[FeatureOut])
def list_result_features(
    result_id: str,
    feature_type: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[FeatureOut]:
    _get_result(db, result_id)
    stmt = select(SARFeature).where(SARFeature.result_id == result_id)
    if feature_type:
        stmt = stmt.where(SARFeature.feature_type == feature_type)
    rows = db.scalars(stmt.limit(limit)).all()
    return [FeatureOut.model_validate(row) for row in rows]


@router.get("/results/{result_id}/layers")
def list_layers(result_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = _get_result(db, result_id)
    layers = []
    for name, meta in (result.layer_metadata or {}).items():
        if isinstance(meta, dict) and meta.get("title"):
            layers.append({**meta, "name": name})
    return {
        "result_id": result.id,
        "is_demo": result.is_demo,
        "layers": layers,
        "limitations": (result.layer_metadata or {}).get("limitations", []),
        "provenance": (result.layer_metadata or {}).get("provenance", {}),
    }


@router.get("/results/{result_id}/layers/{layer}")
def get_layer(
    result_id: str,
    layer: str,
    format: Literal["png", "geotiff"] = "png",
    db: Session = Depends(get_db),
) -> Response:
    result = _get_result(db, result_id)
    meta = (result.layer_metadata or {}).get(layer)
    if not isinstance(meta, dict) or not meta.get("title"):
        raise NotFoundError(
            f"Layer '{layer}' not found for result {result_id}",
            detail={"available": list((result.layer_metadata or {}).keys())},
        )
    uri = meta.get("png_uri") if format == "png" else meta.get("raster_uri")
    if not uri:
        raise NotFoundError(f"Layer '{layer}' has no {format} artifact")
    store = get_object_store()
    data = store.get_bytes(uri)
    media_type = "image/png" if format == "png" else "image/tiff"
    extension = "png" if format == "png" else "tif"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'inline; filename="{layer}.{extension}"',
            "X-SARVEX-Demo": "true" if result.is_demo else "false",
        },
    )


@router.get("/results/{result_id}/timeseries", response_model=list[TimeSeriesOut])
def result_timeseries(result_id: str, db: Session = Depends(get_db)) -> list[TimeSeriesOut]:
    _get_result(db, result_id)
    rows = db.scalars(
        select(TimeSeries).where(TimeSeries.result_id == result_id).limit(20)
    ).all()
    return [TimeSeriesOut.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# Timeseries (global)
# ---------------------------------------------------------------------------
@router.get("/timeseries", response_model=list[TimeSeriesOut])
def list_timeseries(
    aoi_id: str | None = None,
    result_id: str | None = None,
    event_id: str | None = None,
    series_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TimeSeriesOut]:
    stmt = select(TimeSeries)
    if aoi_id:
        stmt = stmt.where(TimeSeries.aoi_id == aoi_id)
    if result_id:
        stmt = stmt.where(TimeSeries.result_id == result_id)
    if event_id:
        stmt = stmt.where(TimeSeries.event_id == event_id)
    if series_type:
        stmt = stmt.where(TimeSeries.series_type == series_type)
    rows = db.scalars(stmt.order_by(TimeSeries.created_at.desc()).limit(limit)).all()
    return [TimeSeriesOut.model_validate(row) for row in rows]


@router.get("/timeseries/{series_id}", response_model=TimeSeriesOut)
def get_timeseries(series_id: str, db: Session = Depends(get_db)) -> TimeSeriesOut:
    row = db.get(TimeSeries, series_id)
    if not row:
        raise NotFoundError(f"Time series {series_id} not found")
    return TimeSeriesOut.model_validate(row)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_job(db: Session, job_id: str) -> ProcessingJob:
    job = db.get(ProcessingJob, job_id)
    if not job:
        raise NotFoundError(f"Analysis job {job_id} not found")
    return job


def _get_result(db: Session, result_id: str) -> AnalysisResult:
    result = db.get(AnalysisResult, result_id)
    if not result:
        raise NotFoundError(f"Analysis result {result_id} not found")
    return result
