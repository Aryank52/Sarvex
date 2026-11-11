"""MODE C - Dual-polarization feature intelligence.

This baseline is deliberately limited to dual-pol observables. Full covariance
decompositions (H/A/alpha, Freeman-Durden, etc.) require calibrated quad-pol
covariance data and are exposed as a separate capability, not approximated.
"""
from __future__ import annotations

import numpy as np

from app.processing.artifacts import save_categorical_layer, save_layer
from app.processing.backscatter_utils import to_db
from app.processing.base import FeatureSpec, ProcessContext, Processor, ProcessorOutput
from app.processing.raster import RasterData, align_to, read_raster
from app.processing.stats import (
    change_fraction,
    logistic_confidence,
    morphological_cleanup,
    remove_small_components,
    robust_stats,
)
from app.processing.vectorize import label_components, vectorize_components


class PolarimetricProcessor(Processor):
    analysis_type = "polarimetric"
    algorithm = "dual_pol_ratio_features_v1"
    algorithm_version = "1.0"
    result_type = "polarimetric_features"
    required_product_types = ("GCOV",)
    min_products = 1

    def _read_channels(self, ctx: ProcessContext, product, reference: RasterData | None) -> tuple[np.ndarray, np.ndarray, RasterData]:
        from app.core.errors import ValidationError

        raster = read_raster(product.path, geometry=ctx.aoi_geometry)
        aligned = raster if reference is None else align_to(reference, raster)
        vv_idx = aligned.band_index_by_keyword("vv")
        vh_idx = aligned.band_index_by_keyword("vh")
        params = ctx.parameters
        if vv_idx is None and "vv_band" in params:
            vv_idx = int(params["vv_band"])
        if vh_idx is None and "vh_band" in params:
            vh_idx = int(params["vh_band"])
        if vv_idx is None or vh_idx is None:
            raise ValidationError(
                "Dual-pol analysis requires identifiable VV and VH bands (descriptions or vv_band/vh_band parameters)",
                detail={"descriptions": aligned.descriptions, "product": product.product_id},
            )
        vv, _ = to_db(aligned.band(vv_idx), product.units, str(ctx.parameters.get("input_scale", "auto")))
        vh, _ = to_db(aligned.band(vh_idx), product.units, str(ctx.parameters.get("input_scale", "auto")))
        return vv, vh, aligned

    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        p = ctx.parameters
        threshold_db = float(p.get("ratio_change_threshold_db", 1.5))
        min_area_px = int(p.get("min_area_px", 6))
        ordered = sorted(ctx.inputs, key=lambda x: x.acquisition_start or "")
        reference: RasterData | None = None
        channels = []
        for product in ordered:
            vv, vh, grid = self._read_channels(ctx, product, reference)
            if reference is None:
                reference = grid
            ratio = (vv - vh).astype("float32")
            channels.append({"product": product, "grid": grid, "vv": vv, "vh": vh, "ratio": ratio})
        assert reference is not None
        aoi_mask = reference.mask_for_geometry(ctx.aoi_geometry)
        layers: dict = {}
        last = channels[-1]
        layers["vv"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="vv_backscatter", array=last["vv"], grid=reference,
            title="VV co-polarized backscatter", units="dB", method="Dual-pol channel extraction",
            source="SARVEX deterministic processing", ramp="backscatter", mask=aoi_mask,
            product_ids=[last["product"].product_id], dates=[last["product"].acquisition_start],
        )
        layers["vh"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="vh_backscatter", array=last["vh"], grid=reference,
            title="VH cross-polarized backscatter", units="dB", method="Dual-pol channel extraction",
            source="SARVEX deterministic processing", ramp="backscatter", mask=aoi_mask,
            product_ids=[last["product"].product_id], dates=[last["product"].acquisition_start],
        )
        layers["ratio"] = save_layer(
            ctx.store, result_id=ctx.result_id, name="vv_vh_ratio", array=last["ratio"], grid=reference,
            title="VV/VH ratio (dB)", units="dB", method="vv_db - vh_db",
            source="SARVEX deterministic processing", ramp="ratio", mask=aoi_mask,
            product_ids=[last["product"].product_id], dates=[last["product"].acquisition_start],
        )
        features: list[FeatureSpec] = []
        timeseries = []
        stats: dict = {
            "n_epochs": len(channels),
            "product_ids": [c["product"].product_id for c in channels],
            "acquisitions": [c["product"].acquisition_start for c in channels],
            "channels": ["VV", "VH"],
            "decomposition": "none (dual-pol features only)",
        }
        confidence_val = None
        if len(channels) >= 2:
            before = channels[0]
            after = channels[-1]
            valid = (
                np.isfinite(before["ratio"]) & np.isfinite(after["ratio"]) & aoi_mask
            )
            ratio_change = np.where(valid, after["ratio"] - before["ratio"], np.nan).astype("float32")
            vv_change = np.where(valid, after["vv"] - before["vv"], np.nan).astype("float32")
            vh_change = np.where(valid, after["vh"] - before["vh"], np.nan).astype("float32")
            abs_change = np.abs(ratio_change)
            confidence = np.where(valid, logistic_confidence(abs_change, threshold_db), np.nan).astype("float32")
            mask = valid & (abs_change >= threshold_db)
            mask = morphological_cleanup(mask, closing=1)
            mask = remove_small_components(mask, min_area_px)
            labels, n_components = label_components(mask)
            raw = vectorize_components(
                grid=reference, labels=labels, values=ratio_change, uncertainty=None,
                confidence=confidence, max_features=int(p.get("max_features", 30)),
            )
            for f in raw:
                vh_delta = float(np.nanmedian(vh_change[labels == f["label"]]))
                vv_delta = float(np.nanmedian(vv_change[labels == f["label"]]))
                candidates = []
                if f["value_median"] > 0 and vh_delta < 0:
                    candidates.append("VEGETATION_STRUCTURE_CHANGE_CANDIDATE")
                if abs(vv_delta) > abs(vh_delta):
                    candidates.append("SURFACE_ROUGHNESS_CHANGE_CANDIDATE")
                features.append(
                    FeatureSpec(
                        feature_type="polarimetric_change_segment",
                        geometry=f["geometry"],
                        value=f["value_median"],
                        unit="dB",
                        uncertainty=None,
                        confidence=f.get("confidence"),
                        properties={
                            "area_m2": f["area_m2"],
                            "area_km2": f["area_m2"] / 1e6,
                            "pixels": f["pixels"],
                            "ratio_change_db": f["value_median"],
                            "vv_change_db": vv_delta,
                            "vh_change_db": vh_delta,
                            "candidate_labels": candidates,
                            "classification_basis": "transparent dual-pol ratio rule; requires independent validation",
                            "method": self.algorithm,
                            "algorithm_version": self.algorithm_version,
                        },
                    )
                )
            changed_values = ratio_change[mask]
            mean_conf = float(np.nanmean(confidence[mask])) if mask.any() else float(np.nanmean(confidence[valid])) if valid.any() else None
            confidence_val = mean_conf
            total_area = sum(f.properties["area_m2"] for f in features)
            layers["ratio_change"] = save_layer(
                ctx.store, result_id=ctx.result_id, name="polarimetric_ratio_change", array=ratio_change,
                grid=reference, title="VV/VH ratio change (after - before)", units="dB",
                method=f"Signed dual-pol ratio change; {self.algorithm}",
                source="SARVEX deterministic processing", ramp="difference", symmetric=True, mask=valid,
                product_ids=[before["product"].product_id, after["product"].product_id],
                dates=[before["product"].acquisition_start, after["product"].acquisition_start],
            )
            layers["vv_change"] = save_layer(
                ctx.store, result_id=ctx.result_id, name="vv_change", array=vv_change, grid=reference,
                title="VV backscatter change", units="dB", method="Signed difference",
                source="SARVEX deterministic processing", ramp="difference", symmetric=True, mask=valid,
            )
            layers["vh_change"] = save_layer(
                ctx.store, result_id=ctx.result_id, name="vh_change", array=vh_change, grid=reference,
                title="VH backscatter change", units="dB", method="Signed difference",
                source="SARVEX deterministic processing", ramp="difference", symmetric=True, mask=valid,
            )
            layers["change_mask"] = save_categorical_layer(
                ctx.store, result_id=ctx.result_id, name="polarimetric_change_mask", mask=mask,
                grid=reference, title="Polarimetric change mask",
                method=f"|ratio change| >= {threshold_db} dB; {self.algorithm}",
                source="SARVEX deterministic processing", label="polarimetric change",
            )
            stats.update(
                {
                    "valid_pixels": int(np.count_nonzero(valid)),
                    "changed_pixels": int(np.count_nonzero(mask)),
                    "change_fraction": change_fraction(mask, valid),
                    "n_components": n_components,
                    "n_features": len(features),
                    "total_change_area_m2": total_area,
                    "total_change_area_km2": total_area / 1e6,
                    "median_ratio_change_db": float(np.median(changed_values)) if changed_values.size else 0.0,
                    "ratio_change_threshold_db": threshold_db,
                }
            )
            summary = (
                f"Dual-pol analysis compared VV/VH ratios between {before['product'].acquisition_start} "
                f"and {after['product'].acquisition_start}. {len(features)} region(s) exceeded "
                f"{threshold_db} dB ratio change, covering {total_area / 1e6:.3f} km2. "
                "Candidate categories are rule-based hypotheses from dual-pol observables and require "
                "independent validation; no full covariance decomposition was performed."
            )
        else:
            stats.update({"valid_pixels": int(np.count_nonzero(np.isfinite(last['ratio']) & aoi_mask)), "n_features": 0})
            summary = (
                "Characterized dual-pol VV, VH and VV/VH ratio over one acquisition. "
                "A temporal polarimetric change requires at least two products."
            )
        return ProcessorOutput(
            result_type=self.result_type,
            summary=summary,
            statistics=stats,
            units="dB",
            confidence=confidence_val,
            uncertainty=None,
            layers=layers,
            feature_type="polarimetric_change_segment",
            features=features,
            event_type="SURFACE_DISTURBANCE",
            taxonomy_stage="CLASSIFIED" if features else "DETECTED",
            classification_method=self.algorithm if features else None,
            event_summary=(
                "Rule-based dual-polarization change candidates detected; candidate labels are hypotheses "
                "requiring independent validation."
            ),
        )
