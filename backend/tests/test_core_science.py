"""Unit tests for scientific units, taxonomy, geometry and robust statistics."""
from __future__ import annotations

import math

import numpy as np
import pytest

from app.core.geometry import (
    GeometryValidationError,
    geometry_area_m2,
    geometry_bbox,
    overlap_ratio,
    safe_join,
    sanitize_filename,
    validate_geojson_geometry,
)
from app.core.taxonomy import EvidenceStage, STAGE_DESCRIPTIONS, can_promote
from app.core.units import (
    UnitError,
    db_to_linear_power,
    linear_power_to_db,
    phase_to_displacement_mm,
    phase_to_los_displacement,
)
from app.processing.stats import (
    cusum_change_point,
    logistic_confidence,
    morphological_cleanup,
    remove_small_components,
    robust_stats,
    robust_zscore,
    theil_sen_trend,
)

ASSAM = {
    "type": "Polygon",
    "coordinates": [
        [[91.55, 26.05], [91.95, 26.05], [91.95, 26.32], [91.55, 26.32], [91.55, 26.05]]
    ],
}


def test_db_linear_roundtrip():
    for value in (-25.0, -10.5, 0.0, 3.25):
        assert linear_power_to_db(db_to_linear_power(value)) == pytest.approx(value, abs=1e-9)


def test_phase_displacement_scalar_and_array():
    wavelength = 0.2385
    assert phase_to_los_displacement(math.pi, wavelength) == pytest.approx(-wavelength / 4.0)
    array = np.array([0.0, math.pi, 2 * math.pi], dtype="float32")
    result = phase_to_los_displacement(array, wavelength)
    assert isinstance(result, np.ndarray)
    assert result.shape == array.shape
    assert result[1] == pytest.approx(-wavelength / 4.0, rel=1e-6)
    assert phase_to_displacement_mm(2 * math.pi, wavelength) == pytest.approx(-wavelength * 1000 / 2)


def test_phase_requires_positive_wavelength():
    with pytest.raises(UnitError):
        phase_to_los_displacement(0.1, 0.0)


def test_taxonomy_promotion_and_descriptions():
    assert can_promote(EvidenceStage.DETECTED, EvidenceStage.CLASSIFIED)
    assert not can_promote(EvidenceStage.CONFIRMED, EvidenceStage.DETECTED)
    assert STAGE_DESCRIPTIONS[EvidenceStage.CONFIRMED].startswith("Supported by")


def test_geometry_validation_bbox_and_area():
    geometry = validate_geojson_geometry(ASSAM)
    bbox = geometry_bbox(geometry)
    assert bbox == pytest.approx([91.55, 26.05, 91.95, 26.32])
    area = geometry_area_m2(geometry)
    # Roughly 40 km x 30 km; assert a defensible order of magnitude only.
    assert 1.0e9 < area < 2.0e9


def test_geometry_rejects_bad_coordinates():
    with pytest.raises(GeometryValidationError):
        validate_geojson_geometry({"type": "Point", "coordinates": [500, 100]})
    with pytest.raises(GeometryValidationError):
        validate_geojson_geometry({"type": "Polygon", "coordinates": []})


def test_overlap_ratio_bounded():
    event = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
    }
    asset = {
        "type": "Polygon",
        "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]],
    }
    ratio = overlap_ratio(event, asset)
    assert 0.0 < ratio < 1.0


def test_safe_join_and_filename_sanitization(tmp_path):
    target = safe_join(tmp_path, "nested/file.tif")
    assert tmp_path in target.parents
    with pytest.raises(ValueError):
        safe_join(tmp_path, "../escape.tif")
    assert sanitize_filename("../../evil name?.tif") == "evil name_.tif"


def test_robust_stats_and_zscore_detect_outlier():
    baseline = np.array([1.0, 1.1, 0.9, 1.05, 0.95, 1.0], dtype="float64")
    stats = robust_stats(baseline)
    assert stats["n"] == 6
    assert stats["median"] == pytest.approx(1.0)
    z, _ = robust_zscore(np.array([1.0, 1.0, 8.0]), baseline)
    assert abs(float(z[2])) > 20
    assert abs(float(z[0])) < 1e-6


def test_logistic_confidence_monotonic_and_bounded():
    values = np.array([0.0, 3.5, 7.0, 20.0], dtype="float32")
    confidence = logistic_confidence(values, 3.5)
    assert np.all(np.diff(confidence) >= 0)
    assert np.all(confidence > 0) and np.all(confidence < 1)


def test_cusum_detects_persistent_shift():
    series = np.array([5.0, 5.1, 4.9, 5.0, 5.05, 9.0, 9.1, 8.9, 9.05], dtype="float64")
    result = cusum_change_point(series, threshold_sigma=3.0)
    assert result.change_index is not None
    assert 3 <= result.change_index <= 5
    assert result.mean_shift > 3.0


def test_theil_sen_recovers_slope_per_year():
    # 0.01 dB/day -> ~3.6525 dB/year
    points = [
        {"t": float(day), "value": 10.0 + 0.01 * day}
        for day in range(0, 400, 20)
    ]
    trend = theil_sen_trend(points)
    assert trend["slope"] == pytest.approx(3.6525, rel=0.02)
    assert trend["slope_ci_low"] <= trend["slope"] <= trend["slope_ci_high"]


def test_morphology_and_component_filtering():
    mask = np.zeros((20, 20), dtype=bool)
    mask[2:6, 2:6] = True
    mask[10, 10] = True
    kept = remove_small_components(mask, min_pixels=5)
    assert kept[3, 3]
    assert not kept[10, 10]
    cleaned = morphological_cleanup(mask, opening=2, closing=1)
    assert cleaned.shape == mask.shape
