"""Offset tracking baseline using phase correlation on amplitude images.

This is a transparent, non-parametric offset estimator. It reports image-axis
offsets with subpixel interpolation and approximate ground metres derived from
the raster footprint. It does not claim range/azimuth decomposition unless the
product metadata explicitly encodes those axes.
"""
from __future__ import annotations

import numpy as np

from app.processing.artifacts import save_layer
from app.processing.base import FeatureSpec, ProcessContext, Processor, ProcessorOutput
from app.processing.raster import RasterData, align_to, read_raster
from app.processing.stats import robust_stats


class OffsetProcessor(Processor):
    analysis_type = "offsets"
    algorithm = "phase_correlation_offset_v1"
    algorithm_version = "1.0"
    result_type = "offsets"
    required_product_types = ()
    min_products = 2
    units = "px"

    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        from app.core.errors import ValidationError

        ordered = sorted(ctx.inputs, key=lambda x: x.acquisition_start or "")
        before_product, after_product = ordered[0], ordered[-1]
        before_raster = read_raster(before_product.path, geometry=ctx.aoi_geometry)
        after_raster = read_raster(after_product.path, geometry=ctx.aoi_geometry)
        after_aligned = align_to(before_raster, after_raster)
        before_db = self._amplitude_db(before_raster.band(0), before_product.units)
        after_db = self._amplitude_db(after_aligned.band(0), after_product.units)
        valid = np.isfinite(before_db) & np.isfinite(after_db) & before_raster.mask_for_geometry(ctx.aoi_geometry)
        if np.count_nonzero(valid) < 64:
            raise ValidationError("Insufficient valid overlapping pixels for offset estimation")
        a = np.where(valid, before_db, np.nan)
        b = np.where(valid, after_db, np.nan)
        a = _fill_nan(a)
        b = _fill_nan(b)
        shift_y, shift_x, quality = _phase_correlation(a, b)
        ny, nx = a.shape
        bbox = before_raster.bbox_wgs84()
        from pyproj import Geod

        geod = Geod(ellps="WGS84")
        mid_lat = (bbox[1] + bbox[3]) / 2
        width_m = abs(geod.inv(bbox[0], mid_lat, bbox[2], mid_lat)[2])
        height_m = abs(geod.inv(bbox[0], bbox[1], bbox[0], bbox[3])[2])
        mpp_x = width_m / max(nx, 1)
        mpp_y = height_m / max(ny, 1)
        offset_x_m = shift_x * mpp_x
        offset_y_m = shift_y * mpp_y
        magnitude_px = float(np.hypot(shift_x, shift_y))
        magnitude_m = float(np.hypot(offset_x_m, offset_y_m))
        confidence = float(1.0 - np.exp(-max(quality, 0.0) / 4.0))
        uncertainty_m = float(np.hypot(mpp_x, mpp_y) * 0.5)
        from shapely.geometry import mapping, Point

        centroid = Point(
            (before_raster.transform.c + (nx / 2) * before_raster.transform.a),
            (before_raster.transform.f + (ny / 2) * before_raster.transform.e),
        )
        from rasterio.warp import transform_geom

        geom = mapping(centroid)
        if before_raster.crs and before_raster.crs.to_string() != "EPSG:4326":
            geom = transform_geom(before_raster.crs, "EPSG:4326", geom)
        feature = FeatureSpec(
            feature_type="image_offset",
            geometry=dict(geom),
            value=magnitude_m,
            unit="m",
            uncertainty=uncertainty_m,
            confidence=confidence,
            properties={
                "shift_x_px": float(shift_x),
                "shift_y_px": float(shift_y),
                "offset_x_m": offset_x_m,
                "offset_y_m": offset_y_m,
                "magnitude_px": magnitude_px,
                "magnitude_m": magnitude_m,
                "pixel_spacing_x_m": mpp_x,
                "pixel_spacing_y_m": mpp_y,
                "peak_quality": float(quality),
                "axis_convention": "image x/y axes; not decomposed into radar range/azimuth",
                "method": self.algorithm,
                "algorithm_version": self.algorithm_version,
            },
        )
        layers = {}
        layers["before"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="before_amplitude", array=before_db,
            grid=before_raster, title="Prior amplitude (dB)", units="dB", method="Amplitude for offset tracking",
            source="SARVEX deterministic processing", ramp="backscatter", mask=valid,
            product_ids=[before_product.product_id], dates=[before_product.acquisition_start],
        )
        layers["after"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="after_amplitude", array=after_db,
            grid=before_raster, title="Later amplitude (dB)", units="dB", method="Amplitude for offset tracking",
            source="SARVEX deterministic processing", ramp="backscatter", mask=valid,
            product_ids=[after_product.product_id], dates=[after_product.acquisition_start],
        )
        stats_vals = robust_stats((b - a)[valid])
        stats = {
            "shift_x_px": float(shift_x),
            "shift_y_px": float(shift_y),
            "offset_x_m": offset_x_m,
            "offset_y_m": offset_y_m,
            "magnitude_px": magnitude_px,
            "magnitude_m": magnitude_m,
            "peak_quality": float(quality),
            "confidence": confidence,
            "uncertainty_m": uncertainty_m,
            "pixel_spacing_x_m": mpp_x,
            "pixel_spacing_y_m": mpp_y,
            "valid_pixels": int(np.count_nonzero(valid)),
            "amplitude_change_median_db": stats_vals["median"],
            "method": self.algorithm,
            "product_ids": [before_product.product_id, after_product.product_id],
            "acquisitions": [before_product.acquisition_start, after_product.acquisition_start],
            "limitations": [
                "Single global offset estimate, not a spatially varying offset field.",
                "Image-axis offsets; conversion to radar range/azimuth requires geometry metadata.",
            ],
        }
        summary = (
            f"Phase-correlation offset analysis estimated an image-axis shift of "
            f"({shift_x:.2f}, {shift_y:.2f}) px, equivalent to approximately {magnitude_m:.2f} m "
            f"on the ground using footprint-derived pixel spacing. Peak quality {quality:.2f}. "
            "This is a DETECTED offset measurement, not a deformation mechanism."
        )
        return ProcessorOutput(
            result_type=self.result_type,
            summary=summary,
            statistics=stats,
            units="m",
            confidence=confidence,
            uncertainty=uncertainty_m,
            layers=layers,
            feature_type="image_offset",
            features=[feature],
            event_type="UNCLASSIFIED_CHANGE",
            taxonomy_stage="DETECTED",
            classification_method=self.algorithm,
            event_summary=(
                f"Image-axis offset of approximately {magnitude_m:.2f} m detected between acquisitions; "
                "not decomposed into range/azimuth or vertical motion."
            ),
        )

    @staticmethod
    def _amplitude_db(band: np.ndarray, units: str | None) -> np.ndarray:
        arr = np.asarray(band, dtype="float32")
        unit_low = (units or "").lower()
        finite = arr[np.isfinite(arr)]
        is_db = "db" in unit_low or (finite.size > 0 and float(np.median(finite)) < -1.0)
        if is_db:
            return arr
        return (10.0 * np.log10(np.maximum(arr, 1e-10))).astype("float32")


