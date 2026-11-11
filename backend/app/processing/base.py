"""Processing contracts shared by every SAR analysis mode."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.units import Unit
from app.storage.object_store import ObjectStore


@dataclass
class InputProduct:
    db_id: str
    product_id: str
    product_type: str
    path: Path
    provider: str
    acquisition_start: str | None
    acquisition_end: str | None = None
    frequency_band: str | None = None
    frequency_hz: float | None = None
    polarization: str | None = None
    wavelength_m: float | None = None
    units: str | None = None
    crs: str | None = None
    bbox: list[float] = field(default_factory=list)
    dataset_id: str | None = None
    observation_id: str | None = None
    is_demo: bool = False
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class ProcessContext:
    job_id: str
    result_id: str
    aoi_geometry: dict[str, Any]
    aoi_name: str
    inputs: list[InputProduct]
    parameters: dict[str, Any]
    store: ObjectStore
    is_demo: bool = False
    request_id: str | None = None


@dataclass
class FeatureSpec:
    feature_type: str
    geometry: dict[str, Any] | None
    value: float | None
    unit: str
    uncertainty: float | None = None
    confidence: float | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class TimeSeriesSpec:
    series_type: str
    unit: str
    points: list[dict[str, Any]]
    trend: dict[str, Any] = field(default_factory=dict)
    change_points: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None


@dataclass
class ProcessorOutput:
    result_type: str
    summary: str
    statistics: dict[str, Any]
    units: str
    confidence: float | None
    uncertainty: float | None
    layers: dict[str, Any] = field(default_factory=dict)
    feature_type: str = "change_segment"
    features: list[FeatureSpec] = field(default_factory=list)
    event_type: str = "SURFACE_DISTURBANCE"
    taxonomy_stage: str = "DETECTED"
    classification_method: str | None = None
    event_summary: str = ""
    timeseries: list[TimeSeriesSpec] = field(default_factory=list)
    change_map: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


class Processor(ABC):
    analysis_type: str = "unknown"
    algorithm: str = "unknown"
    algorithm_version: str = "1.0"
    result_type: str = "analysis"
    required_product_types: tuple[str, ...] = ()
    min_products: int = 2
    units: str = Unit.UNITLESS.value

    def validate(self, ctx: ProcessContext) -> None:
        from app.core.errors import ValidationError

        if len(ctx.inputs) < self.min_products:
            raise ValidationError(
                f"{self.analysis_type} requires at least {self.min_products} product(s); got {len(ctx.inputs)}"
            )
        if self.required_product_types:
            unsupported = [
                p.product_type for p in ctx.inputs if p.product_type not in self.required_product_types
            ]
            if unsupported:
                raise ValidationError(
                    f"{self.analysis_type} accepts {sorted(self.required_product_types)}; got {sorted(set(unsupported))}"
                )
        for p in ctx.inputs:
            if not p.path.exists():
                raise ValidationError(f"Materialized input is missing: {p.product_id}")

    @abstractmethod
    def run(self, ctx: ProcessContext) -> ProcessorOutput:
        ...

    def metadata(self) -> dict[str, Any]:
        return {
            "analysis_type": self.analysis_type,
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "required_product_types": list(self.required_product_types),
            "min_products": self.min_products,
        }
