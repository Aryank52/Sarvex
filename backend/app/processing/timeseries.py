"""Multi-temporal analytics.

Mode uses the transparent backscatter detector plus full temporal summary:
trend, change points, gaps, persistence and recurrence. Two timestamps are never
treated as a time series; at least three observations are required.
"""
from __future__ import annotations

from app.processing.backscatter import BackscatterProcessor
from app.processing.base import ProcessContext, ProcessorOutput


class TimeSeriesProcessor(BackscatterProcessor):
    analysis_type = "timeseries"
    algorithm = "multitemporal_mad_theilsen_v1"
    algorithm_version = "1.0"
    result_type = "timeseries"
    required_product_types = ("GCOV", "GSLC")
    min_products = 3

    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        output = super().run(ctx)
        output.result_type = self.result_type
        output.statistics["temporal_analysis"] = "Theil-Sen trend + CUSUM change points on AOI medians"
        output.statistics["n_epochs"] = len(ctx.inputs)
        if output.timeseries:
            ts = output.timeseries[0]
            values = [pt["value"] for pt in ts.points if pt.get("value") is not None]
            if values:
                median = sorted(values)[len(values) // 2]
                deviations = [abs(v - median) for v in values]
                tol = max(float(output.statistics.get("robust_sigma_db", 0.0)) * 3.0, 1.0)
                output.statistics["persistence_fraction"] = sum(d > tol for d in deviations) / len(deviations)
            output.statistics["trend_db_per_year"] = ts.trend.get("slope")
            output.statistics["change_points"] = ts.change_points
        output.summary = output.summary.replace(
            "Temporal backscatter change analysis",
            "Multi-temporal backscatter analysis",
        )
        return output
