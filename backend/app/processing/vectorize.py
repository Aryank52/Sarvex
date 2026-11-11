"""Vectorization of raster masks into evidence features."""
from __future__ import annotations

from typing import Any

import numpy as np
from rasterio.warp import transform_geom
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from app.core.geometry import geometry_area_m2
from app.processing.raster import RasterData


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    labels, count = ndimage.label(mask.astype(bool), structure=np.ones((3, 3), dtype=int))
    return labels, int(count)


def component_stats(labels: np.ndarray, values: np.ndarray, uncertainty: np.ndarray | None, confidence: np.ndarray | None) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    count = int(labels.max()) if labels.size else 0
    for label in range(1, count + 1):
        sel = labels == label
        if not np.any(sel):
            continue
        vals = values[sel]
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        entry: dict[str, float] = {
            "pixels": int(vals.size),
            "value_median": float(np.median(vals)),
            "value_mean": float(np.mean(vals)),
            "value_min": float(np.min(vals)),
            "value_max": float(np.max(vals)),
        }
        if uncertainty is not None:
            u = uncertainty[sel]
            u = u[np.isfinite(u)]
            if u.size:
                entry["uncertainty_median"] = float(np.median(u))
        if confidence is not None:
            c = confidence[sel]
            c = c[np.isfinite(c)]
            if c.size:
                entry["confidence_mean"] = float(np.mean(c))
        out[label] = entry
    return out


def vectorize_components(
    *,
    grid: RasterData,
    labels: np.ndarray,
    values: np.ndarray,
    uncertainty: np.ndarray | None,
    confidence: np.ndarray | None,
    max_features: int = 60,
    simplify_pixels: float = 0.5,
) -> list[dict[str, Any]]:
    """Turn labeled components into WGS84 GeoJSON features with geodesic areas."""
    from rasterio.features import shapes

    stats_by_label = component_stats(labels, values, uncertainty, confidence)
    features: list[dict[str, Any]] = []
    # Shapes are generated per label to keep memory bounded and geometry valid.
    for label, st in sorted(stats_by_label.items(), key=lambda kv: kv[1]["pixels"], reverse=True)[:max_features]:
        mask = labels == label
        polygons = []
        for geom, _val in shapes(labels.astype("int32"), mask=mask, transform=grid.transform):
            if geom.get("type") in {"Polygon", "MultiPolygon"}:
                polygons.append(shape(geom))
        if not polygons:
            continue
        merged = unary_union(polygons)
        if grid.crs and grid.crs.to_string() != "EPSG:4326":
            geom_wgs = transform_geom(grid.crs, "EPSG:4326", mapping(merged))
        else:
            geom_wgs = mapping(merged)
        geom_wgs = _clean_geometry(geom_wgs)
        if geom_wgs is None:
            continue
        try:
            area = geometry_area_m2(geom_wgs)
        except Exception:  # noqa: BLE001
            area = st["pixels"] * grid.pixel_area_m2()
        feature = {
            "label": label,
            "geometry": geom_wgs,
            "area_m2": float(area),
            "pixel_area_m2": float(grid.pixel_area_m2()),
            "pixels": st["pixels"],
            "value_median": st["value_median"],
            "value_mean": st["value_mean"],
            "value_min": st["value_min"],
            "value_max": st["value_max"],
            "uncertainty": st.get("uncertainty_median"),
            "confidence": st.get("confidence_mean"),
        }
        features.append(feature)
    return features


def _clean_geometry(geom: dict[str, Any]) -> dict[str, Any] | None:
    try:
        g = shape(geom)
        if g.is_empty:
            return None
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty:
            return None
        if g.geom_type not in {"Polygon", "MultiPolygon"}:
            g = g.buffer(0)
        return dict(mapping(g))
    except Exception:  # noqa: BLE001
        return None
