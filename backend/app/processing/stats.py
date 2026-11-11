"""Robust statistics and transparent change detection primitives."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage, stats


def robust_stats(values: np.ndarray) -> dict[str, float]:
    """Median/MAD-based statistics over finite values only."""
    data = np.asarray(values, dtype="float64")
    data = data[np.isfinite(data)]
    if data.size == 0:
        return {"n": 0, "median": float("nan"), "mad": float("nan"), "sigma": float("nan"), "mean": float("nan"), "std": float("nan")}
    med = float(np.median(data))
    mad = float(np.median(np.abs(data - med)))
    sigma = 1.4826 * mad
    if sigma == 0.0:
        sigma = float(np.std(data))
    return {
        "n": int(data.size),
        "median": med,
        "mad": mad,
        "sigma": sigma,
        "mean": float(np.mean(data)),
        "std": float(np.std(data)),
        "p05": float(np.percentile(data, 5)),
        "p95": float(np.percentile(data, 95)),
        "min": float(np.min(data)),
        "max": float(np.max(data)),
    }


def robust_zscore(values: np.ndarray, baseline: np.ndarray | None = None) -> tuple[np.ndarray, dict[str, float]]:
    """Robust z-score using median/MAD estimated from a baseline (or values)."""
    ref = values if baseline is None else baseline
    st = robust_stats(ref)
    med = st["median"]
    sigma = st["sigma"]
    if not math.isfinite(med):
        return np.full_like(values, np.nan, dtype="float32"), st
    if not math.isfinite(sigma) or sigma <= 1e-12:
        sigma = 1e-6
    z = (values - med) / sigma
    return z.astype("float32"), st


def mad_sigma(values: np.ndarray) -> float:
    st = robust_stats(values)
    return float(st["sigma"]) if math.isfinite(st["sigma"]) else float("nan")


def logistic_confidence(abs_z: np.ndarray, threshold: float) -> np.ndarray:
    """Map |z| to [0,1] confidence around the detection threshold."""
    x = np.asarray(abs_z, dtype="float32") - float(threshold)
    return (1.0 / (1.0 + np.exp(-x))).astype("float32")


def change_fraction(mask: np.ndarray, valid: np.ndarray) -> float:
    denom = int(np.count_nonzero(valid))
    if denom == 0:
        return 0.0
    return float(np.count_nonzero(mask & valid) / denom)


def remove_small_components(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    if min_pixels <= 1 or not mask.any():
        return mask
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if count == 0:
        return mask
    sizes = np.bincount(labels.ravel())
    keep = sizes >= min_pixels
    keep[0] = False
    return keep[labels]


def morphological_cleanup(mask: np.ndarray, opening: int = 0, closing: int = 0) -> np.ndarray:
    out = mask
    if opening > 0:
        out = ndimage.binary_opening(out, structure=np.ones((opening, opening), dtype=bool))
    if closing > 0:
        out = ndimage.binary_closing(out, structure=np.ones((closing, closing), dtype=bool))
    return out


def smooth(arr: np.ndarray, sigma: float, *, mask: np.ndarray | None = None) -> np.ndarray:
    """Gaussian smoothing with NaN-aware local normalisation."""
    if sigma <= 0:
        return arr.astype("float32")
    data = np.asarray(arr, dtype="float64")
    valid = np.isfinite(data)
    if mask is not None:
        valid &= mask
    filled = np.where(valid, data, 0.0)
    weights = ndimage.gaussian_filter(valid.astype("float64"), sigma=sigma, mode="nearest")
    blurred = ndimage.gaussian_filter(filled, sigma=sigma, mode="nearest")
    out = np.where(weights > 1e-6, blurred / np.maximum(weights, 1e-6), np.nan)
    return out.astype("float32")


@dataclass
class CusumResult:
    mean_shift: float
    change_index: int | None
    statistic: float
    positive: np.ndarray
    negative: np.ndarray


def cusum_change_point(values: np.ndarray, threshold_sigma: float = 4.0) -> CusumResult:
    """Two-sided CUSUM change-point test on a 1-D series."""
    data = np.asarray(values, dtype="float64")
    finite = data[np.isfinite(data)]
    if finite.size < 4:
        return CusumResult(float("nan"), None, 0.0, np.zeros_like(data), np.zeros_like(data))
    mean = float(np.mean(finite))
    std = float(np.std(finite, ddof=1))
    if std <= 0:
        return CusumResult(0.0, None, 0.0, np.zeros_like(data), np.zeros_like(data))
    z = (data - mean) / std
    z = np.where(np.isfinite(z), z, 0.0)
    pos = np.cumsum(z)
    neg = np.cumsum(-z)
    stat = max(float(np.max(np.abs(pos))), float(np.max(np.abs(neg))))
    if stat < threshold_sigma:
        return CusumResult(0.0, None, stat, pos, neg)
    idx = int(np.argmax(np.abs(pos))) if np.max(np.abs(pos)) >= np.max(np.abs(neg)) else int(np.argmax(np.abs(neg)))
    before = data[: idx + 1]
    after = data[idx + 1 :]
    shift = float(np.nanmean(after) - np.nanmean(before)) if after.size else 0.0
    return CusumResult(shift, idx, stat, pos, neg)


def theil_sen_trend(points: list[dict]) -> dict[str, float | str | None]:
    """Robust linear trend with units per year; inputs are chronological."""
    clean = [
        (float(p["t"]), float(p["value"]))
        for p in points
        if p.get("value") is not None and p.get("t") is not None
    ]
    if len(clean) < 3:
        return {"slope": None, "intercept": None, "unit": "per_year", "method": "insufficient_points", "n": len(clean)}
    x = np.array([c[0] for c in clean])
    y = np.array([c[1] for c in clean])
    slope, intercept, low, high = stats.theilslopes(y, x, alpha=0.95)
    return {
        "slope": float(slope) * 365.25,
        "slope_ci_low": float(low) * 365.25,
        "slope_ci_high": float(high) * 365.25,
        "intercept": float(intercept),
        "unit": "per_year",
        "method": "theil_sen_v1",
        "n": len(clean),
    }


def pearson(x: np.ndarray, y: np.ndarray) -> float:
    a = np.asarray(x, dtype="float64")
    b = np.asarray(y, dtype="float64")
    valid = np.isfinite(a) & np.isfinite(b)
    if np.count_nonzero(valid) < 3:
        return float("nan")
    return float(np.corrcoef(a[valid], b[valid])[0, 1])
