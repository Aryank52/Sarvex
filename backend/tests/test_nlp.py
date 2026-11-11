"""Tests for NLP intent parser."""
from __future__ import annotations

from app.nlp.intent import parse_intent


def test_parse_deformation_intent():
    q = "Show persistent deformation around Dehradun between August and October"
    intent = parse_intent(q)
    d = intent.to_dict()
    assert d["analysis_type"] == "deformation"
    assert d["aoi"] == "Dehradun"
    assert d["date_start"].endswith("-08-01")
    assert d["date_end"].endswith("-10-28")
    assert d["constraints"].get("persistence") == "persistent"


def test_parse_flood_context():
    intent = parse_intent("Find flood changes near the river with infrastructure exposure")
    d = intent.to_dict()
    assert d["analysis_type"] == "change_detection"
    assert "infrastructure" in d["context_layers"] or "water" in d["context_layers"]
    assert d["output_type"] == "intelligence"


def test_parse_product_preference():
    intent = parse_intent("Run InSAR on GUNW products over the AOI")
    d = intent.to_dict()
    assert "GUNW" in d["product_preference"]
    assert d["frequency"] is None or d["frequency"] in ("L", "S")


def test_parse_frequency():
    intent = parse_intent("Analyze L-band backscatter change")
    d = intent.to_dict()
    assert d["frequency"] == "L"
    assert d["analysis_type"] == "backscatter"
