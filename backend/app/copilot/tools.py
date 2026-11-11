"""Bounded copilot tools.

The language model never receives filesystem, shell or network access. It can
only reason over the structured context assembled by these read-only lookups.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    AOI,
    AnalysisResult,
    ChangeEvent,
    Dataset,
    EventExposure,
    GeospatialContext,
    InfrastructureAsset,
    Observation,
    ProcessingRun,
    Product,
    TimeSeries,
)


def get_event_tool(session: Session, event_id: str) -> dict[str, Any] | None:
    event = session.get(ChangeEvent, event_id)
    if not event:
        return None
    exposures = session.scalars(
        select(EventExposure).where(EventExposure.event_id == event.id)
    ).all()
    assets = {
        a.id: a
        for a in session.scalars(
            select(InfrastructureAsset).where(
                InfrastructureAsset.id.in_([e.asset_id for e in exposures] or [""])
            )
        ).all()
    }
    contexts = []
    for link in event.context_links:
        ctx = session.get(GeospatialContext, link.context_id)
        if ctx:
            contexts.append(
                {
                    "name": ctx.name,
                    "layer_type": ctx.layer_type,
                    "relation": link.relation,
                    "provider": ctx.provider,
                    "license": ctx.license,
                    "is_demo": ctx.is_demo,
                }
            )
    return {
        "id": event.id,
        "event_type": event.event_type,
        "taxonomy_stage": event.taxonomy_stage,
        "classification_method": event.classification_method,
        "classification_confidence": event.classification_confidence,
        "summary": event.summary,
        "aoi_id": _event_aoi_id(session, event),
        "analysis_result_id": (event.properties or {}).get("analysis_result_id"),
        "run_id": event.run_id,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "area_m2": event.area_m2,
        "magnitude": event.magnitude,
        "magnitude_unit": event.magnitude_unit,
        "confidence": event.confidence,
        "uncertainty": event.uncertainty,
        "persistence": event.persistence,
        "severity": event.severity,
        "status": event.status,
        "is_demo": event.is_demo,
        "candidate_labels": (event.properties or {}).get("candidate_labels", []),
        "algorithm": (event.properties or {}).get("algorithm"),
        "algorithm_version": (event.properties or {}).get("algorithm_version"),
        "context_layers": contexts,
        "exposures": [
            {
                "asset": assets[e.asset_id].name if e.asset_id in assets else None,
                "asset_type": assets[e.asset_id].asset_type if e.asset_id in assets else None,
                "distance_m": e.distance_m,
                "overlap_ratio": e.overlap_ratio,
                "exposure_score": e.exposure_score,
                "rationale": e.rationale,
            }
            for e in exposures
        ],
        "observation_ids": [link.observation_id for link in event.observation_links],
    }


def get_analysis_tool(session: Session, result_id: str | None = None, aoi_id: str | None = None) -> dict[str, Any] | None:
    if result_id:
        result = session.get(AnalysisResult, result_id)
    elif aoi_id:
        result = session.scalar(
            select(AnalysisResult)
            .where(AnalysisResult.aoi_id == aoi_id)
            .order_by(AnalysisResult.created_at.desc())
            .limit(1)
        )
    else:
        result = session.scalar(
            select(AnalysisResult).order_by(AnalysisResult.created_at.desc()).limit(1)
        )
    if not result:
        return None
    run = session.get(ProcessingRun, result.run_id)
    products: list[Product] = []
    observations: list[Observation] = []
    datasets: list[Dataset] = []
    if run:
        products = session.scalars(
            select(Product).where(Product.id.in_(run.input_product_ids or [""]))
        ).all()
        observations = session.scalars(
            select(Observation).where(Observation.id.in_(run.observation_ids or [""]))
        ).all()
        datasets = session.scalars(
            select(Dataset).where(Dataset.id.in_([o.dataset_id for o in observations] or [""]))
        ).all()
    layers = []
    for name, meta in (result.layer_metadata or {}).items():
        if isinstance(meta, dict) and meta.get("title"):
            layers.append(
                {
                    "layer": name,
                    "title": meta.get("title"),
                    "units": meta.get("units"),
                    "method": meta.get("method"),
                    "legend_title": meta.get("legend_title"),
                }
            )
    return {
        "result_id": result.id,
        "job_id": result.job_id,
        "run_id": result.run_id,
        "aoi_id": result.aoi_id,
        "result_type": result.result_type,
        "summary": result.summary,
        "statistics": result.statistics,
        "units": result.units,
        "confidence": result.confidence,
        "uncertainty": result.uncertainty,
        "is_demo": result.is_demo,
        "created_at": result.created_at.isoformat(),
        "algorithm": run.algorithm if run else None,
        "algorithm_version": run.algorithm_version if run else None,
        "code_version": run.code_version if run else None,
        "parameters": run.parameters if run else {},
        "product_ids": [p.product_id for p in products],
        "product_types": sorted({p.product_type for p in products}),
        "dates": [
            o.acquisition_start.isoformat() for o in sorted(observations, key=lambda o: o.acquisition_start)
        ],
        "providers": sorted({o.provider for o in observations}),
        "datasets": [d.dataset_id for d in datasets],
        "layers": layers,
        "limitations": (result.layer_metadata or {}).get("limitations", []),
    }


def get_timeseries_tool(session: Session, result_id: str | None, aoi_id: str | None, event_id: str | None) -> list[dict[str, Any]]:
    stmt = select(TimeSeries)
    if event_id:
        stmt = stmt.where(TimeSeries.event_id == event_id)
    elif result_id:
        stmt = stmt.where(TimeSeries.result_id == result_id)
    elif aoi_id:
        stmt = stmt.where(TimeSeries.aoi_id == aoi_id)
    else:
        return []
    series = session.scalars(stmt.limit(5)).all()
    return [
        {
            "series_type": s.series_type,
            "unit": s.unit,
            "points": s.points,
            "trend": s.trend,
            "change_points": s.change_points,
            "gaps": s.gaps,
            "confidence": s.confidence,
        }
        for s in series
    ]


def get_aoi_tool(session: Session, aoi_id: str) -> dict[str, Any] | None:
    aoi = session.get(AOI, aoi_id)
    if not aoi:
        return None
    return {
        "id": aoi.id,
        "name": aoi.name,
        "description": aoi.description,
        "bbox": aoi.bbox,
        "area_m2": aoi.area_m2,
        "crs": aoi.crs,
    }


def _event_aoi_id(session: Session, event: ChangeEvent) -> str | None:
    if not event.run_id:
        return None
    from app.db.models import ProcessingJob, ProcessingRun

    run = session.get(ProcessingRun, event.run_id)
    if not run:
        return None
    job = session.get(ProcessingJob, run.job_id)
    return job.aoi_id if job else None


def inspect_metadata_tool(session: Session, product_ids: list[str]) -> list[dict[str, Any]]:
    if not product_ids:
        return []
    products = session.scalars(
        select(Product)
        .options(selectinload(Product.observation))
        .where(Product.product_id.in_(product_ids))
        .limit(20)
    ).all()
    return [
        {
            "product_id": p.product_id,
            "product_type": p.product_type,
            "provider": p.provider,
            "checksum": p.checksum,
            "validation_status": p.validation_status,
            "is_demo": p.is_demo,
            "acquisition_start": p.observation.acquisition_start.isoformat() if p.observation else None,
            "frequency_band": p.observation.frequency_band if p.observation else None,
            "polarization": p.observation.polarization if p.observation else None,
            "units": p.observation.units if p.observation else None,
            "wavelength_m": p.observation.wavelength_m if p.observation else None,
            "crs": p.observation.crs if p.observation else None,
        }
        for p in products
    ]
