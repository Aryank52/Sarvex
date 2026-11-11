"""Evidence registry endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.core.errors import NotFoundError, ValidationError
from app.db.models import AuditLog, ChangeEvent, EventEvidenceLink, EvidenceItem
from app.schemas.analysis import EvidenceCreate, EvidenceOut
from app.schemas.common import Page

router = APIRouter(tags=["evidence"], dependencies=[Depends(rate_limit)])


@router.get("/evidence", response_model=Page[EvidenceOut])
def list_evidence(
    source_type: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[EvidenceOut]:
    stmt = select(EvidenceItem)
    if source_type:
        stmt = stmt.where(EvidenceItem.source_type == source_type)
    if demo is not None:
        stmt = stmt.where(EvidenceItem.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(EvidenceItem.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[EvidenceOut](
        items=[EvidenceOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/evidence", response_model=EvidenceOut, status_code=201)
def create_evidence(request: EvidenceCreate, db: Session = Depends(get_db)) -> EvidenceOut:
    if not (request.url or request.citation or request.snippet):
        raise ValidationError("Evidence must include a URL, citation or snippet")
    evidence = EvidenceItem(
        source_type=request.source_type,
        title=request.title,
        url=request.url,
        citation=request.citation,
        snippet=request.snippet,
        evidence_metadata=request.evidence_metadata,
        confidence=request.confidence,
        is_demo=request.is_demo,
    )
    db.add(evidence)
    db.flush()
    if request.event_id:
        event = db.get(ChangeEvent, request.event_id)
        if not event:
            raise NotFoundError(f"Change event {request.event_id} not found")
        db.add(EventEvidenceLink(event_id=event.id, evidence_id=evidence.id))
    db.add(
        AuditLog(
            actor="api_client",
            action="evidence.created",
            entity_type="evidence_item",
            entity_id=evidence.id,
            detail={"event_id": request.event_id, "source_type": request.source_type},
        )
    )
    db.commit()
    return EvidenceOut.model_validate(evidence)


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def get_evidence(evidence_id: str, db: Session = Depends(get_db)) -> EvidenceOut:
    evidence = db.get(EvidenceItem, evidence_id)
    if not evidence:
        raise NotFoundError(f"Evidence {evidence_id} not found")
    return EvidenceOut.model_validate(evidence)
