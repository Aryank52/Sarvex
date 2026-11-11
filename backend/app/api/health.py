"""Health, capability and system status endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_db
from app.config import get_settings
from app.connectors.registry import get_connector_registry
from app.isce3.adapter import get_isce3_adapter
from app.ml.registry import get_model_registry
from app.rag.ingest import rag_stats

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Fast health check with no live network probes."""
    settings = get_settings()
    database_ok = True
    database_error = None
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        database_ok = False
        database_error = str(exc)
    registry = get_model_registry()
    isce3 = get_isce3_adapter().health()
    try:
        rag = rag_stats(db)
    except Exception:  # noqa: BLE001 - empty database before init
        rag = {"documents": 0, "chunks": 0, "embeddings": 0}
    demo_products = 0
    try:
        from sqlalchemy import func, select

        from app.db.models import Product

        demo_products = int(db.scalar(select(func.count(Product.id)).where(Product.is_demo.is_(True))) or 0)
    except Exception:  # noqa: BLE001
        pass
    if settings.demo_mode == "on" or (settings.demo_mode == "auto" and demo_products > 0):
        data_mode = "DEMO"
    elif demo_products > 0:
        data_mode = "MIXED"
    else:
        data_mode = "LIVE_OR_EMPTY"
    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.app_name,
        "version": __version__,
        "code_version": settings.code_version,
        "environment": settings.environment,
        "time": datetime.now(timezone.utc).isoformat(),
        "database": {
            "backend": "postgresql" if not settings.using_sqlite else "sqlite",
            "postgis": not settings.using_sqlite,
            "pgvector": not settings.using_sqlite,
            "healthy": database_ok,
            "error": database_error,
        },
        "object_storage": {"backend": settings.object_storage_backend},
        "demo_mode": {
            "setting": settings.demo_mode,
            "effective_data_mode": data_mode,
            "demo_products": demo_products,
            "banner": (
                "DEMO MODE — synthetic fixtures, not NASA/ISRO observations"
                if data_mode in {"DEMO", "MIXED"}
                else None
            ),
        },
        "models": {
            "configured": registry.capability_summary(),
            "active_llm": registry.active_llm_health(),
            "degraded_by_default": True,
        },
        "isce3": isce3,
        "rag": rag,
        "worker": {
            "inline": settings.run_inline_worker,
            "mode": "inline_thread" if settings.run_inline_worker else "external_worker",
        },
        "offline_mode": settings.offline_mode,
    }


@router.get("/health/connectors")
def connector_health() -> dict[str, Any]:
    """Explicit connector probe. May perform network calls; offline mode is fast."""
    registry = get_connector_registry()
    summary = registry.availability_summary()
    return {**summary, "probed_at": datetime.now(timezone.utc).isoformat()}


@router.get("/health/models")
def model_health() -> dict[str, Any]:
    registry = get_model_registry()
    return {
        "models": registry.health(),
        "summary": registry.capability_summary(),
        "config_path": str(registry.config_path),
    }


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    """Machine-readable capability map used by the frontend and documentation."""
    settings = get_settings()
    registry = get_model_registry()
    return {
        "analysis_types": [
            {"type": "backscatter", "modes": ["GCOV", "GSLC"], "min_products": 2},
            {"type": "change_detection", "modes": ["GCOV", "GSLC"], "min_products": 2},
            {"type": "deformation", "modes": ["GUNW", "RUNW"], "min_products": 1},
            {"type": "polarimetric", "modes": ["GCOV"], "min_products": 1},
            {"type": "offsets", "modes": ["RSLC", "GSLC", "GCOV"], "min_products": 2},
            {"type": "timeseries", "modes": ["GCOV", "GSLC"], "min_products": 3},
        ],
        "connectors": ["nasa_asf", "bhoonidhi", "local", "stac", "demo"],
        "product_types": ["RSLC", "GSLC", "GCOV", "RIFG", "RUNW", "GUNW", "ROFF", "GOFF"],
        "frequency_bands": ["L", "S"],
        "models": registry.capability_summary(),
        "isce3": get_isce3_adapter().health(),
        "offline_mode": settings.offline_mode,
        "demo_mode": settings.demo_mode,
        "storage": {
            "database": "postgresql+postgis+pgvector" if not settings.using_sqlite else "sqlite (dev/test fallback)",
            "objects": settings.object_storage_backend,
        },
    }
