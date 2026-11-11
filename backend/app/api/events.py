"""Change event endpoints: review workflow, confirmation gate and GeoJSON."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.models import (
    AuditLog,
    ChangeEvent,
    EventEvidenceLink,
    EventExposure,
    EvidenceItem,
    GeospatialContext,
    InfrastructureAsset,
)
from app.schemas.analysis import (
    AssetOut,
    ConfirmEventRequest,
    ContextOut,
    EventDetail,
    EventOut,
    EventReviewOut,
    EventStatusUpdate,
    EvidenceOut,
    ExposureOut,
)
from app.schemas.common import Page

router = APIRouter(tags=["events"], dependencies=[Depends(rate_limit)])

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "UNREVIEWED": {"UNDER_REVIEW", "REJECTED", "ARCHIVED"},
    "UNDER_REVIEW": {"CORROBORATED", "REJECTED", "ARCHIVED", "UNREVIEWED"},
    "CORROBORATED": {"ARCHIVED", "UNDER_REVIEW"},
    "REJECTED": {"UNDER_REVIEW", "ARCHIVED"},
    "ARCHIVED": {"UNDER_REVIEW"},
}


@router.get("/events", response_model=Page[EventOut])
def list_events(
    event_type: str | None = None,
    status: str | None = None,
    taxonomy_stage: str | None = None,
    demo: bool | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    aoi_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[EventOut]:
    stmt = select(ChangeEvent)
    if event_type:
        stmt = stmt.where(ChangeEvent.event_type == event_type.upper())
    if status:
        stmt = stmt.where(ChangeEvent.status == status.upper())
    if taxonomy_stage:
        stmt = stmt.where(ChangeEvent.taxonomy_stage == taxonomy_stage.upper())
    if demo is not None:
        stmt = stmt.where(ChangeEvent.is_demo.is_(demo))
    if min_confidence is not None:
        stmt = stmt.where(ChangeEvent.confidence >= min_confidence)
    if aoi_id:
        from app.db.models import ProcessingJob, ProcessingRun

        run_ids = db.scalars(
            select(ProcessingRun.id)
            .join(ProcessingJob, ProcessingRun.job_id == ProcessingJob.id)
            .where(ProcessingJob.aoi_id == aoi_id)
        ).all()
        stmt = stmt.where(ChangeEvent.run_id.in_(list(run_ids) or [""]))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(ChangeEvent.severity.desc(), ChangeEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[EventOut](
        items=[EventOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/events/geojson")
def events_geojson(
    event_type: str | None = None,
    status: str | None = None,
    taxonomy_stage: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(ChangeEvent)
    if event_type:
        stmt = stmt.where(ChangeEvent.event_type == event_type.upper())
    if status:
        stmt = stmt.where(ChangeEvent.status == status.upper())
    if taxonomy_stage:
        stmt = stmt.where(ChangeEvent.taxonomy_stage == taxonomy_stage.upper())
    if demo is not None:
        stmt = stmt.where(ChangeEvent.is_demo.is_(demo))
    rows = db.scalars(
        stmt.order_by(ChangeEvent.severity.desc()).limit(limit)
    ).all()
    features = []
    for event in rows:
        if not event.geometry:
            continue
        features.append(
            {
                "type": "Feature",
                "id": event.id,
                "geometry": event.geometry,
                "properties": {
                    "event_type": event.event_type,
                    "taxonomy_stage": event.taxonomy_stage,
                    "status": event.status,
                    "confidence": event.confidence,
                    "uncertainty": event.uncertainty,
                    "area_m2": event.area_m2,
                    "magnitude": event.magnitude,
                    "magnitude_unit": event.magnitude_unit,
                    "severity": event.severity,
                    "priority": event.priority,
                    "summary": event.summary,
                    "is_demo": event.is_demo,
                    "start_time": event.start_time.isoformat() if event.start_time else None,
                    "end_time": event.end_time.isoformat() if event.end_time else None,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "demo_mode": any(f["properties"]["is_demo"] for f in features),
            "notice": (
                "Demo features are synthetic SARVEX fixtures, not NASA/ISRO observations."
                if any(f["properties"]["is_demo"] for f in features)
                else None
            ),
        },
    }


@router.get("/events/stats")
def event_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    by_type = dict(
        db.execute(
            select(ChangeEvent.event_type, func.count(ChangeEvent.id)).group_by(
                ChangeEvent.event_type
            )
        ).all()
    )
    by_status = dict(
        db.execute(
            select(ChangeEvent.status, func.count(ChangeEvent.id)).group_by(ChangeEvent.status)
        ).all()
    )
    by_stage = dict(
        db.execute(
            select(ChangeEvent.taxonomy_stage, func.count(ChangeEvent.id)).group_by(
                ChangeEvent.taxonomy_stage
            )
        ).all()
    )
    total = int(db.scalar(select(func.count(ChangeEvent.id))) or 0)
    demo = int(
        db.scalar(select(func.count(ChangeEvent.id)).where(ChangeEvent.is_demo.is_(True))) or 0
    )
    return {
        "total": total,
        "demo": demo,
        "by_type": by_type,
        "by_status": by_status,
        "by_taxonomy_stage": by_stage,
    }


@router.get("/events/{event_id}", response_model=EventDetail)
def get_event(event_id: str, db: Session = Depends(get_db)) -> EventDetail:
    event = _get_event(db, event_id)
    detail = EventDetail.model_validate(event)
    detail.observation_ids = [link.observation_id for link in event.observation_links]
    detail.evidence_ids = [link.evidence_id for link in event.evidence_links]
    detail.context_ids = [link.context_id for link in event.context_links]
    exposures = db.scalars(
        select(EventExposure)
        .where(EventExposure.event_id == event.id)
        .order_by(EventExposure.exposure_score.desc())
    ).all()
    asset_ids = [e.asset_id for e in exposures]
    assets = {
        a.id: AssetOut.model_validate(a)
        for a in db.scalars(
            select(InfrastructureAsset).where(InfrastructureAsset.id.in_(asset_ids or [""]))
        ).all()
    }
    detail.exposures = [
        ExposureOut.model_validate(
            {
                **{
                    "id": e.id,
                    "event_id": e.event_id,
                    "asset_id": e.asset_id,
                    "distance_m": e.distance_m,
                    "overlap_ratio": e.overlap_ratio,
                    "exposure_score": e.exposure_score,
                    "rationale": e.rationale,
                    "asset": assets.get(e.asset_id),
                }
            }
        )
        for e in exposures
    ]
    return detail


@router.patch("/events/{event_id}/status", response_model=EventReviewOut)
def update_event_status(
    event_id: str, update: EventStatusUpdate, db: Session = Depends(get_db)
) -> EventReviewOut:
    event = _get_event(db, event_id)
    target = update.status.upper()
    allowed = ALLOWED_TRANSITIONS.get(event.status, set())
    if target not in allowed:
        raise ConflictError(
            f"Cannot move event from {event.status} to {target}",
            detail={"allowed_transitions": sorted(allowed)},
        )
    if target == "CORROBORATED" and not update.external_evidence_url:
        raise ValidationError(
            "CORROBORATED requires an external_evidence_url. Use the confirmation "
            "endpoint to attach authoritative evidence and promote to CONFIRMED."
        )
    previous = event.status
    event.status = target
    db.add(
        AuditLog(
            actor="api_client",
            action="event.status_changed",
            entity_type="change_event",
            entity_id=event.id,
            detail={
                "from": previous,
                "to": target,
                "rationale": update.rationale,
                "external_evidence_url": update.external_evidence_url,
            },
        )
    )
    db.commit()
    return EventReviewOut(
        event_id=event.id,
        status=event.status,
        taxonomy_stage=event.taxonomy_stage,
        message=(
            f"Status changed from {previous} to {target}. Taxonomy stage remains "
            f"{event.taxonomy_stage}; confirmation requires independent evidence."
        ),
    )


@router.post("/events/{event_id}/confirm", response_model=EventReviewOut)
def confirm_event(
    event_id: str, request: ConfirmEventRequest, db: Session = Depends(get_db)
) -> EventReviewOut:
    """Promote an event to CONFIRMED using independent external evidence.

    Hard gates:
    - demo events can never be confirmed (synthetic fixtures are not real events);
    - synthetic evidence is rejected;
    - a resolvable reference (URL or citation) is mandatory;
    - the event must not be REJECTED or ARCHIVED.
    """
    event = _get_event(db, event_id)
    if event.is_demo:
        raise ValidationError(
            "Demo events derive from synthetic fixtures and cannot be CONFIRMED. "
            "Confirm only real observations with independent authoritative evidence.",
            detail={"event_id": event.id, "is_demo": True},
        )
    if request.is_demo_evidence:
        raise ValidationError("Synthetic evidence cannot be used to confirm a real event")
    if not (request.url or request.citation):
        raise ValidationError("A URL or a full citation is required for confirmation")
    if event.status in {"REJECTED", "ARCHIVED"}:
        raise ConflictError(
            f"Event is {event.status}; move it back to UNDER_REVIEW before confirmation",
            detail={"status": event.status},
        )
    evidence = EvidenceItem(
        source_type=request.source_type,
        title=request.evidence_title,
        url=request.url,
        citation=request.citation,
        snippet=request.rationale,
        evidence_metadata={
            "publisher": request.publisher,
            "observed_at": request.observed_at.isoformat() if request.observed_at else None,
            "confirmation": True,
        },
        confidence=1.0,
        is_demo=False,
    )
    db.add(evidence)
    db.flush()
    linked = {link.evidence_id for link in event.evidence_links}
    if evidence.id not in linked:
        db.add(EventEvidenceLink(event_id=event.id, evidence_id=evidence.id))
    previous_stage = event.taxonomy_stage
    previous_status = event.status
    event.taxonomy_stage = "CONFIRMED"
    event.status = "CORROBORATED"
    event.classification_confidence = max(event.classification_confidence or 0.0, 0.9)
    event.properties = {
        **(event.properties or {}),
        "confirmation": {
            "evidence_id": evidence.id,
            "source_type": request.source_type,
            "publisher": request.publisher,
            "url": request.url,
            "citation": request.citation,
            "rationale": request.rationale,
            "previous_taxonomy_stage": previous_stage,
        },
    }
    db.add(
        AuditLog(
            actor="api_client",
            action="event.confirmed",
            entity_type="change_event",
            entity_id=event.id,
            detail={
                "from_stage": previous_stage,
                "to_stage": "CONFIRMED",
                "from_status": previous_status,
                "to_status": "CORROBORATED",
                "evidence_id": evidence.id,
            },
        )
    )
    db.commit()
    return EventReviewOut(
        event_id=event.id,
        status=event.status,
        taxonomy_stage=event.taxonomy_stage,
        evidence_id=evidence.id,
        message=(
            "Event promoted to CONFIRMED with independently supplied evidence. "
            "The evidence remains separately identifiable and citable."
        ),
    )


@router.get("/events/{event_id}/exposures", response_model=list[ExposureOut])
def list_event_exposures(event_id: str, db: Session = Depends(get_db)) -> list[ExposureOut]:
    _get_event(db, event_id)
    exposures = db.scalars(
        select(EventExposure)
        .where(EventExposure.event_id == event_id)
        .order_by(EventExposure.exposure_score.desc())
    ).all()
    assets = {
        a.id: AssetOut.model_validate(a)
        for a in db.scalars(
            select(InfrastructureAsset).where(
                InfrastructureAsset.id.in_([e.asset_id for e in exposures] or [""])
            )
        ).all()
    }
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


@router.get("/events/{event_id}/evidence", response_model=list[EvidenceOut])
def list_event_evidence(event_id: str, db: Session = Depends(get_db)) -> list[EvidenceOut]:
    event = _get_event(db, event_id)
    ids = [link.evidence_id for link in event.evidence_links]
    rows = db.scalars(select(EvidenceItem).where(EvidenceItem.id.in_(ids or [""]))).all()
    return [EvidenceOut.model_validate(row) for row in rows]


@router.get("/events/{event_id}/context", response_model=list[ContextOut])
def list_event_context(event_id: str, db: Session = Depends(get_db)) -> list[ContextOut]:
    event = _get_event(db, event_id)
    ids = [link.context_id for link in event.context_links]
    rows = db.scalars(select(GeospatialContext).where(GeospatialContext.id.in_(ids or [""]))).all()
    return [ContextOut.model_validate(row) for row in rows]


def _get_event(db: Session, event_id: str) -> ChangeEvent:
    event = db.get(ChangeEvent, event_id)
    if not event:
        raise NotFoundError(f"Change event {event_id} not found")
    return event
