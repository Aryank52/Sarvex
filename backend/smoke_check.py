"""End-to-end smoke check used during development (not part of pytest)."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
DATA = BACKEND / "data"
DB = DATA / "smoke.db"
OBJECTS = DATA / "smoke_objects"
for path in (DB,):
    path.unlink(missing_ok=True)
shutil.rmtree(OBJECTS, ignore_errors=True)

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{DB.as_posix()}",
        "OBJECT_STORAGE_DIR": str(OBJECTS),
        "OBJECT_STORAGE_BACKEND": "local",
        "DEMO_MODE": "on",
        "RUN_INLINE_WORKER": "false",
        "SEED_DEMO_ON_STARTUP": "true",
        "OFFLINE_MODE": "true",
        "STRUCTURED_LOGS": "false",
        "LOG_LEVEL": "WARNING",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def show(label: str, response) -> None:  # type: ignore[no-untyped-def]
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else f"<{len(response.content)} bytes>"
    preview = json.dumps(body, default=str)[:600] if not isinstance(body, str) else body[:300]
    print(f"{label}: {response.status_code} {preview}")


with TestClient(app) as client:
    health = client.get("/api/v1/health")
    show("health", health)
    assert health.status_code == 200, health.text

    products = client.get("/api/v1/products")
    show("products", products)
    assert products.status_code == 200
    assert products.json()["total"] >= 8, products.text

    results = client.get("/api/v1/results")
    show("results", results)
    assert results.status_code == 200
    assert results.json()["total"] >= 3, results.text
    result_ids = [item["id"] for item in results.json()["items"]]

    events = client.get("/api/v1/events")
    show("events", events)
    assert events.status_code == 200

    geojson = client.get("/api/v1/events/geojson")
    show("events geojson", geojson)
    assert geojson.status_code == 200

    layers = client.get(f"/api/v1/results/{result_ids[0]}/layers")
    show("layers", layers)
    assert layers.status_code == 200, layers.text
    layer_names = [layer["name"] for layer in layers.json()["layers"]]
    if layer_names:
        png = client.get(f"/api/v1/results/{result_ids[0]}/layers/{layer_names[0]}")
        print("layer png:", png.status_code, png.headers.get("content-type"), len(png.content))
        assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"

    search = client.post(
        "/api/v1/knowledge/search",
        json={"query": "interferometric phase to displacement", "top_k": 4},
    )
    show("rag search", search)
    assert search.status_code == 200 and search.json()["citations"], search.text

    copilot = client.post(
        "/api/v1/copilot/ask",
        json={
            "question": "What did the analysis measure and what are its limitations?",
            "result_id": result_ids[0],
        },
    )
    show("copilot", copilot)
    assert copilot.status_code == 200, copilot.text
    assert copilot.json()["citations_validated"] is True, copilot.text

    report = client.post(
        "/api/v1/reports", json={"result_id": result_ids[0], "format": "markdown"}
    )
    show("report", report)
    assert report.status_code == 201, report.text
    download = client.get(f"/api/v1/reports/{report.json()['id']}/download")
    print("report download:", download.status_code, len(download.content))
    assert download.status_code == 200

    aoi = client.get("/api/v1/aois").json()["items"][0]
    backscatter_products = [
        p["id"]
        for p in client.get("/api/v1/products", params={"product_type": "GCOV"}).json()["items"]
        if p["is_demo"]
    ]
    job = client.post(
        "/api/v1/analyses",
        json={
            "aoi_id": aoi["id"],
            "product_ids": backscatter_products[:3],
            "analysis_type": "change_detection",
            "parameters": {"z_threshold": 3.0},
        },
    )
    show("create job", job)
    assert job.status_code == 202, job.text
    run = client.post(f"/api/v1/analyses/{job.json()['job_id']}/run")
    show("run job", run)
    assert run.status_code == 200 and run.json()["status"] == "COMPLETED", run.text

    models = client.get("/api/v1/models")
    show("models", models)
    assert models.status_code == 200

    stats = client.get("/api/v1/events/stats")
    show("event stats", stats)
    assert stats.status_code == 200

print("SMOKE OK")
