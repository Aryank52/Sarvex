"""Tests for new intelligence endpoints."""
from __future__ import annotations

import pytest


def test_nlp_parse_endpoint(client):
    resp = client.post("/api/v1/nlp/parse", json={"query": "Show deformation around Dehradun between August and October"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"]["analysis_type"] == "deformation"
    assert body["intent"]["aoi"] == "Dehradun"


def test_hfce_status_endpoint(client):
    resp = client.get("/api/v1/models/hfce/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # model may or may not be trained depending on artifacts; both are valid
    assert "available" in body


def test_hfce_predict_endpoint(client):
    # May be unavailable in CI without artifact; accept 200 or 503
    resp = client.post("/api/v1/models/hfce/predict", json={"features": {"backscatter_change_median_db": 2.0}})
    assert resp.status_code in (200, 503), resp.text
    if resp.status_code == 200:
        body = resp.json()
        assert "prediction" in body
        assert body["prediction"]["event_type"] is not None
