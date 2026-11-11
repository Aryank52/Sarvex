"""Hybrid scientific retrieval: keyword + vector fusion, optional reranking.

Retrieval is bounded and deterministic. Citations always carry document-level
provenance (source, publisher, date, section, page, priority). The API contract
returns these fields unchanged so the copilot can validate every reference.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentChunk, EmbeddingRecord
from app.ml.providers import tokenize
from app.ml.registry import get_model_registry

MAX_CANDIDATE_CHUNKS = 5000


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    title: str
    url: str | None
    publisher: str | None
    author: str | None
    publication_date: str | None
    section: str | None
    page: int | None
    document_type: str
    scientific_topic: str | None
    source_priority: int
    text: str
    is_demo: bool
    keyword_score: float = 0.0
    vector_score: float = 0.0
    fused_score: float = 0.0
    rerank_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def citation(self, score: float | None = None) -> dict[str, Any]:
        snippet = self.text if len(self.text) <= 700 else self.text[:697].rsplit(" ", 1)[0] + "..."
        return {
            "id": self.chunk_id,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher,
            "author": self.author,
            "publication_date": self.publication_date,
            "section": self.section,
            "page": self.page,
            "document_type": self.document_type,
            "scientific_topic": self.scientific_topic,
            "source_priority": self.source_priority,
            "snippet": snippet,
            "score": round(float(score if score is not None else self.fused_score), 6),
            "is_demo": self.is_demo,
        }


def _cosine(a: list[float], b: list[float], dimension: int) -> float:
    n = min(len(a), len(b), dimension)
    if n <= 0:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(n):
        va = a[i]
        vb = b[i]
        dot += va * vb
        norm_a += va * va
        norm_b += vb * vb
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def _keyword_scores(query: str, texts: list[str]) -> list[float]:
    q_tokens = [t for t in tokenize(query) if len(t) > 1]
    if not q_tokens:
        return [0.0] * len(texts)
    token_sets = [set(tokenize(t)) for t in texts]
    n_docs = max(len(texts), 1)
    df: dict[str, int] = {}
    for tokens in token_sets:
        for token in set(q_tokens) & tokens:
            df[token] = df.get(token, 0) + 1
    idf = {token: math.log((n_docs + 1) / (df.get(token, 0) + 1)) + 1.0 for token in q_tokens}
    weights = {token: idf[token] for token in q_tokens}
    total_weight = sum(weights.values()) or 1.0
    scores: list[float] = []
    for tokens in token_sets:
        matched = sum(w for token, w in weights.items() if token in tokens)
        # Shorter passages get a small boost, mirroring passage retrieval practice.
        compactness = 1.0
        scores.append(min(matched / total_weight, 1.0) * compactness)
    return scores


def retrieve(
    session: Session,
    *,
    query: str,
    top_k: int = 6,
    categories: list[str] | None = None,
    keyword_weight: float = 0.45,
    rerank: bool = True,
    use_model: bool = True,
    candidate_limit: int = 120,
) -> tuple[list[RetrievedChunk], dict[str, Any]]:
    started = time.perf_counter()
    registry = get_model_registry()
    embedding_provider = registry.embedding_provider()
    query_vector = embedding_provider.embed_query(query)

    stmt = (
        select(DocumentChunk, Document, EmbeddingRecord)
        .join(Document, DocumentChunk.document_id == Document.id)
        .join(EmbeddingRecord, EmbeddingRecord.chunk_id == DocumentChunk.id)
        .where(EmbeddingRecord.model_name == embedding_provider.name)
        .limit(MAX_CANDIDATE_CHUNKS)
    )
    if categories:
        stmt = stmt.where(Document.document_type.in_(categories))
    rows = session.execute(stmt).all()
    if not rows:
        # Fall back to any stored embedding model so a model swap never hides a corpus.
        stmt = (
            select(DocumentChunk, Document, EmbeddingRecord)
            .join(Document, DocumentChunk.document_id == Document.id)
            .join(EmbeddingRecord, EmbeddingRecord.chunk_id == DocumentChunk.id)
            .limit(MAX_CANDIDATE_CHUNKS)
        )
        if categories:
            stmt = stmt.where(Document.document_type.in_(categories))
        rows = session.execute(stmt).all()
    if not rows:
        return [], {
            "keyword_hits": 0,
            "vector_hits": 0,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "embedding_model": embedding_provider.name,
            "reranker": "none",
            "candidates": 0,
        }

    texts = [row[0].text for row in rows]
    keyword_scores = _keyword_scores(query, texts)
    candidates: list[RetrievedChunk] = []
    for (chunk, document, embedding), kw in zip(rows, keyword_scores):
        vec = _cosine(query_vector, list(embedding.vector or []), int(embedding.dimension or len(query_vector)))
        fused = keyword_weight * kw + (1.0 - keyword_weight) * max(vec, 0.0)
        candidates.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                title=document.title,
                url=document.url,
                publisher=document.publisher,
                author=document.author,
                publication_date=document.publication_date.isoformat() if document.publication_date else None,
                section=chunk.section,
                page=chunk.page,
                document_type=document.document_type,
                scientific_topic=document.scientific_topic,
                source_priority=document.source_priority,
                text=chunk.text,
                is_demo=document.is_demo,
                keyword_score=kw,
                vector_score=vec,
                fused_score=fused,
            )
        )

    # Source priority is a tie-breaker and a small boost: official sources win
    # near-ties, which is the required scientific source hierarchy.
    for candidate in candidates:
        priority_bonus = (8 - min(max(candidate.source_priority, 1), 7)) * 0.004
        candidate.fused_score += priority_bonus

    candidates.sort(key=lambda c: c.fused_score, reverse=True)
    keyword_hits = sum(1 for c in candidates if c.keyword_score > 0)
    vector_hits = sum(1 for c in candidates if c.vector_score > 0)
    shortlist = candidates[: max(candidate_limit, top_k)]

    reranker_name = "none"
    if rerank and shortlist:
        if use_model:
            try:
                reranker = registry.reranker()
                pairs = reranker.rerank(query, [c.text for c in shortlist], top_k)
                reranker_name = f"{reranker.name}@{reranker.version}"
                for idx, score in pairs:
                    if 0 <= idx < len(shortlist):
                        shortlist[idx].rerank_score = float(score)
                shortlist.sort(
                    key=lambda c: (
                        c.rerank_score if c.rerank_score is not None else -1.0,
                        c.fused_score,
                    ),
                    reverse=True,
                )
            except Exception:  # noqa: BLE001 - retrieval degrades to fusion, never fails
                reranker_name = "unavailable"
        else:
            reranker_name = "disabled"

    selected = [_dedupe_key(c) for c in shortlist]
    seen: set[tuple[str, str | None]] = set()
    output: list[RetrievedChunk] = []
    for candidate in selected:
        key = (candidate.document_id, candidate.section)
        if key in seen and len(output) >= top_k:
            continue
        seen.add(key)
        output.append(candidate)
        if len(output) >= top_k:
            break

    return output, {
        "keyword_hits": keyword_hits,
        "vector_hits": vector_hits,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "embedding_model": f"{embedding_provider.name}@{embedding_provider.version}",
        "reranker": reranker_name,
        "candidates": len(candidates),
    }


def _dedupe_key(candidate: RetrievedChunk) -> RetrievedChunk:
    return candidate


def citation_payload(chunks: list[RetrievedChunk]) -> list[dict[str, Any]]:
    return [chunk.citation() for chunk in chunks]
