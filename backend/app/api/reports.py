"""Report generation and retrieval endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.core.errors import NotFoundError
from app.db.models import Report
from app.schemas.common import Page
from app.schemas.knowledge import ReportCreate, ReportOut, ReportSummaryOut
from app.services.reports import create_report, get_report_content

router = APIRouter(tags=["reports"], dependencies=[Depends(rate_limit)])


@router.post("/reports", response_model=ReportOut, status_code=201)
def generate_report(request: ReportCreate, db: Session = Depends(get_db)) -> ReportOut:
    report = create_report(db, request)
    return ReportOut.model_validate(report)


@router.get("/reports", response_model=Page[ReportSummaryOut])
def list_reports(
    report_type: str | None = None,
    result_id: str | None = None,
    event_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[ReportSummaryOut]:
    stmt = select(Report)
    if report_type:
        stmt = stmt.where(Report.report_type == report_type.upper())
    if result_id:
        stmt = stmt.where(Report.result_id == result_id)
    if event_id:
        stmt = stmt.where(Report.event_id == event_id)
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(Report.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return Page[ReportSummaryOut](
        items=[ReportSummaryOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: str, db: Session = Depends(get_db)) -> ReportOut:
    report = db.get(Report, report_id)
    if not report:
        raise NotFoundError(f"Report {report_id} not found")
    return ReportOut.model_validate(report)


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, db: Session = Depends(get_db)) -> Response:
    report, content, media_type = get_report_content(db, report_id)
    extension = "html" if report.format == "html" else "md"
    safe_title = "".join(
        c if c.isalnum() or c in "-_ " else "_" for c in report.title
    ).strip()[:80] or "sarvex-report"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_title}.{extension}"',
        },
    )
