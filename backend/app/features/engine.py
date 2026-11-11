"""SARVEX feature engine.

Extracts scientific features from SAR products and derived rasters. Every
feature carries name, value, unit, source, timestamp, algorithm_version. No
feature is invented; missing inputs yield missing features rather than zeros.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np


@dataclass
class Feature:
    name: str
    value: float | None
    unit: str
    source: str
    timestamp: str | None
    algorithm_version: str
    group: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


FEATURE_ALGORITHM_VERSION = "sar_feature_engine_v1"


def _safe_stat(arr: np.ndarray, fn) -> float | None:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    try:
        v = fn(finite)
    except Exception:  # noqa: BLE001
        return None
    if not np.isfinite(v):
        return None
    return float(v)


class SARFeatureEngine:
    """Extracts feature groups A-G from arrays and context."""

    def __init__(self, algorithm_version: str = FEATURE_ALGORITHM_VERSION) -> None:
        self.algorithm_version = algorithm_version

    def _stamp(self, ts: str | None) -> str | None:
        return ts

    def backscatter_features(
        self,
        array_db: np.ndarray,
        *,
        source: str,
        timestamp: str | None = None,
        before_db: np.ndarray | None = None,
    ) -> list[Feature]:
        arr = np.asarray(array_db, dtype="float64")
        ts = self._stamp(timestamp)
        feats: list[Feature] = []
        group = "backscatter"
        feats.append(Feature("backscatter_mean_db", _safe_stat(arr, np.mean), "dB", source, ts, self.algorithm_version, group))
        feats.append(Feature("backscatter_median_db", _safe_stat(arr, np.median), "dB", source, ts, self.algorithm_version, group))
        feats.append(Feature("backscatter_std_db", _safe_stat(arr, np.std), "dB", source, ts, self.algorithm_version, group))
        feats.append(Feature("backscatter_min_db", _safe_stat(arr, np.min), "dB", source, ts, self.algorithm_version, group))
        feats.append(Feature("backscatter_max_db", _safe_stat(arr, np.max), "dB", source, ts, self.algorithm_version, group))
        feats.append(Feature("backscatter_variance_db2", _safe_stat(arr, np.var), "dB^2", source, ts, self.algorithm_version, group))
        # texture: local contrast via std of 3x3? approximate with gradient std
        try:
            gx = np.gradient(arr, axis=0)
            gy = np.gradient(arr, axis=1)
            grad = np.hypot(gx, gy)
            feats.append(Feature("backscatter_gradient_mean", _safe_stat(grad, np.mean), "dB/px", source, ts, self.algorithm_version, group))
            feats.append(Feature("backscatter_gradient_std", _safe_stat(grad, np.std), "dB/px", source, ts, self.algorithm_version, group))
        except Exception:  # noqa: BLE001
            pass
        if before_db is not None:
            b = np.asarray(before_db, dtype="float64")
            if b.shape == arr.shape:
                diff = arr - b
                ratio = arr / np.where(b == 0, np.nan, b)
                log_ratio = np.log(np.where(ratio <= 0, np.nan, ratio))
                feats.append(Feature("backscatter_change_db", _safe_stat(diff, np.mean), "dB", source, ts, self.algorithm_version, group))
                feats.append(Feature("backscatter_change_median_db", _safe_stat(diff, np.median), "dB", source, ts, self.algorithm_version, group))
                feats.append(Feature("backscatter_log_ratio_mean", _safe_stat(log_ratio, np.mean), "log", source, ts, self.algorithm_version, group))
                feats.append(Feature("backscatter_change_std_db", _safe_stat(diff, np.std), "dB", source, ts, self.algorithm_version, group))
        return feats

    def coherence_features(
        self,
        coherence: np.ndarray,
        *,
        source: str,
        timestamp: str | None = None,
        threshold: float = 0.3,
    ) -> list[Feature]:
        arr = np.asarray(coherence, dtype="float64")
        ts = self._stamp(timestamp)
        group = "coherence"
        feats: list[Feature] = []
        feats.append(Feature("coherence_mean", _safe_stat(arr, np.mean), "unitless", source, ts, self.algorithm_version, group))
        feats.append(Feature("coherence_median", _safe_stat(arr, np.median), "unitless", source, ts, self.algorithm_version, group))
        feats.append(Feature("coherence_std", _safe_stat(arr, np.std), "unitless", source, ts, self.algorithm_version, group))
        finite = arr[np.isfinite(arr)]
        if finite.size:
            low = float(np.mean(finite < threshold))
            feats.append(Feature("low_coherence_fraction", low, "fraction", source, ts, self.algorithm_version, group))
        return feats

    def deformation_features(
        self,
        displacement_mm: np.ndarray,
        *,
        source: str,
        timestamp: str | None = None,
        coherence: np.ndarray | None = None,
    ) -> list[Feature]:
        arr = np.asarray(displacement_mm, dtype="float64")
        ts = self._stamp(timestamp)
        group = "deformation"
        feats: list[Feature] = []
        feats.append(Feature("displacement_mean_mm", _safe_stat(arr, np.mean), "mm", source, ts, self.algorithm_version, group))
        feats.append(Feature("displacement_median_mm", _safe_stat(arr, np.median), "mm", source, ts, self.algorithm_version, group))
        feats.append(Feature("displacement_std_mm", _safe_stat(arr, np.std), "mm", source, ts, self.algorithm_version, group))
        feats.append(Feature("displacement_min_mm", _safe_stat(arr, np.min), "mm", source, ts, self.algorithm_version, group))
        feats.append(Feature("displacement_max_mm", _safe_stat(arr, np.max), "mm", source, ts, self.algorithm_version, group))
        # gradient
        try:
            gx = np.gradient(arr, axis=0)
            gy = np.gradient(arr, axis=1)
            grad = np.hypot(gx, gy)
            feats.append(Feature("displacement_gradient_mean", _safe_stat(grad, np.mean), "mm/px", source, ts, self.algorithm_version, group))
        except Exception:  # noqa: BLE001
            pass
        # magnitude persistence proxy: fraction of pixels above 10mm
        finite = arr[np.isfinite(arr)]
        if finite.size:
            feats.append(Feature("displacement_large_fraction", float(np.mean(np.abs(finite) >= 10.0)), "fraction", source, ts, self.algorithm_version, group))
        if coherence is not None:
            c = np.asarray(coherence, dtype="float64")
            if c.shape == arr.shape:
                low = (c < 0.3)
                feats.append(Feature("deformation_in_low_coherence_fraction", float(np.mean(low)), "fraction", source, ts, self.algorithm_version, group))
        return feats

    def temporal_features(
        self,
        series: np.ndarray,
        *,
        source: str,
        timestamps: list[str] | None = None,
    ) -> list[Feature]:
        arr = np.asarray(series, dtype="float64").ravel()
        ts = timestamps[-1] if timestamps else None
        group = "temporal"
        feats: list[Feature] = []
        feats.append(Feature("temporal_mean", _safe_stat(arr, np.mean), "unitless", source, ts, self.algorithm_version, group))
        feats.append(Feature("temporal_std", _safe_stat(arr, np.std), "unitless", source, ts, self.algorithm_version, group))
        feats.append(Feature("temporal_min", _safe_stat(arr, np.min), "unitless", source, ts, self.algorithm_version, group))
        feats.append(Feature("temporal_max", _safe_stat(arr, np.max), "unitless", source, ts, self.algorithm_version, group))
        # trend via simple linear slope (Theil-Sen preferred in processing; here lightweight)
        finite_idx = np.where(np.isfinite(arr))[0]
        if finite_idx.size >= 3:
            x = finite_idx.astype("float64")
            y = arr[finite_idx]
            try:
                slope = float(np.polyfit(x, y, 1)[0])
                if np.isfinite(slope):
                    feats.append(Feature("temporal_linear_slope", slope, "unit/epoch", source, ts, self.algorithm_version, group))
            except Exception:  # noqa: BLE001
                pass
        # change point count proxy: number of sign changes in first diff
        d = np.diff(arr)
        if d.size:
            sign_changes = int(np.sum((d[1:] * d[:-1]) < 0))
            feats.append(Feature("temporal_sign_changes", float(sign_changes), "count", source, ts, self.algorithm_version, group))
        return feats

    def polarimetric_features(
        self,
        vv_db: np.ndarray,
        vh_db: np.ndarray,
        *,
        source: str,
        timestamp: str | None = None,
    ) -> list[Feature]:
        vv = np.asarray(vv_db, dtype="float64")
        vh = np.asarray(vh_db, dtype="float64")
        ts = self._stamp(timestamp)
        group = "polarimetric"
        feats: list[Feature] = []
        if vv.shape == vh.shape:
            ratio = vv - vh
            feats.append(Feature("vv_vh_ratio_mean_db", _safe_stat(ratio, np.mean), "dB", source, ts, self.algorithm_version, group))
            feats.append(Feature("vv_vh_ratio_std_db", _safe_stat(ratio, np.std), "dB", source, ts, self.algorithm_version, group))
            feats.append(Feature("vv_mean_db", _safe_stat(vv, np.mean), "dB", source, ts, self.algorithm_version, group))
            feats.append(Feature("vh_mean_db", _safe_stat(vh, np.mean), "dB", source, ts, self.algorithm_version, group))
        return feats

    def spatial_features(
        self,
        mask: np.ndarray,
        *,
        source: str,
        timestamp: str | None = None,
        pixel_area_m2: float = 100.0,
    ) -> list[Feature]:
        m = np.asarray(mask, dtype=bool)
        ts = self._stamp(timestamp)
        group = "spatial"
        feats: list[Feature] = []
        area_px = int(np.count_nonzero(m))
        feats.append(Feature("changed_area_px", float(area_px), "px", source, ts, self.algorithm_version, group))
        feats.append(Feature("changed_area_m2", float(area_px * pixel_area_m2), "m^2", source, ts, self.algorithm_version, group))
        feats.append(Feature("changed_fraction", float(area_px / m.size) if m.size else 0.0, "fraction", source, ts, self.algorithm_version, group))
        # connected components count (4-connectivity) via scipy if available
        try:
            from scipy import ndimage

            labeled, n = ndimage.label(m)
            feats.append(Feature("connected_components", float(n), "count", source, ts, self.algorithm_version, group))
            if n > 0:
                sizes = np.array([int(np.sum(labeled == i)) for i in range(1, n + 1)])
                feats.append(Feature("largest_component_px", float(sizes.max()), "px", source, ts, self.algorithm_version, group))
                feats.append(Feature("component_size_std_px", float(sizes.std()), "px", source, ts, self.algorithm_version, group))
        except Exception:  # noqa: BLE001
            pass
        return feats

    def context_features(
        self,
        *,
        source: str,
        timestamp: str | None = None,
        distance_to_water_m: float | None = None,
        distance_to_road_m: float | None = None,
        distance_to_building_m: float | None = None,
        elevation_m: float | None = None,
        slope_deg: float | None = None,
        land_cover: str | None = None,
    ) -> list[Feature]:
        ts = self._stamp(timestamp)
        group = "context"
        feats: list[Feature] = []
        if distance_to_water_m is not None:
            feats.append(Feature("distance_to_water_m", float(distance_to_water_m), "m", source, ts, self.algorithm_version, group))
        if distance_to_road_m is not None:
            feats.append(Feature("distance_to_road_m", float(distance_to_road_m), "m", source, ts, self.algorithm_version, group))
        if distance_to_building_m is not None:
            feats.append(Feature("distance_to_building_m", float(distance_to_building_m), "m", source, ts, self.algorithm_version, group))
        if elevation_m is not None:
            feats.append(Feature("elevation_m", float(elevation_m), "m", source, ts, self.algorithm_version, group))
        if slope_deg is not None:
            feats.append(Feature("slope_deg", float(slope_deg), "deg", source, ts, self.algorithm_version, group))
        if land_cover is not None:
            feats.append(Feature("land_cover_code", None, "code", source, ts, self.algorithm_version, group, metadata={"land_cover": land_cover}))
        return feats

    def extract_all(self, payload: dict[str, Any]) -> list[Feature]:
        """Convenience: payload keys map to method kwargs. Returns merged list."""
        out: list[Feature] = []
        if "backscatter_db" in payload:
            out += self.backscatter_features(
                payload["backscatter_db"],
                source=payload.get("source", "unknown"),
                timestamp=payload.get("timestamp"),
                before_db=payload.get("backscatter_before_db"),
            )
        if "coherence" in payload:
            out += self.coherence_features(
                payload["coherence"],
                source=payload.get("source", "unknown"),
                timestamp=payload.get("timestamp"),
                threshold=payload.get("coherence_threshold", 0.3),
            )
        if "displacement_mm" in payload:
            out += self.deformation_features(
                payload["displacement_mm"],
                source=payload.get("source", "unknown"),
                timestamp=payload.get("timestamp"),
                coherence=payload.get("coherence"),
            )
        if "series" in payload:
            out += self.temporal_features(
                payload["series"],
                source=payload.get("source", "unknown"),
                timestamps=payload.get("timestamps"),
            )
        if "vv_db" in payload and "vh_db" in payload:
            out += self.polarimetric_features(
                payload["vv_db"],
                payload["vh_db"],
                source=payload.get("source", "unknown"),
                timestamp=payload.get("timestamp"),
            )
        if "mask" in payload:
            out += self.spatial_features(
                payload["mask"],
                source=payload.get("source", "unknown"),
                timestamp=payload.get("timestamp"),
                pixel_area_m2=payload.get("pixel_area_m2", 100.0),
            )
        out += self.context_features(
            source=payload.get("source", "unknown"),
            timestamp=payload.get("timestamp"),
            distance_to_water_m=payload.get("distance_to_water_m"),
            distance_to_road_m=payload.get("distance_to_road_m"),
            distance_to_building_m=payload.get("distance_to_building_m"),
            elevation_m=payload.get("elevation_m"),
            slope_deg=payload.get("slope_deg"),
            land_cover=payload.get("land_cover"),
        )
        return out

    def to_vector(self, features: list[Feature]) -> tuple[list[str], list[float]]:
        names = [f.name for f in features]
        values = [0.0 if f.value is None else float(f.value) for f in features]
        return names, values


def features_to_dict(features: list[Feature]) -> dict[str, float | None]:
    return {f.name: f.value for f in features}
