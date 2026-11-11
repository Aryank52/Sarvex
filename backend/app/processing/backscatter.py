"""MODE A - Backscatter change detection.

Transparent baseline:
1. temporal median baseline over all but the latest epoch (or the earlier
   scene for a pair),
2. robust z-score from median absolute deviation,
3. magnitude + significance thresholds,
4. morphological cleanup and connected-component vectorization.

No causal labels are produced. Output confidence is a detection confidence,
not a probability that a specific hazard occurred.
"""
from __future__ import annotations

import numpy as np

from app.core.units import Unit
from app.processing.artifacts import save_categorical_layer, save_layer
from app.processing.backscatter_utils import load_backscatter_stack, stack_timeseries
from app.processing.base import FeatureSpec, ProcessContext, Processor, ProcessorOutput, TimeSeriesSpec
from app.processing.stats import (
    change_fraction,
    cusum_change_point,
    logistic_confidence,
    morphological_cleanup,
    remove_small_components,
    robust_stats,
    robust_zscore,
    smooth,
)
from app.processing.vectorize import label_components, vectorize_components


class BackscatterProcessor(Processor):
    analysis_type = "backscatter"
    algorithm = "temporal_median_mad_v1"
    algorithm_version = "1.0"
    result_type = "backscatter_change"
    required_product_types = ("GCOV", "GSLC")
    min_products = 2
    units = Unit.DB.value

    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        p = ctx.parameters
        z_threshold = float(p.get("z_threshold", 3.5))
        min_change_db = float(p.get("min_change_db", 1.0))
        min_area_px = int(p.get("min_area_px", 6))
        smoothing_sigma = float(p.get("smoothing_sigma", 0.0))
        opening = int(p.get("morph_opening_px", 0))
        closing = int(p.get("morph_closing_px", 1))
        temporal_median = bool(p.get("temporal_median", True))

        stack, reference, products, conversion_notes = load_backscatter_stack(ctx)
        aoi_mask = reference.mask_for_geometry(ctx.aoi_geometry)
        if smoothing_sigma > 0:
            stack = [smooth(s, smoothing_sigma) for s in stack]
        if len(stack) == 2 or not temporal_median:
            before = stack[0]
            baseline_note = f"single prior epoch ({products[0].product_id})"
        else:
            before = np.nanmedian(np.stack(stack[:-1], axis=0), axis=0)
            baseline_note = f"temporal median of {len(stack) - 1} prior epochs"
        after = stack[-1]
        valid = np.isfinite(before) & np.isfinite(after) & aoi_mask
        if not np.any(valid):
            from app.core.errors import ValidationError

            raise ValidationError("No overlapping valid pixels inside the AOI for backscatter analysis")
        diff = np.where(valid, after - before, np.nan).astype("float32")
        ratio_db = diff  # difference of dB values equals log ratio
        z, base_stats = robust_zscore(diff, diff[valid])
        sigma = float(base_stats["sigma"])
        abs_z = np.abs(z)
        confidence = np.where(valid, logistic_confidence(abs_z, z_threshold), np.nan).astype("float32")
        uncertainty = np.where(valid, sigma, np.nan).astype("float32")

        mask = valid & (abs_z >= z_threshold) & (np.abs(diff) >= min_change_db)
        mask = morphological_cleanup(mask, opening=opening, closing=closing)
        mask = remove_small_components(mask, min_area_px)
        labels, n_components = label_components(mask)
        features_raw = vectorize_components(
            grid=reference,
            labels=labels,
            values=diff,
            uncertainty=uncertainty,
            confidence=confidence,
            max_features=int(p.get("max_features", 40)),
        )
        features: list[FeatureSpec] = []
        for f in features_raw:
            px = max(int(f["pixels"]), 1)
            direction = "decrease" if f["value_median"] < 0 else "increase"
            features.append(
                FeatureSpec(
                    feature_type="backscatter_change_segment",
                    geometry=f["geometry"],
                    value=f["value_median"],
                    unit="dB",
                    uncertainty=float(np.sqrt(px) * sigma / px),
                    confidence=f["confidence"],
                    properties={
                        "area_m2": f["area_m2"],
                        "area_km2": f["area_m2"] / 1e6,
                        "area_hectares": f["area_m2"] / 1e4,
                        "pixels": px,
                        "value_min_db": f["value_min"],
                        "value_max_db": f["value_max"],
                        "direction": direction,
                        "ratio_db": f["value_median"],
                        "linear_ratio": float(10 ** (f["value_median"] / 10)),
                        "method": self.algorithm,
                        "algorithm_version": self.algorithm_version,
                        "baseline": baseline_note,
                        "z_threshold": z_threshold,
                        "min_change_db": min_change_db,
                    },
                )
            )

        changed_pixels = int(np.count_nonzero(mask))
        valid_pixels = int(np.count_nonzero(valid))
        total_area = sum(f.properties["area_m2"] for f in features)
        changed_values = diff[mask]
        changed_median = float(np.median(changed_values)) if changed_values.size else 0.0
        mean_conf = float(np.nanmean(confidence[mask])) if mask.any() else float(np.nanmean(confidence[valid])) if valid.any() else None
        dates = [pr.acquisition_start for pr in products]
        stats = {
            "valid_pixels": valid_pixels,
            "changed_pixels": changed_pixels,
            "change_fraction": change_fraction(mask, valid),
            "n_components": n_components,
            "n_features": len(features),
            "total_change_area_m2": total_area,
            "total_change_area_km2": total_area / 1e6,
            "median_change_db": changed_median,
            "median_absolute_change_db": float(np.median(np.abs(changed_values))) if changed_values.size else 0.0,
            "baseline_median_db": base_stats["median"],
            "robust_sigma_db": sigma,
            "z_threshold": z_threshold,
            "min_change_db": min_change_db,
            "n_epochs": len(products),
            "baseline": baseline_note,
            "acquisitions": dates,
            "product_ids": [pr.product_id for pr in products],
            "unit_decisions": conversion_notes,
            "pixel_area_m2": reference.pixel_area_m2(),
        }
        layers = {}
        layers["before"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="before_backscatter", array=before, grid=reference,
            title="Prior backscatter baseline", units="dB", method=f"Backscatter {self.algorithm}",
            source="SARVEX deterministic processing", ramp="backscatter", mask=aoi_mask,
            product_ids=[pr.product_id for pr in products], dates=dates,
        )
        latest = products[-1].acquisition_start if products else None
        layers["after"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="after_backscatter", array=after, grid=reference,
            title="Latest backscatter", units="dB", method=f"Backscatter {self.algorithm}",
            source="SARVEX deterministic processing", ramp="backscatter", mask=aoi_mask,
            product_ids=[latest] if latest else [], dates=[latest] if latest else [],
        )
        layers["difference"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="backscatter_difference", array=diff, grid=reference,
            title="Backscatter difference (after - baseline)", units="dB", method=f"Signed difference; {self.algorithm}",
            source="SARVEX deterministic processing", ramp="difference", symmetric=True, mask=valid,
            product_ids=[pr.product_id for pr in products], dates=dates,
        )
        layers["change_mask"] = save_categorical_layer(
            ctx.store, result_id=ctx.result_id, name="change_mask", mask=mask, grid=reference,
            title="Detected change mask", method=f"MAD z >= {z_threshold} and |delta| >= {min_change_db} dB; {self.algorithm}",
            source="SARVEX deterministic processing", label="detected change",
        )
        layers["confidence"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="confidence", array=confidence, grid=reference,
            title="Detection confidence", units="unitless[0,1]", method=f"Logistic of |z| about threshold {z_threshold}",
            source="SARVEX deterministic processing", ramp="confidence", mask=valid,
        )
        timeseries_points, trend = stack_timeseries(ctx.aoi_geometry, ctx)
        timeseries = []
        if len(timeseries_points) >= 2:
            tvals = np.array([pt["value"] for pt in timeseries_points], dtype="float64")
            cusum = cusum_change_point(tvals)
            change_points = (
                [{"index": cusum.change_index, "date": timeseries_points[cusum.change_index].get("date"), "shift_db": cusum.mean_shift}]
                if cusum.change_index is not None
                else []
            )
            timeseries.append(
                TimeSeriesSpec(
                    series_type="aoi_backscatter_median",
                    unit="dB",
                    points=timeseries_points,
                    trend=trend,
                    change_points=change_points,
                    gaps=_find_gaps(timeseries_points),
                    confidence=mean_conf,
                )
            )
        summary = (
            f"Temporal backscatter change analysis used {len(products)} acquisition(s) and a {baseline_note}. "
            f"The robust MAD z-score (threshold {z_threshold}) combined with a minimum |delta sigma0| of "
            f"{min_change_db} dB detected {len(features)} connected change region(s) covering "
            f"{total_area / 1e6:.3f} km2 ({stats['change_fraction'] * 100:.2f}% of valid AOI pixels). "
            f"Median change within detected regions is {changed_median:.2f} dB. "
            "This is a DETECTED surface-change pattern, not a causal attribution."
        )
        return ProcessorOutput(
            result_type=self.result_type,
            summary=summary,
            statistics=stats,
            units="dB",
            confidence=mean_conf,
            uncertainty=sigma,
            layers=layers,
            feature_type="backscatter_change_segment",
            features=features,
            event_type="SURFACE_DISTURBANCE",
            taxonomy_stage="DETECTED",
            classification_method=self.algorithm,
            event_summary=(
                f"Detected backscatter change of {changed_median:.2f} dB (median) over {total_area / 1e6:.3f} km2 "
                f"using {self.algorithm}. Detectability only; cause not established."
            ),
            timeseries=timeseries,
            change_map={
                "method": self.algorithm,
                "threshold": z_threshold,
                "change_fraction": stats["change_fraction"],
                "statistics": stats,
                "confidence": mean_conf,
            },
        )


