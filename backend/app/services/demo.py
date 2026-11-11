"""Demo data seeding: catalog, context, knowledge documents and real analyses.

All seeded records are explicitly flagged ``is_demo``. Analyses are genuinely
computed by the processing engine from the synthetic fixtures; no result values
are hard-coded.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.connectors.base import SearchQuery
from app.connectors.demo import DEMO_PROVIDER
from app.connectors.registry import get_connector_registry
from app.core.geometry import geometry_area_m2, geometry_bbox
from app.db.models import AOI, AnalysisResult, Document, Product, ProcessingJob
from app.events.context import seed_demo_context
from app.fixtures.demo_raster import AOI_BOUNDS
from app.rag.ingest import ingest_document
from app.schemas.analysis import AnalysisRequest, TimeRange
from app.services.ingest import ingest_remote
from app.services.jobs import create_job
from app.processing.engine import execute_job

logger = logging.getLogger("sarvex.demo")

DEMO_AOI_NAME = "Assam demonstration AOI (synthetic fixtures)"


def seed_demo_aoi(session: Session) -> AOI:
    existing = session.scalar(
        select(AOI).where(AOI.name == DEMO_AOI_NAME)
    )
    if existing:
        return existing
    minx, miny, maxx, maxy = AOI_BOUNDS
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]
        ],
    }
    aoi = AOI(
        name=DEMO_AOI_NAME,
        description=(
            "Demonstration AOI over Assam, India. Bounds are real-world geography; "
            "all SAR pixels are SARVEX synthetic fixtures, not NASA/ISRO observations."
        ),
        geometry=geometry,
        bbox=geometry_bbox(geometry),
        area_m2=geometry_area_m2(geometry),
        crs="EPSG:4326",
        created_by="demo_seed",
    )
    session.add(aoi)
    session.commit()
    return aoi


def seed_demo_catalog(session: Session, dest_dir: Path | None = None) -> int:
    existing = session.scalar(
        select(Product).where(Product.is_demo.is_(True), Product.provider == DEMO_PROVIDER).limit(1)
    )
    if existing:
        return 0
    registry = get_connector_registry()
    products = registry.demo.search(SearchQuery(max_results=50))
    dest = dest_dir or (BACKEND_DIR / "data" / "demo_ingest")
    count = 0
    for remote in products:
        # Skip duplicates from a partially completed previous seed.
        if session.scalar(
            select(Product).where(Product.product_id == remote.product_id).limit(1)
        ):
            continue
        try:
            ingest_remote(session, registry.demo, remote, dest)
            count += 1
        except Exception as exc:  # noqa: BLE001 - seeding must report, not crash silently
            session.rollback()
            logger.exception("Demo ingest failed for %s: %s", remote.product_id, exc)
    return count


def seed_demo_documents(session: Session) -> int:
    from app.fixtures.demo_docs import DEMO_DOCUMENTS

    count = 0
    for doc in DEMO_DOCUMENTS:
        existing = session.scalar(
            select(Document).where(Document.title == doc.title, Document.is_demo.is_(True))
        )
        if existing:
            continue
        try:
            ingest_document(
                session,
                text=doc.text,
                title=doc.title,
                publisher="SARVEX (internal demo knowledge)",
                document_type=doc.topic,
                scientific_topic=doc.topic,
                mission=None,
                license_text="SARVEX internal demo note; not an official NASA/ISRO document",
                source_priority=7,
                is_demo=True,
                extra_metadata={"authored_by": "SARVEX", "demo": True},
            )
            count += 1
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning("Demo document ingest failed for '%s': %s", doc.title, exc)
    return count


def _products_by_type(session: Session, product_type: str, band: str | None = None, limit: int = 10) -> list[Product]:
    from app.db.models import Observation

    stmt = (
        select(Product)
        .join(Observation)
        .where(Product.is_demo.is_(True), Observation.product_type == product_type)
        .order_by(Observation.acquisition_start)
    )
    if band:
        stmt = stmt.where(Observation.frequency_band == band)
    return list(session.scalars(stmt.limit(limit)).all())


def seed_demo_analyses(session: Session, aoi: AOI) -> list[str]:
    """Run real analyses over the demo fixtures. Returns created result IDs."""
    settings = get_settings()
    created: list[str] = []
    scenarios = [
        ("backscatter", _products_by_type(session, "GCOV", "L", 3)),
        ("deformation", _products_by_type(session, "GUNW", None, 1)),
        ("polarimetric", _products_by_type(session, "GCOV", None, 10)),
    ]
    for analysis_type, products in scenarios:
        if analysis_type == "polarimetric":
            products = [p for p in products if "+" in (p.observation.polarization or "")]
        if not products:
            logger.info("Skipping demo %s analysis: no fixtures", analysis_type)
            continue
        existing = session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.analysis_type == analysis_type,
                ProcessingJob.is_demo.is_(True),
                ProcessingJob.status == "COMPLETED",
            ).limit(1)
        )
        if existing:
            result = session.scalar(
                select(AnalysisResult).where(AnalysisResult.job_id == existing.id).limit(1)
            )
            if result:
                created.append(result.id)
            continue
        request = AnalysisRequest(
            aoi_id=aoi.id,
            product_ids=[p.product_id for p in products],
            analysis_type=analysis_type,  # type: ignore[arg-type]
            parameters={},
            requested_by="demo_seed",
        )
        job = create_job(session, request)
        status = execute_job(job.id)
        logger.info("Demo %s analysis -> %s", analysis_type, status)
        session.expire_all()
        result = session.scalar(select(AnalysisResult).where(AnalysisResult.job_id == job.id).limit(1))
        if result:
            created.append(result.id)
    return created


def seed_demo(session: Session, *, include_analyses: bool = True) -> dict[str, object]:
    aoi = seed_demo_aoi(session)
    products = seed_demo_catalog(session)
    context_counts = seed_demo_context(session)
    documents = seed_demo_documents(session)
    result_ids: list[str] = []
    if include_analyses:
        result_ids = seed_demo_analyses(session, aoi)
    summary = {
        "aoi_id": aoi.id,
        "products_ingested": products,
        "context_layers": context_counts[0],
        "assets": context_counts[1],
        "documents": documents,
        "result_ids": result_ids,
        "demo_mode": True,
        "notice": "All demo data is synthetic. Not NASA or ISRO observations.",
    }
    logger.info("Demo seed complete: %s", summary)
    return summary
