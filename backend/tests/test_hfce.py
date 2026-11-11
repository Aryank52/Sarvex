"""Tests for SARVEX-HFCE."""
from __future__ import annotations

import numpy as np

from app.ml.hfce import SarvexHFCE, EVENT_TYPES


def test_hfce_untrained_predict():
    model = SarvexHFCE(feature_names=["a", "b"])
    pred = model.predict({"a": 1.0, "b": 2.0})
    assert pred.event_type in EVENT_TYPES
    assert 0.0 <= pred.change_probability <= 1.0
    assert 0.0 <= pred.confidence <= 1.0
    assert 0.0 <= pred.uncertainty <= 1.0


def test_hfce_train_and_predict():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(120, 4))
    y = (X[:, 0] > 0).astype(int)
    # map 0/1 to event indices 0 and 2
    y = np.where(y == 1, 2, 0)
    names = ["f0", "f1", "f2", "f3"]
    model = SarvexHFCE(feature_names=names)
    model.fit(X, y, feature_names=names)
    assert model.trained
    pred = model.predict(X[0].tolist(), feature_names=names)
    assert pred.event_type in EVENT_TYPES
    assert len(pred.probabilities) == len(EVENT_TYPES)


def test_hfce_save_load(tmp_path):
    rng = np.random.default_rng(1)
    X = rng.normal(size=(80, 3))
    y = np.array([i % 3 for i in range(80)])
    names = ["a", "b", "c"]
    model = SarvexHFCE(feature_names=names)
    model.fit(X, y, feature_names=names)
    model.save(tmp_path / "m")
    loaded = SarvexHFCE.load(tmp_path / "m")
    assert loaded.trained
    assert loaded.feature_names == names
    p1 = model.predict(X[0].tolist(), feature_names=names)
    p2 = loaded.predict(X[0].tolist(), feature_names=names)
    assert p1.event_type == p2.event_type


def test_hfce_explain():
    model = SarvexHFCE(feature_names=["a"])
    e = model.explain()
    assert e["model"] == "SARVEX-HFCE"
    assert "weights" in e
    assert abs(sum(e["weights"].values()) - 1.0) < 1e-9


def test_hfce_deterministic_baseline_bounds():
    model = SarvexHFCE()
    s = model.deterministic_baseline_score({"backscatter_change_median_db": 10.0, "changed_fraction": 0.5})
    assert 0.0 <= s <= 1.0
    assert model.deterministic_baseline_score({}) == 0.0
