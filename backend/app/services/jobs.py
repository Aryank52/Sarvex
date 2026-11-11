"""Job creation, product auto-selection and inline worker dispatch."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import NotFoundError, ValidationError
from app.core.geometry import geometry_area_m2, geometry_bbox, validate_geojson_geometry
from app.db.models import AOI, AuditLog, Observation, Product, ProcessingJob
from app.db.session import session_scope
from app.processing import PROCESSORS
from app.processing.engine import execute_job
from app.schemas.analysis import AnalysisRequest

PRODUCT_TYPE_ACCEPTANCE = {
    "backscatter": {"GCOV", "GSLC"},
    "change_detection": {"GCOV", "GSLC"},
    "timeseries": {"GCOV", "GSLC"},
    "polarimetric": {"GCOV"},
    "deformation": {"GUNW", "RUNW"},
    "offsets": {"RSLC", "GSLC", "GCOV"},
}
MAX_PRODUCTS_PER_ANALYSIS = 20


def _resolve_aoi(session: Session, request: AnalysisRequest) -> AOI:
    if request.aoi_id:
        aoi = session.get(AOI, request.aoi_id)
        if aoi is None:
            raise NotFoundError(f"AOI {request.aoi_id} not found")
        return aoi
    assert request.aoi is not None
    geometry = validate_geojson_geometry(request.aoi)
    bbox = geometry_bbox(geometry)
    aoi = AOI(
        name=request.aoi_name or "Analysis AOI",
        description="AOI created with an analysis request",
        geometry=geometry,
        bbox=bbox,
        area_m2=geometry_area_m2(geometry),
        crs="EPSG:4326",
        created_by=request.requested_by,
    )
    session.add(aoi)
    session.flush()
    return aoi


def _observation_matches_aoi(obs: Observation, bbox: list[float]) -> bool:
    if obs.geometry:
        try:
            from shapely.geometry import box, shape

            aoi_geom = box(*bbox)
            return bool(shape(obs.geometry).intersects(aoi_geom))
        except Exception:  # noqa: BLE001
            pass
    if obs.bbox and len(obs.bbox) == 4:
        return not (
            obs.bbox[2] < bbox[0]
            or obs.bbox[0] > bbox[2]
            or obs.bbox[3] < bbox[1]
            or obs.bbox[1] > bbox[3]
        )
    return True


def _auto_select_products(session: Session, request: AnalysisRequest, aoi: AOI) -> list[Product]:
    accepted = PRODUCT_TYPE_ACCEPTANCE.get(request.analysis_type, set())
    stmt = (
        select(Product)
        .join(Observation)
        .options(selectinload(Product.observation))
        .where(Observation.product_type.in_(accepted))
        .order_by(Observation.acquisition_start)
    )
    if request.time_range:
        stmt = stmt.where(
            Observation.acquisition_start >= request.time_range.start,
            Observation.acquisition_start <= request.time_range.end,
        )
    candidates = session.scalars(stmt).all()
    matched = [p for p in candidates if p.observation and _observation_matches_aoi(p.observation, aoi.bbox)]
    return matched[:MAX_PRODUCTS_PER_ANALYSIS]


def _explicit_products(session: Session, product_ids: list[str]) -> list[Product]:
    ids = list(dict.fromkeys(product_ids))
    found = session.scalars(
        select(Product).options(selectinload(Product.observation)).where(Product.id.in_(ids))
    ).all()
    by_db = {p.id: p for p in found}
    by_business = {
        p.product_id: p
        for p in session.scalars(
            select(Product).options(selectinload(Product.observation)).where(Product.product_id.in_(ids))
        ).all()
    }
    ordered: list[Product] = []
    for pid in ids:
        product = by_db.get(pid) or by_business.get(pid)
        if product is None:
            raise NotFoundError(f"Product '{pid}' not found")
        ordered.append(product)
    return ordered


def create_job(session: Session, request: AnalysisRequest) -> ProcessingJob:
    with session.begin_nested():
        aoi = _resolve_aoi(session, request)
    processor_cls = PROCESSORS.get(request.analysis_type)
    if processor_cls is None:
        raise ValidationError(f"Unsupported analysis type '{request.analysis_type}'")
    accepted = PRODUCT_TYPE_ACCEPTANCE.get(request.analysis_type, set())
    if request.product_ids:
        products = _explicit_products(session, request.product_ids)
        wrong = [p.product_id for p in products if p.observation and p.observation.product_type not in accepted]
        if wrong:
            raise ValidationError(
                f"{request.analysis_type} does not accept product types of: {wrong}",
                detail={"accepted_product_types": sorted(accepted)},
            )
        selection_mode = "explicit"
    else:
        products = _auto_select_products(session, request, aoi)
        selection_mode = "auto"
    if len(products) < processor_cls.min_products:
        raise ValidationError(
            f"{request.analysis_type} requires at least {processor_cls.min_products} compatible product(s); "
            f"found {len(products)}",
            detail={
                "accepted_product_types": sorted(accepted),
                "hint": "Ingest products or enable demo fixtures and search the Assam demo AOI.",
            },
        )
    products = products[:MAX_PRODUCTS_PER_ANALYSIS]
    ordered_products = sorted(
        products, key=lambda p: (p.observation.acquisition_start if p.observation else p.created_at)
    )
    parameters = dict(request.parameters or {})
    parameters["product_selection"] = {
        "mode": selection_mode,
        "requested_product_ids": request.product_ids,
        "selected_product_db_ids": [p.id for p in ordered_products],
        "selected_product_ids": [p.product_id for p in ordered_products],
        "accepted_product_types": sorted(accepted),
        "time_range": (
            {"start": request.time_range.start.isoformat(), "end": request.time_range.end.isoformat()}
            if request.time_range
            else None
        ),
    }
    is_demo = all(p.is_demo for p in ordered_products)
    job = ProcessingJob(
        analysis_type=request.analysis_type,
        status="QUEUED",
        aoi_id=aoi.id,
        product_ids=[p.id for p in ordered_products],
        parameters=parameters,
        time_range_start=request.time_range.start if request.time_range else None,
        time_range_end=request.time_range.end if request.time_range else None,
        progress=0.0,
        current_stage="QUEUED",
        correlation_id=uuid.uuid4().hex,
        requested_by=request.requested_by,
        logs=[
            {
                "ts": None,
                "level": "INFO",
                "message": f"Queued {request.analysis_type} analysis with {len(ordered_products)} product(s)",
            }
        ],
        is_demo=is_demo,
    )
    session.add(job)
    session.flush()
    session.add(
        AuditLog(
            actor=request.requested_by,
            action="analysis.queued",
            entity_type="processing_job",
            entity_id=job.id,
            correlation_id=job.correlation_id,
            detail={
                "analysis_type": request.analysis_type,
                "selection": parameters["product_selection"],
                "demo": is_demo,
            },
        )
    )
    session.commit()
    return job


def launch_inline(job_id: str) -> None:
    """Run a queued job in a daemon thread for single-process dev/demo mode."""
    thread = threading.Thread(target=_run_safely, args=(job_id,), name=f"sarvex-job-{job_id[:8]}", daemon=True)
    thread.start()


def _run_safely(job_id: str) -> None:
    try:
        execute_job(job_id)
    except Exception:  # noqa: BLE001 - worker dispatcher must not die
        import logging

        logging.getLogger("sarvex.jobs").exception("Unhandled job execution error for %s", job_id)