class ChangeDetectionProcessor(BackscatterProcessor):
    """Generic stack-based transparent change detector (MAD/CUSUM baseline)."""

    analysis_type = "change_detection"
    algorithm = "temporal_median_mad_cusum_v1"
    algorithm_version = "1.0"
    result_type = "change_detection"
    required_product_types = ()

    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        output = super().run(ctx)
        output.result_type = self.result_type
        output.statistics["change_detector"] = self.algorithm
        if output.change_map:
            output.change_map["method"] = self.algorithm
        return output


def _find_gaps(points: list[dict]) -> list[dict]:
    from datetime import datetime

    dates = []
    for pt in points:
        try:
            dates.append(datetime.fromisoformat(str(pt["date"]).replace("Z", "+00:00")))
        except (ValueError, TypeError):
            dates.append(None)
    valid = [d for d in dates if d]
    if len(valid) < 3:
        return []
    diffs = sorted((b - a).days for a, b in zip(valid, valid[1:]))
    median = diffs[len(diffs) // 2]
    gaps = []
    for i in range(1, len(valid)):
        delta = (valid[i] - valid[i - 1]).days
        if delta > 2 * max(median, 1):
            gaps.append({"start": valid[i - 1].isoformat(), "end": valid[i].isoformat(), "days": delta})
    return gaps
