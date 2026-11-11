"""Versioned API router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from app.api import analyses, catalog, context, events, evidence, health, knowledge, models, nlp, reports

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(catalog.router)
api_router.include_router(analyses.router)
api_router.include_router(events.router)
api_router.include_router(context.router)
api_router.include_router(evidence.router)
api_router.include_router(models.router)
api_router.include_router(knowledge.router)
api_router.include_router(reports.router)
api_router.include_router(nlp.router)

__all__ = ["api_router"]
