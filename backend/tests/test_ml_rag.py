"""Model registry, embedding storage and hybrid RAG tests."""
from __future__ import annotations

import uuid

import pytest

from app.core.errors import ValidationError
from app.ml.registry import EMBEDDING_STORAGE_CAPACITY, get_model_registry
from app.rag.ingest import pad_embedding

SENTINEL = "zorbital"


def test_model_registry_is_configuration_driven():
    registry = get_model_registry()
    summary = registry.capability_summary()
    assert summary["embedding"]["dimension"] == 384
    assert summary["storage_capacity"] == EMBEDDING_STORAGE_CAPACITY == 1536
    assert summary["llm"]["name"] == "grounded-extractive-composer"
    assert summary["reranker"]["name"] == "lexical-overlap-reranker"

    provider = registry.embedding_provider()
    assert provider.dimension == 384
    first = provider.embed_query("radar backscatter coherence")
    second = provider.embed_query("radar backscatter coherence")
    other = provider.embed_query("unrelated volcanic ash plume")
    assert len(first) == 384
    assert first == second
    assert first != other
    assert provider.health()["semantic"] is False

    health = registry.health()
    assert health
    categories = {entry["category"] for entry in health}
    assert {"llm", "embedding", "reranker", "change_detection"} <= categories
    assert all(entry["status"] for entry in health)
    with pytest.raises(Exception):
        registry.get_spec("embedding", "not-a-configured-model")


def test_embedding_padding_never_truncates():
    vector = [0.5, -0.25, 0.125]
    padded = pad_embedding(vector)
    assert len(padded) == EMBEDDING_STORAGE_CAPACITY
    assert padded[:3] == pytest.approx(vector)
    assert all(value == 0.0 for value in padded[3:])

    exact = pad_embedding([0.1] * EMBEDDING_STORAGE_CAPACITY)
    assert len(exact) == EMBEDDING_STORAGE_CAPACITY

    with pytest.raises(ValidationError):
        pad_embedding([0.1] * (EMBEDDING_STORAGE_CAPACITY + 1))


def test_knowledge_ingestion_search_and_provenance(client):
    marker = uuid.uuid4().hex
    title = f"SARVEX RAG contract document {marker}"
    text = (
        f"# {title}\n\n"
        "## Zorbital coherence ledger\n\n"
        f"The {SENTINEL} coherence ledger records calibration checks for dual-pol "
        f"backscatter products. Document marker {marker} supports citation tests. "
        "Values are instrument metadata and do not assert surface change.\n\n"
        "## Retrieval note\n\n"
        "Hybrid retrieval combines lexical overlap with vector similarity and keeps "
        "the source priority attached to every passage.\n"
    )

    before = client.get("/api/v1/knowledge/stats").json()
    response = client.post(
        "/api/v1/knowledge/ingest",
        json={
            "text": text,
            "title": title,
            "url": "https://example.org/sarvex-rag-contract",
            "author": "SARVEX Test Suite",
            "publisher": "SARVEX",
            "document_type": "SAR_METHOD",
            "scientific_topic": "calibration",
            "source_priority": 2,
        },
    )
    assert response.status_code == 201, response.text
    ingested = response.json()
    assert ingested["chunks"] >= 1
    assert ingested["embeddings"] == ingested["chunks"]
    assert ingested["is_demo"] is False

    after = client.get("/api/v1/knowledge/stats").json()
    assert after["documents"] == before["documents"] + 1
    assert after["chunks"] == before["chunks"] + ingested["chunks"]

    search = client.post(
        "/api/v1/knowledge/search",
        json={"query": f"{SENTINEL} coherence ledger {marker}", "top_k": 5},
    )
    assert search.status_code == 200, search.text
    found = search.json()
    assert found["citations"]
    top = found["citations"][0]
    assert top["document_id"] == ingested["document_id"]
    assert top["title"] == title
    assert top["url"] == "https://example.org/sarvex-rag-contract"
    assert top["publisher"] == "SARVEX"
    assert top["source_priority"] == 2
    assert top["is_demo"] is False
    assert marker in top["snippet"]
    assert found["keyword_hits"] > 0

    keyword_only = client.post(
        "/api/v1/knowledge/search",
        json={
            "query": f"{SENTINEL} coherence ledger",
            "top_k": 5,
            "use_model": False,
            "rerank": False,
        },
    )
    assert keyword_only.status_code == 200
    assert any(
        citation["document_id"] == ingested["document_id"]
        for citation in keyword_only.json()["citations"]
    )

    filtered = client.post(
        "/api/v1/knowledge/search",
        json={"query": "backscatter", "top_k": 10, "categories": ["SAR_METHOD"]},
    )
    assert filtered.status_code == 200
    assert filtered.json()["citations"]
    assert all(
        citation["document_type"] == "SAR_METHOD"
        for citation in filtered.json()["citations"]
    )

    duplicate = client.post(
        "/api/v1/knowledge/ingest",
        json={"text": text, "title": title, "document_type": "SAR_METHOD"},
    )
    assert duplicate.status_code == 422, duplicate.text

    document = client.get(f"/api/v1/knowledge/documents/{ingested['document_id']}").json()
    assert document["document"]["title"] == title
    assert document["chunk_count"] == ingested["chunks"]
    assert document["checksum"]
    assert document["chunks"]
    assert all(chunk["embedding_model"] for chunk in document["chunks"])

    demo_documents = client.get(
        "/api/v1/knowledge/documents", params={"demo": True, "limit": 100}
    ).json()
    assert demo_documents["total"] >= 1
    assert all(item["is_demo"] for item in demo_documents["items"])
    assert all(item["source_priority"] == 7 for item in demo_documents["items"])


def test_knowledge_validation_errors(client):
    empty = client.post("/api/v1/knowledge/ingest", json={"title": "No content"})
    assert empty.status_code == 422

    bad_priority = client.post(
        "/api/v1/knowledge/ingest",
        json={"text": "Some valid text for a document body.", "source_priority": 9},
    )
    assert bad_priority.status_code == 422

    bad_type = client.post(
        "/api/v1/knowledge/ingest",
        json={"text": "Some valid text for a document body.", "document_type": "NOT_A_TYPE"},
    )
    assert bad_type.status_code == 422

    missing = client.get("/api/v1/knowledge/documents/does-not-exist")
    assert missing.status_code == 404
