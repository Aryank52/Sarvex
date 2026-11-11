"""Model registry endpoints: configuration, health and model run history."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.post("/models/hfce/predict")
def hfce_predict(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.services.hfce import load_hfce

    model = load_hfce()
    if model is None:
        raise HTTPException(status_code=503, detail="HFCE model artifact not available")
    feats = payload.get("features") or payload
    for name in model.feature_names:
        feats.setdefault(name, 0.0)
    pred = model.predict(feats)
    return {
        "model": "SARVEX-HFCE",
        "model_version": pred.model_version,
        "prediction": {
            "event_type": pred.event_type,
            "change_probability": pred.change_probability,
            "confidence": pred.confidence,
            "uncertainty": pred.uncertainty,
            "probabilities": pred.probabilities,
            "top_features": pred.top_features,
            "baseline_score": pred.baseline_score,
            "ml_score": pred.ml_score,
            "anomaly_score": pred.anomaly_score,
            "fusion": pred.fusion,
        },
    }


@router.get("/results/{result_id}/hfce")
def hfce_for_result(result_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.api.analyses import _get_result
    from app.services.hfce import classify_result

    result = _get_result(db, result_id)
    return classify_result(db, result)


@router.get("/models/hfce/status")
def hfce_status() -> dict[str, Any]:
    from app.services.hfce import find_latest_model_dir
    import json

    d = find_latest_model_dir()
    if d is None:
        return {"available": False, "reason": "No HFCE artifact. Run training script."}
    manifest = {}
    if (d / "training_manifest.json").exists():
        try:
            manifest = json.loads((d / "training_manifest.json").read_text())
        except Exception:  # noqa: BLE001
            manifest = {}
    return {
        "available": True,
        "artifact_dir": str(d),
        "model_version": (d / "version.txt").read_text().strip() if (d / "version.txt").exists() else "1.0",
        "metrics": manifest.get("metrics"),
        "caveat": manifest.get("caveat"),
        "trained_at": manifest.get("trained_at"),
        "n_samples": manifest.get("n_samples"),
        "class_distribution": manifest.get("class_distribution"),
        "feature_importance": manifest.get("feature_importance"),
        "shap_summary": manifest.get("shap_summary"),
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
