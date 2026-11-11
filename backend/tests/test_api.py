"""API contract tests: health, catalog, context, events workflow and reports."""
from __future__ import annotations

import uuid

from app.db.models import ChangeEvent
from app.db.session import session_scope

ASSAM = {
    "type": "Polygon",
    "coordinates": [
        [[91.56, 26.06], [91.62, 26.06], [91.62, 26.12], [91.56, 26.12], [91.56, 26.06]]
    ],
}

DEMO_PROVIDER = "SARVEX Demo Fixtures"


def _create_event(*, is_demo: bool = False, status: str = "UNREVIEWED") -> str:
    """Create a non-seeded event so demo records remain untouched."""
    jitter = (uuid.uuid4().int % 40) / 10000.0
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [91.56 + jitter, 26.06 + jitter],
                [91.62 + jitter, 26.06 + jitter],
                [91.62 + jitter, 26.12 + jitter],
                [91.56 + jitter, 26.12 + jitter],
                [91.56 + jitter, 26.06 + jitter],
            ]
        ],
    }
    with session_scope() as session:
        event = ChangeEvent(
            event_type="SURFACE_DISTURBANCE",
            taxonomy_stage="DETECTED",
            classification_method="unit_test_detector",
            classification_confidence=0.55,
            geometry=geometry,
            area_m2=1_000_000.0,
            magnitude=1.4,
            magnitude_unit="dB",
            confidence=0.55,
            uncertainty=0.3,
            severity=0.45,
            priority=3,
            status=status,
            summary="Non-demo event created by the test suite for review workflow tests.",
            properties={"test": True},
            is_demo=is_demo,
        )
        session.add(event)
        session.flush()
        return event.id


def test_health_capabilities_and_correlation(client):
    response = client.get("/api/v1/health", headers={"X-Correlation-ID": "test-correlation"})
    assert response.status_code == 200
    assert response.headers["x-correlation-id"] == "test-correlation"
    health = response.json()
    assert health["status"] == "ok"
    assert health["database"]["healthy"] is True
    assert health["database"]["backend"] == "sqlite"
    assert health["demo_mode"]["effective_data_mode"] == "DEMO"
    assert "synthetic fixtures" in health["demo_mode"]["banner"]
    assert health["demo_mode"]["demo_products"] >= 8
    assert health["rag"]["documents"] >= 1

    capabilities = client.get("/api/v1/capabilities").json()
    assert {item["type"] for item in capabilities["analysis_types"]} == {
        "backscatter",
        "change_detection",
        "deformation",
        "polarimetric",
        "offsets",
        "timeseries",
    }
    assert capabilities["product_types"] == [
        "RSLC",
        "GSLC",
        "GCOV",
        "RIFG",
        "RUNW",
        "GUNW",
        "ROFF",
        "GOFF",
    ]
    assert "demo" in capabilities["connectors"]
    assert capabilities["models"]["embedding"]["dimension"] == 384
    assert capabilities["models"]["storage_capacity"] == 1536
    assert capabilities["storage"]["database"].startswith("sqlite")

    connectors = client.get("/api/v1/health/connectors").json()
    assert any(item["connector"] == "SARVEX Demo Fixtures" for item in connectors["connectors"])
    demo_health = next(
        item for item in connectors["connectors"] if item["connector"] == "SARVEX Demo Fixtures"
    )
    assert demo_health["status"] == "ok"
    assert demo_health["capabilities"]["synthetic"] is True


def test_catalog_listing_manifest_and_search(client):
    datasets = client.get("/api/v1/datasets", params={"limit": 100}).json()
    assert datasets["total"] >= 8
    dataset = next(item for item in datasets["items"] if item["is_demo"])
    manifest = client.get(f"/api/v1/datasets/{dataset['dataset_id']}/manifest").json()
    assert manifest["dataset_id"] == dataset["dataset_id"]
    assert manifest["attribution"]
    assert manifest["is_demo"] is True
    assert manifest["checksum"]

    observations = client.get(
        "/api/v1/observations", params={"bbox": "91.5,26.0,92.0,26.4", "limit": 100}
    ).json()
    assert observations["total"] >= 8
    gunw = client.get("/api/v1/observations", params={"product_type": "GUNW"}).json()
    assert gunw["total"] == 1
    assert gunw["items"][0]["frequency_band"] == "L"

    search = client.post(
        "/api/v1/catalog/search",
        json={
            "connector": "demo",
            "bbox": [91.55, 26.05, 91.95, 26.32],
            "product_types": ["GCOV"],
            "max_results": 100,
        },
    )
    assert search.status_code == 200, search.text
    body = search.json()
    assert body["connector"] == DEMO_PROVIDER
    assert body["demo_fallback"] is False
    assert body["total"] == 7
    assert all(item["is_demo"] for item in body["items"])
    assert body["data_mode"] == "DEMO"
    assert all(item["product_type"] == "GCOV" for item in body["items"])

    adapters = client.get("/api/v1/catalog/adapters").json()
    assert len(adapters["adapters"]) == 8