def _fill_nan(arr: np.ndarray) -> np.ndarray:
    out = arr.copy()
    if not np.isnan(out).any():
        return out
    fill = float(np.nanmedian(out)) if np.isfinite(out).any() else 0.0
    out[np.isnan(out)] = fill
    return out


def _phase_correlation(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """Return (shift_y_px, shift_x_px, peak_quality) between a and b."""
    a0 = a - np.nanmean(a)
    b0 = b - np.nanmean(b)
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype("float32")
    fa = np.fft.fft2(a0 * window)
    fb = np.fft.fft2(b0 * window)
    cross = fb * np.conj(fa)
    cross /= np.maximum(np.abs(cross), 1e-12)
    corr = np.fft.ifft2(cross).real
    corr -= corr.mean()
    std = corr.std()
    peak_idx = np.unravel_index(np.argmax(corr), corr.shape)
    peak = float(corr[peak_idx])
    quality = float(peak / std) if std > 0 else 0.0
    shift_y, shift_x = _subpixel(corr, peak_idx)
    ny, nx = a.shape
    if shift_y > ny / 2:
        shift_y -= ny
    if shift_x > nx / 2:
        shift_x -= nx
    return float(shift_y), float(shift_x), quality


def _subpixel(corr: np.ndarray, idx: tuple[int, int]) -> tuple[float, float]:
    y, x = idx
    def refine(prev: float, center: float, nxt: float) -> float:
        denom = prev - 2 * center + nxt
        if abs(denom) < 1e-12:
            return 0.0
        return float(0.5 * (prev - nxt) / denom)
    dy = refine(corr[y - 1, x], corr[y, x], corr[(y + 1) % corr.shape[0], x]) if corr.shape[0] > 2 else 0.0
    dx = refine(corr[y, x - 1], corr[y, x], corr[y, (x + 1) % corr.shape[1]]) if corr.shape[1] > 2 else 0.0
    return y + dy, x + dx
