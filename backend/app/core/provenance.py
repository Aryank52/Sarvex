"""Provenance construction for immutable processing runs."""
from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_provenance(
    *,
    algorithm: str,
    algorithm_version: str,
    parameters: dict[str, Any],
    dataset_ids: list[str] | None = None,
    observation_ids: list[str] | None = None,
    product_ids: list[str] | None = None,
    model: str | None = None,
    model_version: str | None = None,
    crs: str = "EPSG:4326",
    units: str | None = None,
    request_id: str | None = None,
    aoi_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the immutable provenance payload attached to every run."""
    settings = get_settings()
    return {
        "sarvex_version": "1.0.0",
        "code_version": settings.code_version,
        "algorithm": algorithm,
        "algorithm_version": algorithm_version,
        "parameters": parameters,
        "dataset_ids": dataset_ids or [],
        "observation_ids": observation_ids or [],
        "product_ids": product_ids or [],
        "model": model,
        "model_version": model_version,
        "crs": crs,
        "units": units,
        "run_timestamp": utcnow().isoformat(),
        "request_id": request_id,
        "aoi_id": aoi_id,
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "extra": extra or {},
    }