def test_aoi_crud_and_geojson(client, demo_aoi_id):
    created = client.post(
        "/api/v1/aois",
        json={"name": "Test AOI", "description": "contract test", "geometry": ASSAM},
    )
    assert created.status_code == 201, created.text
    aoi = created.json()
    assert aoi["name"] == "Test AOI"
    assert aoi["bbox"] == [91.56, 26.06, 91.62, 26.12]
    assert aoi["area_m2"] > 0

    fetched = client.get(f"/api/v1/aois/{aoi['id']}").json()
    assert fetched["id"] == aoi["id"]
    geojson = client.get(f"/api/v1/aois/{aoi['id']}/geojson").json()
    assert geojson["type"] == "Feature"
    assert geojson["geometry"]["type"] == "Polygon"
    assert geojson["properties"]["name"] == "Test AOI"

    analyses = client.get(f"/api/v1/aois/{demo_aoi_id}/analyses").json()
    assert analyses["aoi_id"] == demo_aoi_id
    assert analyses["analyses"], "seeded demo analyses must be discoverable from the AOI"

    assert client.get("/api/v1/aois/does-not-exist").status_code == 404


def test_context_layers_assets_and_exposures(client):
    layers = client.get("/api/v1/context/layers", params={"limit": 100}).json()
    assert layers["total"] > 0
    for layer in layers["items"]:
        assert layer["provider"]
        assert layer["license"]
        assert layer["source"]
        assert layer["is_demo"] is True

    assets = client.get("/api/v1/context/assets", params={"limit": 100}).json()
    assert assets["total"] > 0
    assert all(asset["is_demo"] for asset in assets["items"])

    exposures = client.get("/api/v1/context/exposures", params={"limit": 100}).json()
    for exposure in exposures:
        assert 0.0 <= exposure["exposure_score"] <= 1.0
        assert exposure["rationale"]


