"""Pytest fixtures: isolated SQLite/object-store environment with demo seed."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="sarvex-tests-"))

# These must be set before app.config is imported anywhere.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}",
        "OBJECT_STORAGE_BACKEND": "local",
        "OBJECT_STORAGE_DIR": str(TEST_ROOT / "objects"),
        "DEMO_MODE": "on",
        "RUN_INLINE_WORKER": "false",
        "SEED_DEMO_ON_STARTUP": "false",
        "OFFLINE_MODE": "true",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "STRUCTURED_LOGS": "false",
        "LOG_LEVEL": "WARNING",
    }
)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.db.session import session_scope
    from app.main import app
    from app.services.demo import seed_demo

    with TestClient(app) as test_client:
        with session_scope() as session:
            summary = seed_demo(session, include_analyses=True)
        assert summary["products_ingested"] >= 8, summary
        assert len(summary["result_ids"]) >= 3, summary
        yield test_client


@pytest.fixture(scope="session")
def demo_aoi_id(client) -> str:
    return client.get("/api/v1/aois").json()["items"][0]["id"]


@pytest.fixture(scope="session")
def demo_result(client) -> dict:
    response = client.get("/api/v1/results")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    return next(item for item in items if item["is_demo"])


@pytest.fixture(scope="session")
def demo_event(client) -> dict:
    response = client.get("/api/v1/events")
    assert response.status_code == 200
    items = response.json()["items"]
    assert items
    return items[0]


@pytest.fixture(scope="session")
def demo_products(client) -> list[dict]:
    response = client.get("/api/v1/products", params={"limit": 100})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 8
    return items


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_environment():
    yield
    from app.db.session import get_engine, get_session_factory
    from app.storage.object_store import reset_object_store_cache

    try:
        get_session_factory.cache_clear()
        get_engine().dispose()
        get_engine.cache_clear()
    finally:
        reset_object_store_cache()
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
