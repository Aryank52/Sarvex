"""End-to-end processing tests for every scientific analysis mode."""
from __future__ import annotations

import pytest

DEMO_PROVIDER = "SARVEX Demo Fixtures"


@pytest.fixture(scope="module")
def product_groups(client) -> dict[str, list[dict]]:
    items = client.get("/api/v1/products", params={"limit": 300}).json()["items"]
    demo = [p for p in items if p["is_demo"] and p["provider"] == DEMO_PROVIDER]
    groups = {
        "gcov_l_vv": [
            p
            for p in demo
            if p["product_type"] == "GCOV"
            and p["normalized_metadata"].get("frequency_band") == "L"
            and p["normalized_metadata"].get("polarization") == "VV"
        ],
        "gcov_dual": [
            p
            for p in demo
            if p["product_type"] == "GCOV"
            and p["normalized_metadata"].get("polarization") == "VV+VH"
        ],
        "gunw": [p for p in demo if p["product_type"] == "GUNW"],
    }
    assert len(groups["gcov_l_vv"]) == 3
    assert len(groups["gcov_dual"]) == 2
    assert len(groups["gunw"]) == 1
    return groups


def _run_analysis(client, analysis_type: str, aoi_id: str, product_ids: list[str]) -> dict:
    response = client.post(
        "/api/v1/analyses",
        json={
            "analysis_type": analysis_type,
            "aoi_id": aoi_id,
            "product_ids": product_ids,
        },
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    execution = client.post(f"/api/v1/analyses/{job_id}/run")
    assert execution.status_code == 200, execution.text
    job = execution.json()
    assert job["status"] == "COMPLETED", job
    assert job["progress"] == pytest.approx(100.0)
    assert job["finished_at"] is not None

    results = client.get("/api/v1/results", params={"limit": 200}).json()["items"]
    matches = [r for r in results if r["job_id"] == job_id]
    assert len(matches) == 1, matches
    return matches[0]


def test_backscatter_analysis_end_to_end(client, demo_aoi_id, product_groups):
    product_ids = [p["id"] for p in product_groups["gcov_l_vv"]]
    result = _run_analysis(client, "backscatter", demo_aoi_id, product_ids)

    assert result["result_type"] == "backscatter_change"
    assert result["is_demo"] is True
    assert result["units"] == "dB"
    assert result["statistics"]["n_epochs"] == 3
    assert 0.0 <= result["statistics"]["change_fraction"] <= 1.0
    assert result["statistics"]["n_features"] >= 1

    detail = client.get(f"/api/v1/results/{result['id']}").json()
    assert detail["run"]["algorithm"] == "temporal_median_mad_v1"
    assert detail["run"]["units"] == "dB"
    assert detail["run"]["provenance"]["product_ids"]
    assert detail["events"], "backscatter result should persist detected events"
    assert all(event["taxonomy_stage"] in {"DETECTED", "CLASSIFIED"} for event in detail["events"])
    assert all(event["is_demo"] for event in detail["events"])

    features = client.get(f"/api/v1/results/{result['id']}/features").json()
    assert features
    for feature in features:
        assert feature["feature_type"] == "backscatter_change_segment"
        assert feature["unit"] == "dB"
        assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon"}
        assert feature["confidence"] is not None

    layers = client.get(f"/api/v1/results/{result['id']}/layers").json()
    names = {layer["name"] for layer in layers["layers"]}
    assert {"before", "after", "difference"} <= names
    for name in ("difference", "confidence"):
        png = client.get(f"/api/v1/results/{result['id']}/layers/{name}")
        assert png.status_code == 200
        assert png.headers["content-type"] == "image/png"
        assert png.content.startswith(b"\x89PNG")
        assert png.headers["x-sarvex-demo"] == "true"
    geotiff = client.get(
        f"/api/v1/results/{result['id']}/layers/difference", params={"format": "geotiff"}
    )
    assert geotiff.status_code == 200
    assert geotiff.headers["content-type"] == "image/tiff"
    assert geotiff.content[:2] in {b"II", b"MM"}

    series = client.get(f"/api/v1/results/{result['id']}/timeseries").json()
    assert series
    assert len(series[0]["points"]) == 3
    assert series[0]["unit"] == "dB"


def test_deformation_analysis_end_to_end(client, demo_aoi_id, product_groups):
    product_ids = [p["id"] for p in product_groups["gunw"]]
    result = _run_analysis(client, "deformation", demo_aoi_id, product_ids)

    assert result["result_type"] == "ground_deformation"
    assert result["units"] == "mm"
    assert result["is_demo"] is True
    assert result["statistics"]["wavelength_m"] == pytest.approx(0.2385)
    assert result["statistics"]["p95_displacement_mm"] is not None

    detail = client.get(f"/api/v1/results/{result['id']}").json()
    assert detail["run"]["algorithm"] == "gunw_los_displacement_mad_v1"
    assert detail["run"]["provenance"]["product_ids"]
    assert detail["statistics"]["limitations"]
    assert detail["events"]
    assert all(event["event_type"] == "GROUND_DEFORMATION" for event in detail["events"])
    assert any(event["magnitude_unit"] == "mm" for event in detail["events"])

    layers = client.get(f"/api/v1/results/{result['id']}/layers").json()
    names = {layer["name"] for layer in layers["layers"]}
    assert {"phase", "displacement", "coherence", "uncertainty"} <= names
    png = client.get(f"/api/v1/results/{result['id']}/layers/displacement")
    assert png.status_code == 200
    assert png.content.startswith(b"\x89PNG")


def test_polarimetric_analysis_end_to_end(client, demo_aoi_id, product_groups):
    product_ids = [p["id"] for p in product_groups["gcov_dual"]]
    result = _run_analysis(client, "polarimetric", demo_aoi_id, product_ids)

    assert result["result_type"] == "polarimetric_features"
    assert result["is_demo"] is True
    assert "VV/VH" in result["summary"] or "dual" in result["summary"].lower()
    features = client.get(f"/api/v1/results/{result['id']}/features").json()
    assert features
    assert all(f["feature_type"] == "polarimetric_change_segment" for f in features)

    layers = client.get(f"/api/v1/results/{result['id']}/layers").json()
    names = {layer["name"] for layer in layers["layers"]}
    assert {"vv", "vh", "ratio", "ratio_change"} <= names


def test_offset_tracking_analysis_end_to_end(client, demo_aoi_id, product_groups):
    products = product_groups["gcov_l_vv"]
    product_ids = [products[0]["id"], products[-1]["id"]]
    result = _run_analysis(client, "offsets", demo_aoi_id, product_ids)

    assert result["result_type"] == "offsets"
    assert result["units"] == "m"
    assert result["statistics"]["magnitude_px"] is not None
    assert result["statistics"]["shift_x_px"] is not None
    assert result["statistics"]["pixel_spacing_x_m"] > 0
    layers = client.get(f"/api/v1/results/{result['id']}/layers").json()
    names = {layer["name"] for layer in layers["layers"]}
    assert {"before", "after"} <= names


def test_timeseries_analysis_end_to_end(client, demo_aoi_id, product_groups):
    product_ids = [p["id"] for p in product_groups["gcov_l_vv"]]
    result = _run_analysis(client, "timeseries", demo_aoi_id, product_ids)

    assert result["result_type"] == "timeseries"
    assert result["statistics"]["n_epochs"] == 3
    assert result["statistics"]["temporal_analysis"].startswith("Theil-Sen")
    series = client.get(f"/api/v1/results/{result['id']}/timeseries").json()
    assert series
    assert len(series[0]["points"]) == 3
    assert "slope" in series[0]["trend"]


def test_incompatible_product_type_is_rejected(client, demo_aoi_id, product_groups):
    gcov = product_groups["gcov_l_vv"][0]["id"]
    response = client.post(
        "/api/v1/analyses",
        json={
            "analysis_type": "deformation",
            "aoi_id": demo_aoi_id,
            "product_ids": [gcov],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"


def test_timeseries_requires_three_products(client, demo_aoi_id, product_groups):
    product_ids = [p["id"] for p in product_groups["gcov_l_vv"][:2]]
    response = client.post(
        "/api/v1/analyses",
        json={
            "analysis_type": "timeseries",
            "aoi_id": demo_aoi_id,
            "product_ids": product_ids,
        },
    )
    assert response.status_code == 422, response.text
    assert "at least 3" in response.json()["message"]


def test_job_logs_record_state_transitions(client, demo_aoi_id, product_groups):
    product_ids = [p["id"] for p in product_groups["gcov_l_vv"][:2]]
    response = client.post(
        "/api/v1/analyses",
        json={
            "analysis_type": "backscatter",
            "aoi_id": demo_aoi_id,
            "product_ids": product_ids,
        },
    )
    job_id = response.json()["job_id"]
    client.post(f"/api/v1/analyses/{job_id}/run")
    logs = client.get(f"/api/v1/analyses/{job_id}/logs").json()
    messages = " ".join(entry.get("message", "") for entry in logs["logs"])
    assert "Validating" in messages
    assert "Running" in messages
    assert "Completed" in messages
    assert logs["progress"] == pytest.approx(100.0)
    assert logs["current_stage"] == "COMPLETED"