def test_events_geojson_and_stats(client):
    listing = client.get("/api/v1/events", params={"limit": 1000}).json()
    assert listing["total"] >= 1
    assert any(event["is_demo"] for event in listing["items"])

    geojson = client.get("/api/v1/events/geojson", params={"limit": 2000}).json()
    assert geojson["type"] == "FeatureCollection"
    assert geojson["metadata"]["count"] == len(geojson["features"])
    assert geojson["metadata"]["demo_mode"] is True
    assert "not NASA/ISRO" in geojson["metadata"]["notice"]
    for feature in geojson["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] in {"Polygon", "MultiPolygon", "Point"}
        assert feature["properties"]["taxonomy_stage"] in {
            "DETECTED",
            "CLASSIFIED",
            "HYPOTHESIZED",
            "CONFIRMED",
        }

    stats = client.get("/api/v1/events/stats").json()
    assert stats["total"] == listing["total"]
    assert stats["demo"] >= 1
    assert stats["by_type"]
    assert sum(stats["by_type"].values()) == stats["total"]

    detail_event = listing["items"][0]
    detail = client.get(f"/api/v1/events/{detail_event['id']}").json()
    assert detail["id"] == detail_event["id"]
    assert "evidence_ids" in detail
    assert "context_ids" in detail


def test_event_review_transitions_and_confirmation_gates(client, demo_event):
    # Demo events can never be confirmed: synthetic fixtures are not real events.
    demo_confirm = client.post(
        f"/api/v1/events/{demo_event['id']}/confirm",
        json={
            "evidence_title": "Official flood report",
            "source_type": "OFFICIAL_REPORT",
            "url": "https://example.gov/report",
            "rationale": "Independent official report documenting the observed event.",
        },
    )
    assert demo_confirm.status_code == 422, demo_confirm.text
    assert demo_confirm.json()["code"] == "validation_error"

    event_id = _create_event()

    invalid = client.patch(
        f"/api/v1/events/{event_id}/status", json={"status": "CORROBORATED"}
    )
    assert invalid.status_code == 409, invalid.text

    review = client.patch(
        f"/api/v1/events/{event_id}/status",
        json={"status": "UNDER_REVIEW", "rationale": "Beginning review"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "UNDER_REVIEW"
    assert review.json()["taxonomy_stage"] == "DETECTED"

    missing_url = client.patch(
        f"/api/v1/events/{event_id}/status", json={"status": "CORROBORATED"}
    )
    assert missing_url.status_code == 422, missing_url.text

    corroborated = client.patch(
        f"/api/v1/events/{event_id}/status",
        json={
            "status": "CORROBORATED",
            "external_evidence_url": "https://example.gov/observations/123",
            "rationale": "External observation record matches the detection footprint.",
        },
    )
    assert corroborated.status_code == 200, corroborated.text
    assert corroborated.json()["taxonomy_stage"] == "DETECTED"

    no_reference = client.post(
        f"/api/v1/events/{event_id}/confirm",
        json={
            "evidence_title": "Official report",
            "source_type": "OFFICIAL_REPORT",
            "rationale": "Independent evidence documenting the event in this footprint.",
        },
    )
    assert no_reference.status_code == 422, no_reference.text

    synthetic = client.post(
        f"/api/v1/events/{event_id}/confirm",
        json={
            "evidence_title": "Official report",
            "source_type": "OFFICIAL_REPORT",
            "url": "https://example.gov/report",
            "rationale": "Independent evidence documenting the event in this footprint.",
            "is_demo_evidence": True,
        },
    )
    assert synthetic.status_code == 422, synthetic.text

    confirmed = client.post(
        f"/api/v1/events/{event_id}/confirm",
        json={
            "evidence_title": "District flood bulletin 2026-08-11",
            "source_type": "OFFICIAL_REPORT",
            "url": "https://example.gov/bulletins/2026-08-11",
            "publisher": "Example District Authority",
            "rationale": (
                "The official bulletin independently documents surface water at the "
                "same location and date as the SAR-detected change."
            ),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "CORROBORATED"
    assert body["taxonomy_stage"] == "CONFIRMED"
    assert body["evidence_id"]

    evidence = client.get(f"/api/v1/events/{event_id}/evidence").json()
    assert any(item["id"] == body["evidence_id"] for item in evidence)
    assert any(item["url"] == "https://example.gov/bulletins/2026-08-11" for item in evidence)

    detail = client.get(f"/api/v1/events/{event_id}").json()
    assert detail["taxonomy_stage"] == "CONFIRMED"
    assert body["evidence_id"] in detail["evidence_ids"]


def test_evidence_creation_requires_a_reference(client):
    empty = client.post(
        "/api/v1/evidence",
        json={"source_type": "OFFICIAL_REPORT", "title": "No reference evidence"},
    )
    assert empty.status_code == 422, empty.text

    event_id = _create_event()
    created = client.post(
        "/api/v1/evidence",
        json={
            "source_type": "PEER_REVIEWED_STUDY",
            "title": "Independent SAR validation study",
            "citation": "Doe et al. (2026), Journal of SAR Validation, 12(3), 45-67.",
            "snippet": "Independent analysis reports a change consistent with the detected footprint.",
            "confidence": 0.8,
            "event_id": event_id,
        },
    )
    assert created.status_code == 201, created.text
    evidence = created.json()
    assert evidence["url"] is None
    assert evidence["is_demo"] is False

    linked = client.get(f"/api/v1/events/{event_id}/evidence").json()
    assert any(item["id"] == evidence["id"] for item in linked)

    listing = client.get("/api/v1/evidence", params={"source_type": "PEER_REVIEWED_STUDY"}).json()
    assert listing["total"] >= 1
    assert all(item["source_type"] == "PEER_REVIEWED_STUDY" for item in listing["items"])


def test_models_endpoints(client):
    models = client.get("/api/v1/models").json()
    categories = {model["category"] for model in models["models"]}
    assert {"llm", "embedding", "reranker", "change_detection"} <= categories
    assert models["summary"]["embedding"]["dimension"] == 384
    assert models["summary"]["storage_capacity"] == 1536

    health = client.get("/api/v1/health/models").json()
    assert health["models"]
    assert all(model["status"] for model in health["models"])

    reloaded = client.post("/api/v1/models/reload")
    assert reloaded.status_code == 200
    assert reloaded.json()["reloaded"] is True

    runs = client.get("/api/v1/models/runs").json()
    assert "runs" in runs


def test_report_generation_and_download(client, demo_result, demo_event):
    result_report = client.post("/api/v1/reports", json={"result_id": demo_result["id"]})
    assert result_report.status_code == 201, result_report.text
    report = result_report.json()
    assert "DEMO MODE" in report["content"]
    assert "Provenance record" in report["content"]
    assert "Interpretation and limitations" in report["content"]
    assert report["provenance"]["demo"] is True
    assert report["provenance"]["algorithm"]

    download = client.get(f"/api/v1/reports/{report['id']}/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/markdown")
    assert b"DEMO MODE" in download.content

    event_report = client.post("/api/v1/reports", json={"event_id": demo_event["id"]})
    assert event_report.status_code == 201, event_report.text
    event_body = event_report.json()
    assert "Change Event Report" in event_body["title"]
    assert "DEMO MODE" in event_body["content"]

    html = client.post(
        "/api/v1/reports",
        json={"result_id": demo_result["id"], "format": "html", "title": "HTML test report"},
    )
    assert html.status_code == 201, html.text
    assert html.json()["format"] == "html"
    assert "<html" in html.json()["content"].lower()

    listing = client.get("/api/v1/reports", params={"limit": 100}).json()
    assert listing["total"] >= 3
    assert any(item["id"] == report["id"] for item in listing["items"])

    missing = client.post("/api/v1/reports", json={})
    assert missing.status_code == 422, missing.text

    assert client.get("/api/v1/reports/does-not-exist").status_code == 404
    assert client.get("/api/v1/results/does-not-exist").status_code == 404
