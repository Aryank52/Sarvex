"""Knowledge-base ingestion: extract, chunk, embed, store with provenance.

Every chunk retains full source metadata. Embeddings are stored with their true
dimension; storage pads to the pgvector capacity without altering the recorded
dimension, so a model swap does not corrupt retrieval.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BACKEND_DIR, get_settings
from app.core.errors import ValidationError
from app.core.geometry import sha256_bytes
from app.db.models import Document, DocumentChunk, EmbeddingRecord
from app.ml.registry import EMBEDDING_STORAGE_CAPACITY, get_model_registry
from app.rag.chunking import chunk_document
from app.rag.extract import ExtractedDocument, extract_path, resolve_document_path

logger = logging.getLogger("sarvex.rag.ingest")

DOCUMENT_TYPES = {
    "NISAR_MISSION",
    "NISAR_PRODUCT",
    "SAR_METHOD",
    "INSAR_METHOD",
    "POLARIMETRY",
    "GEOSPATIAL",
    "SCIENTIFIC_LITERATURE",
    "PROCESSING_DOCUMENTATION",
    "MODEL_DOCUMENTATION",
    "INTERNAL_SARVEX",
}

RAG_ROOTS = [
    BACKEND_DIR / "data" / "knowledge",
    BACKEND_DIR / "data" / "uploads" / "documents",
]


def pad_embedding(vector: list[float], capacity: int = EMBEDDING_STORAGE_CAPACITY) -> list[float]:
    """Zero-pad to storage capacity. Cosine similarity is unchanged.

    Dimensions above capacity are rejected explicitly by the registry, so this
    function never truncates.
    """
    if len(vector) > capacity:
        raise ValidationError(
            f"Embedding dimension {len(vector)} exceeds pgvector capacity {capacity}; "
            "SARVEX refuses silent truncation"
        )
    if len(vector) == capacity:
        return [float(v) for v in vector]
    return [float(v) for v in vector] + [0.0] * (capacity - len(vector))


def ingest_document(
    session: Session,
    *,
    text: str | None = None,
    path: str | Path | None = None,
    title: str | None = None,
    url: str | None = None,
    author: str | None = None,
    publisher: str | None = None,
    publication_date: datetime | None = None,
    document_type: str = "INTERNAL_SARVEX",
    scientific_topic: str | None = None,
    mission: str | None = "NISAR",
    product_type: str | None = None,
    license_text: str | None = None,
    source_priority: int = 7,
    is_demo: bool = False,
    extra_metadata: dict[str, Any] | None = None,
    embedding_model_name: str | None = None,
) -> tuple[Document, int, int]:
    if document_type not in DOCUMENT_TYPES:
        raise ValidationError(
            f"Unknown document_type '{document_type}'",
            detail={"allowed": sorted(DOCUMENT_TYPES)},
        )
    if not 1 <= int(source_priority) <= 7:
        raise ValidationError("source_priority must be between 1 (official) and 7 (other trusted)")
    if not text and not path:
        raise ValidationError("Either text or a document path is required")

    extracted = ExtractedDocument(text=text or "", extraction_method="supplied_text")
    source_uri: str | None = None
    checksum: str | None = None
    resolved_title = title
    if path:
        resolved = resolve_document_path(str(path), roots=RAG_ROOTS) if not Path(path).is_absolute() else Path(path)
        extracted = extract_path(resolved, allowed_roots=RAG_ROOTS if not Path(path).is_absolute() else None)
        source_uri = resolved.as_uri()
        checksum = sha256_bytes(resolved.read_bytes())
        resolved_title = resolved_title or extracted.title_hint or resolved.stem
    if not extracted.text.strip():
        raise ValidationError("Document has no extractable text")
    resolved_title = resolved_title or "Untitled scientific document"
    if checksum is None:
        checksum = sha256_bytes(extracted.text.encode("utf-8"))

    duplicate = session.scalar(select(Document).where(Document.checksum == checksum))
    if duplicate:
        raise ValidationError(
            "A document with identical content already exists",
            detail={"document_id": duplicate.id, "title": duplicate.title},
        )

    document = Document(
        title=resolved_title[:400],
        author=author,
        publisher=publisher,
        publication_date=publication_date,
        url=url,
        document_type=document_type,
        scientific_topic=scientific_topic,
        mission=mission,
        product_type=product_type,
        license=license_text,
        source_priority=int(source_priority),
        checksum=checksum,
        source_uri=source_uri,
        extra_metadata={
            **(extra_metadata or {}),
            "extraction_method": extracted.extraction_method,
            "pages": len(extracted.pages) if extracted.pages else None,
        },
        is_demo=is_demo,
    )
    session.add(document)
    session.flush()

    chunks = chunk_document(text=extracted.text, pages=extracted.pages or None)
    if not chunks:
        raise ValidationError("Document produced no chunks")
    registry = get_model_registry()
    provider = registry.embedding_provider(embedding_model_name)
    vectors = provider.embed_documents([c.text for c in chunks])
    if len(vectors) != len(chunks):
        raise ValidationError("Embedding provider returned a mismatched number of vectors")
    if any(len(v) != provider.dimension for v in vectors):
        raise ValidationError(
            "Embedding provider returned vectors inconsistent with its declared dimension"
        )
    for chunk, vector in zip(chunks, vectors):
        record = DocumentChunk(
            document_id=document.id,
            chunk_index=chunk.index,
            section=chunk.section,
            page=chunk.page,
            text=chunk.text,
            token_count=chunk.token_estimate,
            embedding_model=provider.name,
            embedding_version=provider.version,
            chunk_metadata={
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "document_title": document.title,
                "source_priority": document.source_priority,
            },
        )
        session.add(record)
        session.flush()
        session.add(
            EmbeddingRecord(
                chunk_id=record.id,
                model_name=provider.name,
                model_version=provider.version,
                dimension=provider.dimension,
                vector=pad_embedding(vector),
            )
        )
    session.commit()
    logger.info(
        "Ingested document '%s' with %s chunks using %s@%s",
        document.title,
        len(chunks),
        provider.name,
        provider.version,
    )
    return document, len(chunks), len(vectors)


def rag_stats(session: Session) -> dict[str, Any]:
    from sqlalchemy import func

    registry = get_model_registry()
    documents = session.scalar(select(func.count(Document.id))) or 0
    chunks = session.scalar(select(func.count(DocumentChunk.id))) or 0
    embeddings = session.scalar(select(func.count(EmbeddingRecord.id))) or 0
    demo_documents = session.scalar(select(func.count(Document.id)).where(Document.is_demo.is_(True))) or 0
    return {
        "documents": int(documents),
        "chunks": int(chunks),
        "embeddings": int(embeddings),
        "embedding_model": registry.default_spec("embedding").name,
        "reranker_model": registry.default_spec("reranker").name,
        "llm_model": registry.default_spec("llm").name,
        "demo_documents": int(demo_documents),
    }


def seed_document_paths() -> list[Path]:
    """Return bundled knowledge files, if the operator has placed any."""
    paths: list[Path] = []
    for root in RAG_ROOTS:
        if root.exists():
            paths.extend(sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt", ".pdf", ".html"}))
    return paths


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
