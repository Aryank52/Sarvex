"""SARVEX-HFCE service: load trained model and run inference on result features."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import ModelRun
from app.ml.hfce import SarvexHFCE, EVENT_TYPES


def _artifact_root() -> Path:
    settings = get_settings()
    # relative to backend working dir
    return Path("artifacts/models/hfce")


def find_latest_model_dir() -> Path | None:
    root = _artifact_root()
    if not root.exists():
        return None
    candidates = [p for p in root.iterdir() if p.is_dir() and (p / "model.json").exists()]
    if not candidates:
        # maybe latest/ has model
        if (root / "latest" / "model.json").exists():
            return root / "latest"
        return None
    candidates.sort(key=lambda p: p.name)
    return candidates[-1]


def load_hfce() -> SarvexHFCE | None:
    d = find_latest_model_dir()
    if d is None:
        return None
    try:
        return SarvexHFCE.load(d)
    except Exception:  # noqa: BLE001
        return None


def features_from_result(result) -> dict[str, Any]:
    stats = result.statistics or {}
    # map result stats to HFCE feature names
    feats: dict[str, Any] = {}
    # backscatter
    if stats.get("median_change_db") is not None:
        feats["backscatter_change_median_db"] = stats.get("median_change_db")
    feats["backscatter_std_db"] = stats.get("std_change_db") or stats.get("change_std_db")
    # coherence
    feats["coherence_mean"] = stats.get("mean_coherence") or stats.get("coherence_mean")
    feats["low_coherence_fraction"] = stats.get("low_coherence_fraction")
    # deformation
    feats["displacement_median_mm"] = stats.get("median_displacement_mm")
    feats["displacement_std_mm"] = stats.get("std_displacement_mm") or stats.get("displacement_std_mm")
    # spatial
    feats["changed_fraction"] = stats.get("change_fraction")
    # temporal
    feats["temporal_sign_changes"] = stats.get("change_points_count") or (len(stats.get("change_points") or []) if isinstance(stats.get("change_points"), list) else None)
    # polarimetric
    feats["vv_vh_ratio_std_db"] = stats.get("ratio_change_std_db") or stats.get("std_ratio_change_db")
    # context defaults
    feats["distance_to_water_m"] = None
    feats["elevation_m"] = None
    feats["slope_deg"] = None
    # remove None
    return {k: v for k, v in feats.items() if v is not None}


def classify_result(session: Session, result, correlation_id: str | None = None) -> dict[str, Any]:
    model = load_hfce()
    if model is None:
        return {"available": False, "reason": "HFCE model artifact not found. Run training script."}
    feats = features_from_result(result)
    # fill missing with 0
    for name in model.feature_names:
        feats.setdefault(name, 0.0)
    pred = model.predict(feats)
    # record model run
    try:
        run = ModelRun(
            purpose="hfce_classification",
            model_name="sarvex-hfce",
            model_version=pred.model_version,
            status="COMPLETED",
            latency_ms=None,
            error=None,
            correlation_id=correlation_id,
            input_summary={"result_id": result.id, "features": feats},
            output_summary={"event_type": pred.event_type, "change_probability": pred.change_probability, "confidence": pred.confidence},
        )
        session.add(run)
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    return {
        "available": True,
        "model": "SARVEX-HFCE",
        "model_version": pred.model_version,
        "feature_version": pred.feature_version,
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
        "features_used": feats,
        "explanation": model.explain(),
    }
