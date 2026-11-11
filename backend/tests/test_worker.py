"""Background worker: atomic claims, execution and stale-claim recovery."""
from __future__ import annotations

from datetime import timedelta

from app.core.provenance import utcnow
from app.db.models import ProcessingJob
from app.db.session import session_scope
from app.processing.engine import execute_job
from app.worker import claim_jobs, process_once, recover_stale_jobs


def _queued_job(client, demo_aoi_id: str, product_ids: list[str]) -> str:
    response = client.post(
        "/api/v1/analyses",
        json={
            "analysis_type": "backscatter",
            "aoi_id": demo_aoi_id,
            "product_ids": product_ids,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_worker_processes_queued_job(client, demo_aoi_id, demo_products):
    gcov = [p["id"] for p in demo_products if p["product_type"] == "GCOV"][:2]
    job_id = _queued_job(client, demo_aoi_id, gcov)
    assert client.get(f"/api/v1/analyses/{job_id}").json()["status"] == "QUEUED"

    executed = process_once(max_jobs=5)
    assert executed >= 1

    job = client.get(f"/api/v1/analyses/{job_id}").json()
    assert job["status"] == "COMPLETED", job
    assert job["current_stage"] == "COMPLETED"
    assert job["progress"] == 100.0
    results = client.get("/api/v1/results", params={"limit": 500}).json()["items"]
    assert any(result["job_id"] == job_id for result in results)


def test_claims_are_atomic(client, demo_aoi_id, demo_products):
    gcov = [p["id"] for p in demo_products if p["product_type"] == "GCOV"][:2]
    first = _queued_job(client, demo_aoi_id, gcov)
    second = _queued_job(client, demo_aoi_id, gcov)

    with session_scope() as session:
        claimed = claim_jobs(session, 1)
    assert len(claimed) == 1
    claimed_id = claimed[0]
    assert claimed_id in {first, second}

    with session_scope() as session:
        claimed_again = claim_jobs(session, 10)
    assert claimed_id not in claimed_again
    assert set(claimed_again) == ({first, second} - {claimed_id})

    assert execute_job(claimed_id, claimed=True) == "COMPLETED"

    second_id = next(iter(set(claimed_again)))
    # Clean up the second claimed job without executing it.
    with session_scope() as session:
        job = session.get(ProcessingJob, second_id)
        job.status = "CANCELLED"
        job.current_stage = "CANCELLED"
        job.progress = 100.0
        job.finished_at = utcnow()


def test_stale_claim_is_requeued(client, demo_aoi_id):
    with session_scope() as session:
        job = ProcessingJob(
            analysis_type="backscatter",
            status="PROCESSING",
            aoi_id=demo_aoi_id,
            product_ids=[],
            parameters={},
            progress=42.0,
            current_stage="PROCESSING",
            correlation_id="stale-worker-test",
            logs=[],
            queued_at=utcnow() - timedelta(hours=2),
            started_at=utcnow() - timedelta(hours=2),
            is_demo=True,
        )
        session.add(job)
        session.flush()
        job_id = job.id

    with session_scope() as session:
        requeued = recover_stale_jobs(session, stale_minutes=5)
    assert job_id in requeued

    recovered = client.get(f"/api/v1/analyses/{job_id}").json()
    assert recovered["status"] == "QUEUED"
    assert recovered["progress"] == 0.0
    assert recovered["started_at"] is None
    assert recovered["error"] is None
    assert any(
        "Stale execution recovered" in entry.get("message", "")
        for entry in recovered["logs"]
    )

    # Do not leave an unrunnable job queued for other tests.
    cancelled = client.post(f"/api/v1/analyses/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
