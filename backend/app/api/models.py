"""Model registry endpoints: configuration, health and model run history."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.ml.registry import get_model_registry
from app.schemas.knowledge import ModelInfoOut

router = APIRouter(tags=["models"], dependencies=[Depends(rate_limit)])


@router.get("/models")
def list_models() -> dict[str, Any]:
    registry = get_model_registry()
    health = registry.health()
    models = [
        ModelInfoOut(
            category=entry["category"],
            name=entry["name"],
            provider=entry["provider"],
            version=entry["version"],
            task=entry.get("task"),
            framework=entry.get("framework"),
            status=entry["status"],
            is_default=entry["is_default"],
            capabilities=entry.get("capabilities", {}),
            health=entry.get("capabilities", {}),
        )
        for entry in health
    ]
    return {
        "models": models,
        "summary": registry.capability_summary(),
        "config_path": str(registry.config_path),
        "principle": (
            "Models are declarative configuration. No model name is hard-coded in "
            "processing, API, RAG or copilot business logic; supplied specs are added "
            "to config/models.yaml and, if needed, a provider adapter."
        ),
    }


@router.get("/models/summary")
def model_summary() -> dict[str, Any]:
    return get_model_registry().capability_summary()


@router.post("/models/reload")
def reload_models(db: Session = Depends(get_db)) -> dict[str, Any]:
    registry = get_model_registry()
    registry.reload()
    synced = registry.sync_to_db(db)
    return {
        "reloaded": True,
        "synced_models": synced,
        "summary": registry.capability_summary(),
    }


@router.get("/models/runs")
def list_model_runs(
    purpose: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from app.db.models import ModelRun

    stmt = select(ModelRun)
    if purpose:
        stmt = stmt.where(ModelRun.purpose == purpose)
    rows = db.scalars(stmt.order_by(ModelRun.created_at.desc()).limit(limit)).all()
    return {
        "runs": [
            {
                "id": run.id,
                "purpose": run.purpose,
                "model_name": run.model_name,
                "model_version": run.model_version,
                "status": run.status,
                "latency_ms": run.latency_ms,
                "error": run.error,
                "correlation_id": run.correlation_id,
                "created_at": run.created_at.isoformat(),
            }
            for run in rows
        ]
    }
