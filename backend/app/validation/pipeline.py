"""Data validation pipeline for newly ingested NISAR products."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


@dataclass
class ValidationIssue:
    code: str
    severity: str  # error | warning
    message: str
    field: str | None = None


@dataclass
class ValidationResult:
    status: str  # VALID | INVALID | WARNING | PARTIAL
    issues: list[ValidationIssue] = field(default_factory=list)
    metadata_completeness: float = 0.0
    checked_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": [asdict(i) for i in self.issues],
            "metadata_completeness": self.metadata_completeness,
            "checked_fields": self.checked_fields,
        }


REQUIRED_METADATA = [
    "product_id",
    "provider",
    "product_type",
    "acquisition_start",
    "bbox",
]


def _is_finite_number(v: Any) -> bool:
    try:
        return isinstance(v, (int, float)) and np.isfinite(v)
    except Exception:  # noqa: BLE001
        return False


class DataValidationPipeline:
    def __init__(self, required: list[str] | None = None) -> None:
        self.required = required or REQUIRED_METADATA

    def validate_metadata(self, metadata: dict[str, Any]) -> ValidationResult:
        issues: list[ValidationIssue] = []
        checked: list[str] = []
        present = 0
        for field_name in self.required:
            checked.append(field_name)
            if metadata.get(field_name) is None:
                issues.append(ValidationIssue("missing_metadata", "error", f"Missing required field {field_name}", field_name))
            else:
                present += 1
        # bbox validity
        bbox = metadata.get("bbox")
        if bbox is not None:
            checked.append("bbox_validity")
            if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                issues.append(ValidationIssue("invalid_bbox", "error", "bbox must be [minx,miny,maxx,maxy]", "bbox"))
            else:
                try:
                    minx, miny, maxx, maxy = [float(x) for x in bbox]
                    if not (minx < maxx and miny < maxy):
                        issues.append(ValidationIssue("invalid_bbox", "error", "bbox min must be < max", "bbox"))
                    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
                        issues.append(ValidationIssue("bbox_out_of_range", "warning", "bbox outside WGS84 range", "bbox"))
                except (TypeError, ValueError):
                    issues.append(ValidationIssue("invalid_bbox", "error", "bbox values not numeric", "bbox"))
        # acquisition time
        if metadata.get("acquisition_start") is not None:
            checked.append("acquisition_time")
            try:
                from datetime import datetime

                datetime.fromisoformat(str(metadata["acquisition_start"]).replace("Z", "+00:00"))
            except ValueError:
                issues.append(ValidationIssue("invalid_timestamp", "error", "acquisition_start not ISO-8601", "acquisition_start"))
        # CRS
        crs = metadata.get("crs")
        if crs is not None:
            checked.append("crs")
            if not isinstance(crs, str) or not crs.strip():
                issues.append(ValidationIssue("invalid_crs", "warning", "CRS should be a non-empty string", "crs"))
        # completeness
        total = len(self.required) + 3
        completeness = present / max(len(self.required), 1)
        # status
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        if errors:
            status = "INVALID" if len(errors) >= 2 else "PARTIAL"
        elif warnings:
            status = "WARNING"
        elif completeness < 1.0:
            status = "PARTIAL"
        else:
            status = "VALID"
        return ValidationResult(status=status, issues=issues, metadata_completeness=float(completeness), checked_fields=checked)

    def validate_array(self, arr: Any, *, name: str = "array") -> ValidationResult:
        issues: list[ValidationIssue] = []
        checked = ["shape", "dtype", "finite", "nan", "inf"]
        a = None
        try:
            a = np.asarray(arr, dtype="float64")
        except Exception as e:  # noqa: BLE001
            issues.append(ValidationIssue("invalid_array", "error", f"Cannot convert to array: {e}", name))
            return ValidationResult(status="INVALID", issues=issues, checked_fields=checked)
        if a.size == 0:
            issues.append(ValidationIssue("empty_array", "error", "Array is empty", name))
        nan_count = int(np.isnan(a).sum()) if np.issubdtype(a.dtype, np.floating) else 0
        inf_count = int(np.isinf(a).sum()) if np.issubdtype(a.dtype, np.floating) else 0
        if nan_count > 0:
            issues.append(ValidationIssue("nan_values", "warning" if nan_count < a.size * 0.5 else "error", f"{nan_count} NaN values", name))
        if inf_count > 0:
            issues.append(ValidationIssue("inf_values", "error", f"{inf_count} Inf values", name))
        if a.ndim < 2:
            issues.append(ValidationIssue("low_dimensionality", "warning", f"Array ndim={a.ndim}", name))
        errors = [i for i in issues if i.severity == "error"]
        status = "INVALID" if errors else ("WARNING" if issues else "VALID")
        return ValidationResult(status=status, issues=issues, checked_fields=checked)

    def validate_product(self, metadata: dict[str, Any], array: Any | None = None) -> ValidationResult:
        mr = self.validate_metadata(metadata)
        if array is not None:
            ar = self.validate_array(array)
            mr.issues.extend(ar.issues)
            mr.checked_fields.extend(ar.checked_fields)
            if ar.status == "INVALID":
                mr.status = "INVALID"
            elif ar.status == "WARNING" and mr.status == "VALID":
                mr.status = "WARNING"
        return mr
