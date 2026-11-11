"""Fixture integrity, connector behaviour and ingestion guarantees."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio

from app.config import BACKEND_DIR
from app.connectors.base import SearchQuery
from app.connectors.local import LocalFileConnector
from app.connectors.registry import get_connector_registry
from app.core.errors import NotFoundError, ValidationError
from app.fixtures.demo_raster import (
    AOI_BOUNDS,
    DEMO_SCENES,
    _write_geotiff,
    ensure_demo_fixtures,
)
from app.products.base import infer_polarizations, infer_product_type
from app.products.registry import adapter_catalog, get_adapter


def test_demo_fixtures_are_valid_georeferenced_rasters():
    fixtures = ensure_demo_fixtures()
    assert set(fixtures) == set(DEMO_SCENES)
    for key, path in fixtures.items():
        assert path.exists()
        with rasterio.open(path) as dataset:
            assert dataset.crs is not None
            assert dataset.crs.to_epsg() == 4326
            assert dataset.width == dataset.height == 180
            tags = dataset.tags()
            assert tags.get("SARVEX_IS_DEMO") == "TRUE"
            assert tags.get("SARVEX_SCENE_ID") == key
            assert tags.get("SARVEX_MISSION") == "SARVEX-DEMO"
            data = dataset.read(1)
            assert np.isfinite(data).any()
            # Bounds must remain inside the declared Assam AOI envelope.
            assert dataset.bounds.left >= AOI_BOUNDS[0] - 1e-6
            assert dataset.bounds.right <= AOI_BOUNDS[2] + 1e-6
            assert dataset.bounds.bottom >= AOI_BOUNDS[1] - 1e-6
            assert dataset.bounds.top <= AOI_BOUNDS[3] + 1e-6


def test_demo_connector_is_labelled_and_filterable():
    connector = get_connector_registry().demo
    items = connector.search(SearchQuery(bbox=list(AOI_BOUNDS), max_results=100))
    assert len(items) == len(DEMO_SCENES) == 8
    assert all(item.is_demo for item in items)
    assert all("synthetic" in (item.citation or "").lower() for item in items)
    assert {item.product_type for item in items} == {"GCOV", "GUNW"}

    gunw = connector.search(
        SearchQuery(bbox=list(AOI_BOUNDS), product_types=["GUNW"], max_results=100)
    )
    assert len(gunw) == 1
    assert gunw[0].product_type == "GUNW"

    outside = connector.search(SearchQuery(bbox=[0.0, 0.0, 1.0, 1.0], max_results=100))
    assert outside == []
    assert connector.health_check().status == "ok"

    with pytest.raises(NotFoundError):
        connector.get_metadata("no-such-demo-scene")


def test_raster_adapter_extracts_only_declared_metadata():
    fixtures = ensure_demo_fixtures()
    path = fixtures["gcov_l_before"]
    adapter = get_adapter(path, "GCOV")
    report = adapter.validate(path)
    assert report.valid and not report.errors

    meta = adapter.extract(path, provider="SARVEX Demo Fixtures", product_type="GCOV")
    assert meta.product_type == "GCOV"
    assert meta.frequency_band == "L"
    assert meta.frequency_hz == pytest.approx(1.257e9)
    assert meta.wavelength_m == pytest.approx(0.2385)
    assert meta.polarization == "VV"
    assert meta.units == "dB"
    assert meta.acquisition_start.startswith("2026-06-01")
    assert meta.bbox == pytest.approx(list(AOI_BOUNDS))
    assert meta.geometry is not None
    assert meta.checksum


def test_product_adapter_registry_covers_all_nisar_types():
    catalog = adapter_catalog()
    covered = {entry["product_type"] for entry in catalog}
    assert covered == {"RSLC", "GSLC", "GCOV", "RIFG", "RUNW", "GUNW", "ROFF", "GOFF"}
    assert infer_product_type("NISAR_L2_GUNW_BETA_V1.h5") == "GUNW"
    assert infer_product_type("anything.h5", "GSLC") == "GSLC"
    assert infer_polarizations([], {"SARVEX_POLARIZATION": "VV+VH"}) == "VV+VH"
    assert infer_polarizations(["sigma0_VV_dB", "sigma0_VH_dB"], {}) == "VV+VH"


def test_invalid_raster_is_rejected_before_ingestion(tmp_path):
    bad = tmp_path / "broken.tif"
    bad.write_bytes(b"this is not a geotiff")
    adapter = get_adapter(bad)
    report = adapter.validate(bad)
    assert not report.valid
    assert report.errors
    with pytest.raises(ValidationError):
        report.raise_if_invalid()


def test_duplicate_demo_ingestion_is_rejected(client, demo_products):
    seeded = next(product for product in demo_products if product["is_demo"])
    response = client.post(
        "/api/v1/catalog/ingest",
        json={"connector": "demo", "product_ref": seeded["product_id"]},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "conflict"


def test_upload_ingests_new_product_and_rejects_duplicate(client, tmp_path):
    tags = dict(DEMO_SCENES["gcov_l_before"]["tags"])
    tags["SARVEX_SCENE_ID"] = "upload_integration_test"
    data = np.full((180, 180), -13.25, dtype="float32")
    path = _write_geotiff(
        tmp_path / "upload_integration_test.tif",
        [data],
        descriptions=["sigma0_VV_dB"],
        tags=tags,
    )
    target = BACKEND_DIR / "data" / "uploads" / path.name
    try:
        with path.open("rb") as fh:
            response = client.post(
                "/api/v1/catalog/upload",
                files={"file": (path.name, fh, "image/tiff")},
                data={"product_type": "GCOV"},
            )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["product_type"] == "GCOV"
        # The file carries demo tags; provenance must not hide that.
        assert body["is_demo"] is True
        assert body["validation_status"].startswith("VALID")

        product = client.get(f"/api/v1/products/{body['product_db_id']}").json()
        assert product["provider"] == "Local Uploads"
        assert product["normalized_metadata"]["frequency_band"] == "L"
        assert product["manifest"]["checksum"]

        with path.open("rb") as fh:
            duplicate = client.post(
                "/api/v1/catalog/upload",
                files={"file": (path.name, fh, "image/tiff")},
                data={"product_type": "GCOV"},
            )
        assert duplicate.status_code == 409, duplicate.text
    finally:
        target.unlink(missing_ok=True)


def test_local_connector_rejects_path_traversal(tmp_path):
    connector = LocalFileConnector([tmp_path])
    with pytest.raises(ValidationError):
        connector.resolve_path("../escape.tif")
    with pytest.raises(NotFoundError):
        connector.get_metadata("../escape.tif")
