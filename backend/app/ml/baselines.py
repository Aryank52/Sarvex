"""Deterministic scientific baselines exposed through the ML interfaces.

These are not neural networks. They are transparent, testable baselines used as
the default change detector and as a fallback when supplied models are absent.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from app.ml.interfaces import ChangeDetector
from app.processing.stats import robust_stats


class RobustMADChangeDetector(ChangeDetector):
    name = "robust_mad_change_detector"
    version = "1.0"

    def __init__(self, z_threshold: float = 3.5, min_magnitude: float = 1.0) -> None:
        self.z_threshold = float(z_threshold)
        self.min_magnitude = float(min_magnitude)
        self._median: float | None = None
        self._sigma: float | None = None
        self._fitted = False

    def fit(self, features: Any, labels: Any | None = None) -> "RobustMADChangeDetector":
        baseline = np.asarray(features, dtype="float64")
        baseline = baseline[np.isfinite(baseline)]
        if baseline.size == 0:
            raise ValueError("Cannot fit change detector without finite baseline values")
        st = robust_stats(baseline)
        self._median = float(st["median"])
        self._sigma = float(st["sigma"]) if st["sigma"] > 0 else float(st["std"]) or 1e-6
        self._fitted = True
        return self

    def predict(self, features: Any) -> np.ndarray:
        if not self._fitted:
            raise RuntimeError("Change detector must be fitted before predict()")
        values = np.asarray(features, dtype="float64")
        z = (values - float(self._median)) / float(self._sigma)
        return (np.abs(z) >= self.z_threshold) & (np.abs(values - float(self._median)) >= self.min_magnitude)

    def score(self, features: Any, labels: Any) -> dict[str, float]:
        pred = self.predict(features)
        truth = np.asarray(labels, dtype=bool)
        tp = float(np.sum(pred & truth))
        fp = float(np.sum(pred & ~truth))
        fn = float(np.sum(~pred & truth))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        return {"precision": precision, "recall": recall, "f1": f1, "support": float(truth.size)}

    def explain(self) -> dict[str, Any]:
        return {
            "method": "median absolute deviation robust z-score",
            "baseline_median": self._median,
            "baseline_sigma": self._sigma,
            "z_threshold": self.z_threshold,
            "min_magnitude": self.min_magnitude,
            "assumptions": [
                "Baseline distribution is approximately unimodal and stationary",
                "MAD is used to reduce sensitivity to outliers",
            ],
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "category": "change_detection",
            "name": self.name,
            "version": self.version,
            "type": "deterministic_baseline",
            "feature_version": "backscatter_db_v1",
            "processing_version": "1.0",
        }


class HTTPChangeDetector(ChangeDetector):
    """Adapter for an externally supplied change-detection model endpoint.

    The endpoint contract is intentionally generic:
    POST {"features": [...], "feature_version": "..."} ->
    {"predictions": [...], "scores": [...], "model_version": "..."}
    """

    name = "http_change_detector"
    version = "1.0"

    def __init__(self, endpoint: str, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self._last_scores: list[float] = []

    def fit(self, features: Any, labels: Any | None = None) -> "HTTPChangeDetector":
        # Remote models are pre-trained; fitting is a no-op but explicit.
        return self

    def predict(self, features: Any) -> np.ndarray:
        import httpx

        arr = np.asarray(features, dtype="float64")
        payload = {"features": arr.ravel().tolist(), "shape": list(arr.shape), "feature_version": "backscatter_db_v1"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(self.endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            from app.core.errors import CapabilityUnavailableError

            raise CapabilityUnavailableError(f"Change-detection model endpoint failed: {exc}") from exc
        preds = np.asarray(data.get("predictions", []), dtype=bool)
        self._last_scores = list(data.get("scores", []))
        if preds.shape != arr.shape:
            raise ValueError(
                f"Model returned predictions with shape {preds.shape}; expected {arr.shape}"
            )
        return preds

    def score(self, features: Any, labels: Any) -> dict[str, float]:
        pred = self.predict(features)
        truth = np.asarray(labels, dtype=bool)
        tp = float(np.sum(pred & truth))
        fp = float(np.sum(pred & ~truth))
        fn = float(np.sum(~pred & truth))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return {
            "precision": precision,
            "recall": recall,
            "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0,
            "support": float(truth.size),
        }

    def explain(self) -> dict[str, Any]:
        return {"method": "remote_model", "endpoint": self.endpoint, "scores_available": bool(self._last_scores)}

    def metadata(self) -> dict[str, Any]:
        return {
            "category": "change_detection",
            "name": self.name,
            "version": self.version,
            "type": "remote_model",
            "endpoint": self.endpoint,
        }
