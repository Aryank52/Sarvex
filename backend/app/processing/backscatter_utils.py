"""Radar backscatter utilities: calibration-aware dB handling and stacks."""
from __future__ import annotations

import numpy as np

from app.processing.base import InputProduct, ProcessContext
from app.processing.raster import RasterData, align_to, read_raster


def to_db(array: np.ndarray, units: str | None, scale: str = "auto") -> tuple[np.ndarray, str]:
    """Convert a backscatter raster to dB with an explicit recorded decision."""
    arr = np.asarray(array, dtype="float32")
    unit_low = (units or "").lower()
    if scale == "db" or "db" in unit_low:
        return arr, "input_declared_db"
    if scale == "linear":
        return _linear_to_db(arr), "linear_power_to_db"
    # Auto: negative values indicate dB; strictly positive <= ~1 suggests power.
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return arr, "empty"
    median = float(np.median(finite))
    if median > 1.5 or np.percentile(finite, 99) > 10:
        return _linear_to_db(arr), "auto_linear_power_to_db"
    if median < -3:
        return arr, "auto_declared_db"
    return _linear_to_db(np.maximum(arr, 1e-6)), "auto_linear_power_to_db"


def _linear_to_db(arr: np.ndarray) -> np.ndarray:
    floor = 1e-10
    return (10.0 * np.log10(np.maximum(arr, floor))).astype("float32")


def select_backscatter_band(raster: RasterData, product: InputProduct) -> np.ndarray:
    """Select the co-pol band by default, never mixing polarizations silently."""
    idx = 0
    if product.polarization and "+" in product.polarization:
        preferred = product.polarization.split("+")[0].upper()
        found = raster.band_index_by_keyword(preferred.lower())
        if found is not None:
            idx = found
    return raster.band(idx)


def load_backscatter_stack(ctx: ProcessContext) -> tuple[list[np.ndarray], RasterData, list[InputProduct], list[str]]:
    """Read, convert and align all inputs to a common grid; returns dB grids."""
    ordered = sorted(ctx.inputs, key=lambda p: p.acquisition_start or "")
    grids: list[RasterData] = []
    products: list[InputProduct] = []
    notes: list[str] = []
    reference: RasterData | None = None
    for product in ordered:
        raster = read_raster(product.path, geometry=ctx.aoi_geometry)
        if reference is None:
            reference = raster
            aligned = raster
        else:
            aligned = align_to(reference, raster)
        band = select_backscatter_band(aligned, product)
        db, decision = to_db(band, product.units, str(ctx.parameters.get("input_scale", "auto")))
        notes.append(f"{product.product_id}:{decision}")
        grids.append(
            RasterData(
                data=db[np.newaxis, :, :],
                transform=aligned.transform,
                crs=aligned.crs,
                descriptions=[aligned.descriptions[0] if aligned.descriptions else ""],
                tags=aligned.tags,
            )
        )
        products.append(product)
    if reference is None:
        raise ValueError("No inputs provided")
    return [g.band(0) for g in grids], reference, products, notes


def stack_timeseries(aoi_geometry: dict, ctx: ProcessContext) -> tuple[list[dict], dict]:
    """Compute per-epoch AOI summary statistics for backscatter products."""
    from app.processing.stats import robust_stats, theil_sen_trend

    points: list[dict] = []
    ordered = sorted(ctx.inputs, key=lambda p: p.acquisition_start or "")
    for product in ordered:
        raster = read_raster(product.path, geometry=aoi_geometry)
        band = select_backscatter_band(raster, product)
        db, _ = to_db(band, product.units, str(ctx.parameters.get("input_scale", "auto")))
        mask = raster.mask_for_geometry(aoi_geometry)
        values = db[mask]
        st = robust_stats(values)
        if st["n"] == 0:
            continue
        acq = product.acquisition_start
        points.append(
            {
                "date": acq,
                "value": st["median"],
                "unit": "dB",
                "mean": st["mean"],
                "p05": st["p05"],
                "p95": st["p95"],
                "valid_fraction": float(st["n"] / max(int(np.count_nonzero(mask)), 1)),
                "uncertainty": float(st["sigma"] / np.sqrt(max(st["n"], 1))),
                "method": "aoi_robust_median",
                "source_product": product.product_id,
            }
        )
    # Time axis in fractional days since first observation.
    from datetime import datetime

    def _dt(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    dates = [_dt(p["date"]) for p in points]
    valid_dates = [d for d in dates if d is not None]
    if valid_dates:
        t0 = min(valid_dates)
        for p, d in zip(points, dates):
            p["t"] = (d - t0).total_seconds() / 86400.0 if d else None
    trend = theil_sen_trend(points)
    return points, trend
