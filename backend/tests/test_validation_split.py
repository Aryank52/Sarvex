"""Tests for validation, split, dataset, error analysis."""
from __future__ import annotations

import numpy as np

from app.validation.pipeline import DataValidationPipeline
from app.training.split import DataSplitManager
from app.training.dataset import TrainingDatasetBuilder
from app.ml.error_analysis import analyze_errors


def test_validation_metadata_valid():
    v = DataValidationPipeline()
    r = v.validate_metadata({"product_id": "p", "provider": "x", "product_type": "GCOV", "acquisition_start": "2026-08-10T00:00:00Z", "bbox": [91.5, 26.0, 92.0, 26.4]})
    assert r.status in ("VALID", "WARNING")


def test_validation_metadata_invalid():
    v = DataValidationPipeline()
    r = v.validate_metadata({"product_id": None, "provider": None, "product_type": None, "acquisition_start": None, "bbox": None})
    assert r.status in ("INVALID", "PARTIAL")


def test_validation_array_nan():
    v = DataValidationPipeline()
    r = v.validate_array([[1.0, np.nan], [2.0, 3.0]])
    assert r.status in ("WARNING", "VALID")


def test_split_spatial_no_leakage():
    coords = [(91.5 + i * 0.01, 26.0 + j * 0.01) for i in range(20) for j in range(20)]
    m = DataSplitManager(seed=1).spatial_holdout(coords, test_size=0.2, val_size=0.1)
    assert not m.leakage_checks["train_test_overlap"]
    assert m.n_train + m.n_val + m.n_test == len(coords)


def test_split_temporal_order():
    ts = [f"2026-0{i+1}-01" for i in range(10)]
    m = DataSplitManager(seed=1).temporal_holdout(ts, test_fraction=0.2, val_fraction=0.1)
    assert not m.leakage_checks["train_test_overlap"]
    assert not m.leakage_checks["temporal_order_violation"]


def test_dataset_builder():
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    b = TrainingDatasetBuilder(["a", "b"])
    b.from_arrays(X, ["L1", "L2"], label_type="PSEUDO", label_source="test", label_confidence=0.5)
    assert b.summary()["n_samples"] == 2
    assert b.summary()["label_type_counts"]["PSEUDO"] == 2
    Xm, y, ids = b.to_matrix()
    assert Xm.shape == (2, 2)


def test_dataset_builder_rejects_bad_label_type():
    b = TrainingDatasetBuilder(["a"])
    try:
        b.add_sample(__import__("app.training.dataset", fromlist=["TrainingSample"]).TrainingSample(
            sample_id="s", feature_vector=[1.0], label="x", label_type="BAD", label_source="t", label_confidence=0.5
        ))
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_error_analysis():
    res = analyze_errors(["A", "B", "A"], ["A", "A", "B"])
    assert res["n_errors"] == 2
    assert res["error_rate"] > 0
    assert len(res["confusion_pairs"]) >= 1
