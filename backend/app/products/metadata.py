"""Normalized product metadata model shared by all adapters."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NormalizedProductMetadata(BaseModel):
    """The normalized metadata contract required from every NISAR adapter.

    Missing values remain ``None``. Adapters are forbidden from inventing
    acquisition parameters, calibration states or geometry.
    """

    provider: str | None = None
    mission: str | None = "NISAR"
    satellite: str | None = None
    product_type: str = "UNKNOWN"
    product_id: str
    acquisition_start: str | None = None
    acquisition_end: str | None = None
    orbit: int | None = None
    pass_direction: str | None = None
    track: int | None = None
    frame: int | None = None
    frequency_band: str | None = None
    frequency_hz: float | None = None
    polarization: str | None = None
    wavelength_m: float | None = None
    crs: str | None = None
    bbox: list[float] | None = None
    geometry: dict[str, Any] | None = None
    spatial_resolution_m: float | None = None
    units: str | None = None
    processing_baseline: str | None = None
    source_url: str | None = None
    source_identifier: str | None = None
    checksum: str | None = None
    file_format: str | None = None
    file_size: int | None = None
    quality_indicators: dict[str, Any] = Field(default_factory=dict)
    calibration_status: str | None = None
    extraction_method: str = "metadata_tags"
    extraction_notes: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)

    def raise_if_invalid(self) -> None:
        if not self.valid:
            from app.core.errors import ValidationError

            raise ValidationError(
                "Product failed validation", detail={"errors": self.errors, "checks": self.checks}
            )
