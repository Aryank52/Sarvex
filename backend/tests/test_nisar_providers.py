"""Tests for NISAR provider abstraction."""
from __future__ import annotations

from app.connectors.nisar import get_adapter, get_nisar_providers, ADAPTERS


def test_adapters_cover_all_products():
    for pt in ["RSLC", "GSLC", "GCOV", "RIFG", "RUNW", "GUNW", "ROFF", "GOFF"]:
        assert pt in ADAPTERS
        adapter = get_adapter(pt)
        meta = adapter.normalize({"product_id": f"P-{pt}", "product_type": pt, "provider": "test"})
        assert meta.product_id == f"P-{pt}"


def test_demo_provider_health():
    providers = get_nisar_providers()
    assert "demo" in providers
    h = providers["demo"].health_check()
    assert h is not None


def test_adapter_normalizes_metadata():
    adapter = get_adapter("GUNW")
    meta = adapter.normalize(
        {
            "product_id": "G1",
            "provider": "ASF",
            "frequency_band": "L",
            "polarization": "VV+VH",
            "acquisition_start": "2026-08-10T00:00:00",
            "bbox": [91.5, 26.0, 92.0, 26.4],
            "spatial_resolution_m": 10.0,
            "orbit": 12,
            "pass_direction": "ascending",
            "crs": "EPSG:4326",
        }
    )
    assert meta.frequency == "L"
    assert meta.polarization == "VV+VH"
    assert meta.orbit == 12
    assert meta.bbox == [91.5, 26.0, 92.0, 26.4]
    assert meta.to_dict()["product_id"] == "G1"
