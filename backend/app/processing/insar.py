"""MODE B - InSAR displacement analysis.

The processor consumes higher-level interferometric products (GUNW/RUNW-like).
It does not unwrap phase itself; that responsibility belongs to ISCE3 or the
product provider. A missing wavelength, coherence band or georeferencing is a
hard error, never a fabricated result.

Limitations recorded with each result:
* line-of-sight only (no vertical/east-north decomposition),
* relative to the AOI median (unwrapped phase has an arbitrary reference),
* no orbital ramp estimation in this baseline.
"""
from __future__ import annotations

import numpy as np

from app.core.units import Unit
from app.processing.artifacts import save_categorical_layer, save_layer
from app.processing.base import FeatureSpec, ProcessContext, Processor, ProcessorOutput, TimeSeriesSpec
from app.processing.insar_utils import displacement_and_uncertainty, read_insar_pair, resolve_wavelength
from app.processing.stats import (
    change_fraction,
    cusum_change_point,
    logistic_confidence,
    morphological_cleanup,
    remove_small_components,
    robust_stats,
    smooth,
    theil_sen_trend,
)
from app.processing.vectorize import label_components, vectorize_components


class InSARProcessor(Processor):
    analysis_type = "deformation"
    algorithm = "gunw_los_displacement_mad_v1"
    algorithm_version = "1.0"
    result_type = "ground_deformation"
    required_product_types = ("GUNW", "RUNW")
    min_products = 1
    units = Unit.MILLIMETER.value

    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        p = ctx.parameters
        coherence_threshold = float(p.get("coherence_threshold", 0.3))
        min_disp_mm = float(p.get("min_displacement_mm", 10.0))
        looks = float(p.get("looks", 4.0))
        smoothing_sigma = float(p.get("smoothing_sigma", 0.0))
        min_area_px = int(p.get("min_area_px", 4))
        reference_mode = str(p.get("displacement_reference", "aoi_median"))

        ordered = sorted(ctx.inputs, key=lambda x: x.acquisition_start or "")
        latest = ordered[-1]
        pair = read_insar_pair(ctx, latest)
        disp, unc, coh_mask = displacement_and_uncertainty(
            pair, coherence_threshold=coherence_threshold, looks=looks
        )
        aoi_mask = pair.grid.mask_for_geometry(ctx.aoi_geometry)
        valid = np.isfinite(disp) & coh_mask & aoi_mask
        if smoothing_sigma > 0:
            disp = smooth(disp, smoothing_sigma, mask=valid)
        if reference_mode == "aoi_median" and np.isfinite(disp[valid]).any():
            reference = float(np.nanmedian(disp[valid]))
            disp = (disp - reference).astype("float32")
        else:
            reference = 0.0
        valid = np.isfinite(disp) & coh_mask & aoi_mask
        if not np.any(valid):
            from app.core.errors import ValidationError

            raise ValidationError(
                "No valid coherent pixels remain inside the AOI at the requested coherence threshold",
                detail={"coherence_threshold": coherence_threshold},
            )
        significant = valid & (np.abs(disp) >= min_disp_mm)
        significant = morphological_cleanup(significant, closing=1)
        significant = remove_small_components(significant, min_area_px)
        labels, n_components = label_components(significant)
        confidence_px = np.where(valid, np.clip(pair.coherence, 0, 1), np.nan).astype("float32")
        features_raw = vectorize_components(
            grid=pair.grid,
            labels=labels,
            values=disp,
            uncertainty=unc,
            confidence=confidence_px,
            max_features=int(p.get("max_features", 40)),
        )
        features: list[FeatureSpec] = []
        for f in features_raw:
            direction = "away_from_sensor" if f["value_median"] >= 0 else "toward_sensor"
            features.append(
                FeatureSpec(
                    feature_type="los_deformation_lobe",
                    geometry=f["geometry"],
                    value=f["value_median"],
                    unit="mm",
                    uncertainty=f.get("uncertainty"),
                    confidence=f.get("confidence"),
                    properties={
                        "area_m2": f["area_m2"],
                        "area_km2": f["area_m2"] / 1e6,
                        "pixels": f["pixels"],
                        "displacement_min_mm": f["value_min"],
                        "displacement_max_mm": f["value_max"],
                        "los_direction": direction,
                        "coherence_threshold": coherence_threshold,
                        "wavelength_m": pair.wavelength_m,
                        "displacement_reference": reference_mode,
                        "reference_value_mm": reference,
                        "line_of_sight_only": True,
                        "orbital_ramp_estimated": False,
                        "phase_band": pair.phase_band,
                        "coherence_band": pair.coherence_band,
                        "method": self.algorithm,
                        "algorithm_version": self.algorithm_version,
                        "acquisition": latest.acquisition_start,
                    },
                )
            )
        stats_vals = robust_stats(disp[valid])
        total_area = sum(f.properties["area_m2"] for f in features)
        mean_conf = float(np.nanmean(confidence_px[valid])) if np.any(valid) else None
        median_unc = float(np.nanmedian(unc[valid])) if np.any(valid) else None
        median_sig_disp = (
            float(np.nanmedian(np.abs(disp[significant]))) if significant.any() else 0.0
        )
        dates = [pr.acquisition_start for pr in ordered]
        stats = {
            "valid_pixels": int(np.count_nonzero(valid)),
            "significant_pixels": int(np.count_nonzero(significant)),
            "change_fraction": change_fraction(significant, valid),
            "n_components": n_components,
            "n_features": len(features),
            "total_deformation_area_m2": total_area,
            "total_deformation_area_km2": total_area / 1e6,
            "median_displacement_mm": stats_vals["median"],
            "p05_displacement_mm": stats_vals["p05"],
            "p95_displacement_mm": stats_vals["p95"],
            "min_displacement_mm": stats_vals["min"],
            "max_displacement_mm": stats_vals["max"],
            "median_uncertainty_mm": median_unc,
            "median_significant_displacement_mm": median_sig_disp,
            "coherence_threshold": coherence_threshold,
            "min_displacement_mm": min_disp_mm,
            "wavelength_m": pair.wavelength_m,
            "reference_mode": reference_mode,
            "reference_value_mm": reference,
            "acquisitions": dates,
            "product_ids": [pr.product_id for pr in ordered],
            "reader_notes": pair.notes,
            "limitations": [
                "Line-of-sight displacement only; no 2-D/3-D decomposition.",
                "Relative to the AOI median displacement.",
                "No orbital ramp estimation in this baseline.",
            ],
            "pixel_area_m2": pair.grid.pixel_area_m2(),
        }
        layers: dict = {}
        layers["phase"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="unwrapped_phase", array=pair.phase_rad,
            grid=pair.grid, title="Unwrapped interferometric phase", units="rad",
            method="As provided by interferometric product (not re-unwrapped)",
            source="SARVEX deterministic processing", ramp="difference", symmetric=True, mask=aoi_mask,
            product_ids=[latest.product_id], dates=[latest.acquisition_start],
        )
        layers["displacement"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="los_displacement", array=disp,
            grid=pair.grid, title="Line-of-sight displacement (after - reference)",
            units="mm", method=f"d = -lambda/(4*pi)*phase; lambda={pair.wavelength_m:.6f} m; reference={reference_mode}",
            source="SARVEX deterministic processing", ramp="displacement", symmetric=True, mask=valid,
            product_ids=[latest.product_id], dates=[latest.acquisition_start],
            extra={"wavelength_m": pair.wavelength_m, "sign_convention": "negative = toward sensor"},
        )
        layers["coherence"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="coherence", array=pair.coherence,
            grid=pair.grid, title="Interferometric coherence", units="unitless[0,1]",
            method="As provided by interferometric product", source="SARVEX deterministic processing",
            ramp="coherence", mask=aoi_mask, product_ids=[latest.product_id],
            dates=[latest.acquisition_start],
        )
        layers["uncertainty"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="displacement_uncertainty", array=unc,
            grid=pair.grid, title="Displacement uncertainty (1 sigma)", units="mm",
            method="Phase variance from coherence (Hanssen 2001 approximation), converted with wavelength",
            source="SARVEX deterministic processing", ramp="uncertainty", mask=valid,
            product_ids=[latest.product_id], dates=[latest.acquisition_start],
        )
        layers["deformation_mask"] = save_categorical_layer(
            ctx.store, result_id=ctx.result_id, name="deformation_mask", mask=significant, grid=pair.grid,
            title="Detected deformation mask",
            method=f"Coherence >= {coherence_threshold} and |LOS| >= {min_disp_mm} mm; {self.algorithm}",
            source="SARVEX deterministic processing", label="deformation detected", color="#ffb000",
        )
        timeseries: list[TimeSeriesSpec] = []
        points = []
        for product in ordered:
            if product is latest:
                value = float(np.nanmedian(disp[valid])) if np.any(valid) else None
                uncertainty = median_unc
            else:
                try:
                    other = read_insar_pair(ctx, product)
                    other_disp, other_unc, other_mask = displacement_and_uncertainty(
                        other, coherence_threshold=coherence_threshold, looks=looks
                    )
                    mask = other_mask & other.grid.mask_for_geometry(ctx.aoi_geometry)
                    if np.any(mask):
                        ref = float(np.nanmedian(other_disp[mask]))
                        value = float(np.nanmedian(other_disp[mask] - ref))
                        uncertainty = float(np.nanmedian(other_unc[mask]))
                    else:
                        value, uncertainty = None, None
                except Exception:  # noqa: BLE001 - one unreadable pair must not hide the main result
                    value, uncertainty = None, None
            points.append(
                {
                    "date": product.acquisition_start,
                    "value": value,
                    "unit": "mm",
                    "uncertainty": uncertainty,
                    "method": "aoi_median_relative_los",
                    "wavelength_m": resolve_wavelength(product),
                    "source_product": product.product_id,
                }
            )
        if len(points) >= 2:
            from datetime import datetime

            parsed = []
            for pt in points:
                try:
                    parsed.append(datetime.fromisoformat(str(pt["date"]).replace("Z", "+00:00")))
                except (ValueError, TypeError):
                    parsed.append(None)
            t0 = min(d for d in parsed if d is not None)
            for pt, dt in zip(points, parsed):
                pt["t"] = (dt - t0).total_seconds() / 86400.0 if dt else None
            trend = theil_sen_trend(points)
            cusum = cusum_change_point(np.array([pt["value"] for pt in points if pt["value"] is not None]))
            change_points = (
                [{"index": cusum.change_index, "shift_mm": cusum.mean_shift}] if cusum.change_index is not None else []
            )
            timeseries.append(
                TimeSeriesSpec(
                    series_type="aoi_los_displacement_median",
                    unit="mm",
                    points=points,
                    trend=trend,
                    change_points=change_points,
                    confidence=mean_conf,
                )
            )
        direction_text = (
            "The sign convention is negative toward the sensor; positive away from the sensor. "
        )
        summary = (
            f"Line-of-sight interferometric displacement was converted from unwrapped phase using "
            f"wavelength {pair.wavelength_m:.4f} m and coherence threshold {coherence_threshold}. "
            f"{len(features)} deformation region(s) exceeded {min_disp_mm} mm, covering "
            f"{total_area / 1e6:.3f} km2. {direction_text}"
            "Values are relative to the AOI median and are LOS-only; this is a DETECTED displacement "
            "pattern, not a confirmed geophysical cause."
        )
        return ProcessorOutput(
            result_type=self.result_type,
            summary=summary,
            statistics=stats,
            units="mm",
            confidence=mean_conf,
            uncertainty=median_unc,
            layers=layers,
            feature_type="los_deformation_lobe",
            features=features,
            event_type="GROUND_DEFORMATION",
            taxonomy_stage="DETECTED",
            classification_method=self.algorithm,
            event_summary=(
                f"Detected LOS displacement with median |d| {median_sig_disp:.2f} mm over "
                f"{total_area / 1e6:.3f} km2 (relative to AOI median). LOS-only, no causal attribution."
            ),
            timeseries=timeseries,
        )
