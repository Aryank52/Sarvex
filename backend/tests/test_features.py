"""Tests for SARFeatureEngine."""
from __future__ import annotations

import numpy as np

from app.features.engine import SARFeatureEngine


def test_backscatter_features_basic():
    arr = np.array([[1.0, 2.0], [3.0, 4.0]])
    engine = SARFeatureEngine()
    feats = engine.backscatter_features(arr, source="test", timestamp="t")
    names = {f.name for f in feats}
    assert "backscatter_mean_db" in names
    assert "backscatter_median_db" in names
    d = {f.name: f.value for f in feats}
    assert d["backscatter_mean_db"] == 2.5


def test_backscatter_change_features():
    before = np.array([[0.0, 1.0], [2.0, 3.0]])
    after = before + 2.0
    engine = SARFeatureEngine()
    feats = engine.backscatter_features(after, source="test", before_db=before)
    names = {f.name for f in feats}
    assert "backscatter_change_db" in names
    d = {f.name: f.value for f in feats}
    assert abs(d["backscatter_change_db"] - 2.0) < 1e-9


def test_coherence_low_fraction():
    coh = np.array([[0.1, 0.9], [0.2, 0.8]])
    engine = SARFeatureEngine()
    feats = engine.coherence_features(coh, source="test", threshold=0.3)
    d = {f.name: f.value for f in feats}
    assert abs(d["low_coherence_fraction"] - 0.5) < 1e-9


def test_spatial_features_components():
    mask = np.zeros((5, 5), dtype=bool)
    mask[1:3, 1:3] = True
    engine = SARFeatureEngine()
    feats = engine.spatial_features(mask, source="test", pixel_area_m2=100.0)
    d = {f.name: f.value for f in feats}
    assert d["changed_area_px"] == 4.0
    assert d["connected_components"] == 1.0


def test_feature_to_dict():
    arr = np.array([1.0, 2.0, 3.0])
    engine = SARFeatureEngine()
    feats = engine.temporal_features(arr, source="test")
    dd = engine if False else None
    from app.features.engine import features_to_dict

    d = features_to_dict(feats)
    assert "temporal_mean" in d
    assert d["temporal_mean"] == 2.0


def test_nan_protection():
    arr = np.array([[np.nan, 1.0], [2.0, np.inf]])
    engine = SARFeatureEngine()
    feats = engine.backscatter_features(arr, source="test")
    d = {f.name: f.value for f in feats}
    # mean over finite values only
    assert d["backscatter_mean_db"] == 1.5
