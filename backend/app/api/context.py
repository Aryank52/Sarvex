"""Areas of interest, context layers, infrastructure assets and exposures."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.core.errors import NotFoundError, ValidationError
from app.core.geometry import geometry_area_m2, geometry_bbox, validate_geojson_geometry
from app.db.models import AOI, EventExposure, GeospatialContext, InfrastructureAsset, ProcessingJob
from app.schemas.analysis import (
    AssetOut,
    ContextOut,
    ExposureOut,
)
from app.schemas.catalog import AOICreate, AOIOut
from app.schemas.common import Page

router = APIRouter(tags=["context"], dependencies=[Depends(rate_limit)])


# ---------------------------------------------------------------------------
# AOIs
# ---------------------------------------------------------------------------
@router.get("/aois", response_model=Page[AOIOut])
def list_aois(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[AOIOut]:
    total = int(db.scalar(select(func.count(AOI.id))) or 0)
    rows = db.scalars(
        select(AOI).order_by(AOI.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[AOIOut](
        items=[AOIOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/aois", response_model=AOIOut, status_code=201)
def create_aoi(request: AOICreate, db: Session = Depends(get_db)) -> AOIOut:
    try:
        geometry = validate_geojson_geometry(request.geometry)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    aoi = AOI(
        name=request.name,
        description=request.description,
        geometry=geometry,
        bbox=geometry_bbox(geometry),
        area_m2=geometry_area_m2(geometry),
        crs="EPSG:4326",
        created_by=request.created_by,
    )
    db.add(aoi)
    db.commit()
    return AOIOut.model_validate(aoi)


@router.get("/aois/{aoi_id}", response_model=AOIOut)
def get_aoi(aoi_id: str, db: Session = Depends(get_db)) -> AOIOut:
    aoi = db.get(AOI, aoi_id)
    if not aoi:
        raise NotFoundError(f"AOI {aoi_id} not found")
    return AOIOut.model_validate(aoi)


@router.get("/aois/{aoi_id}/geojson")
def get_aoi_geojson(aoi_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    aoi = db.get(AOI, aoi_id)
    if not aoi:
        raise NotFoundError(f"AOI {aoi_id} not found")
    return {
        "type": "Feature",
        "id": aoi.id,
        "geometry": aoi.geometry,
        "properties": {
            "name": aoi.name,
            "description": aoi.description,
            "bbox": aoi.bbox,
            "area_m2": aoi.area_m2,
            "crs": aoi.crs,
        },
    }


@router.get("/aois/{aoi_id}/analyses")
def aoi_analyses(aoi_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not db.get(AOI, aoi_id):
        raise NotFoundError(f"AOI {aoi_id} not found")
    jobs = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.aoi_id == aoi_id)
        .order_by(ProcessingJob.queued_at.desc())
        .limit(50)
    ).all()
    return {
        "aoi_id": aoi_id,
        "analyses": [
            {
                "job_id": job.id,
                "analysis_type": job.analysis_type,
                "status": job.status,
                "progress": job.progress,
                "queued_at": job.queued_at.isoformat() if job.queued_at else None,
                "is_demo": job.is_demo,
            }
            for job in jobs
        ],
    }


# ---------------------------------------------------------------------------
# Context layers and assets
# ---------------------------------------------------------------------------
@router.get("/context/layers", response_model=Page[ContextOut])
def list_context_layers(
    layer_type: str | None = None,
    demo: bool | None = None,
    bbox: str | None = Query(default=None, description="minx,miny,maxx,maxy"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[ContextOut]:
    stmt = select(GeospatialContext)
    if layer_type:
        stmt = stmt.where(GeospatialContext.layer_type == layer_type)
    if demo is not None:
        stmt = stmt.where(GeospatialContext.is_demo.is_(demo))
    rows = db.scalars(stmt.order_by(GeospatialContext.name).limit(1000)).all()
    if bbox:
        box = _parse_bbox(bbox)
        rows = [
            row
            for row in rows
            if row.geometry is None
            or _intersects_bbox(geometry_bbox(row.geometry), box)
        ]
    total = len(rows)
    rows = rows[offset : offset + limit]
    return Page[ContextOut](
        items=[ContextOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/context/layers/{context_id}", response_model=ContextOut)
def get_context_layer(context_id: str, db: Session = Depends(get_db)) -> ContextOut:
    row = db.get(GeospatialContext, context_id)
    if not row:
        raise NotFoundError(f"Context layer {context_id} not found")
    return ContextOut.model_validate(row)


@router.get("/context/assets", response_model=Page[AssetOut])
def list_assets(
    asset_type: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[AssetOut]:
    stmt = select(InfrastructureAsset)
    if asset_type:
        stmt = stmt.where(InfrastructureAsset.asset_type == asset_type)
    if demo is not None:
        stmt = stmt.where(InfrastructureAsset.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(InfrastructureAsset.name).limit(limit).offset(offset)
    ).all()
    return Page[AssetOut](
        items=[AssetOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/context/exposures", response_model=list[ExposureOut])
def list_exposures(
    min_score: float | None = Query(default=None, ge=0, le=1),
    demo: bool | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ExposureOut]:
    stmt = select(EventExposure)
    if min_score is not None:
        stmt = stmt.where(EventExposure.exposure_score >= min_score)
    exposures = db.scalars(
        stmt.order_by(EventExposure.exposure_score.desc()).limit(limit)
    ).all()
    assets = {
        a.id: AssetOut.model_validate(a)
        for a in db.scalars(
            select(InfrastructureAsset).where(
                InfrastructureAsset.id.in_([e.asset_id for e in exposures] or [""])
            )
        ).all()
    }
    if demo is not None:
        assets = {k: v for k, v in assets.items() if v.is_demo is demo}
        exposures = [e for e in exposures if e.asset_id in assets]
    return [
        ExposureOut.model_validate(
            {
                "id": e.id,
                "event_id": e.event_id,
                "asset_id": e.asset_id,
                "distance_m": e.distance_m,
                "overlap_ratio": e.overlap_ratio,
                "exposure_score": e.exposure_score,
                "rationale": e.rationale,
                "asset": assets.get(e.asset_id),
            }
        )
        for e in exposures
    ]


def _parse_bbox(value: str) -> list[float]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise ValidationError("bbox must be 'minx,miny,maxx,maxy'")
    try:
        return [float(p) for p in parts]
    except ValueError as exc:
        raise ValidationError("bbox values must be numeric") from exc


def _intersects_bbox(a: list[float], b: list[float]) -> bool:
    if len(a) != 4 or len(b) != 4:
        return True
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])
