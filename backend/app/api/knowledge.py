"""Scientific knowledge base, hybrid retrieval and grounded copilot endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, rate_limit
from app.core.errors import NotFoundError
from app.copilot.orchestrator import CopilotService
from app.db.models import AuditLog, CopilotSession, Document, DocumentChunk
from app.ml.registry import get_model_registry
from app.rag.ingest import ingest_document, rag_stats
from app.rag.retrieval import retrieve
from app.schemas.common import Page
from app.schemas.knowledge import (
    CopilotRequest,
    CopilotResponse,
    RagDocumentOut,
    RagIngestRequest,
    RagIngestResponse,
    RagSearchRequest,
    RagSearchResponse,
    RagStats,
)

router = APIRouter(tags=["knowledge"], dependencies=[Depends(rate_limit)])


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
@router.post("/knowledge/search", response_model=RagSearchResponse)
def search_knowledge(
    request: RagSearchRequest, db: Session = Depends(get_db)
) -> RagSearchResponse:
    chunks, meta = retrieve(
        db,
        query=request.query,
        top_k=request.top_k,
        categories=list(request.categories) or None,
        keyword_weight=request.keyword_weight,
        rerank=request.rerank,
        use_model=request.use_model,
    )
    citations = [chunk.citation() for chunk in chunks]
    return RagSearchResponse(
        query=request.query,
        citations=citations,
        embedding_model=meta.get("embedding_model", "unknown"),
        reranker=meta.get("reranker", "none"),
        keyword_hits=meta.get("keyword_hits", 0),
        vector_hits=meta.get("vector_hits", 0),
        latency_ms=meta.get("latency_ms", 0.0),
        demo_mode=bool(citations) and all(c.get("is_demo") for c in citations),
    )


@router.get("/knowledge/stats", response_model=RagStats)
def knowledge_stats(db: Session = Depends(get_db)) -> RagStats:
    return RagStats(**rag_stats(db))


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@router.get("/knowledge/documents", response_model=Page[RagDocumentOut])
def list_documents(
    document_type: str | None = None,
    demo: bool | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> Page[RagDocumentOut]:
    stmt = select(Document)
    if document_type:
        stmt = stmt.where(Document.document_type == document_type)
    if demo is not None:
        stmt = stmt.where(Document.is_demo.is_(demo))
    total = int(db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = db.scalars(
        stmt.order_by(Document.source_priority, Document.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[RagDocumentOut](
        items=[RagDocumentOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/knowledge/documents/{document_id}")
def get_document(
    document_id: str,
    include_chunks: bool = True,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    document = db.get(Document, document_id)
    if not document:
        raise NotFoundError(f"Document {document_id} not found")
    chunks = db.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    payload = {
        "document": RagDocumentOut.model_validate(document).model_dump(mode="json"),
        "source_uri": document.source_uri,
        "checksum": document.checksum,
        "extra_metadata": document.extra_metadata,
        "chunk_count": len(chunks),
    }
    if include_chunks:
        payload["chunks"] = [
            {
                "id": chunk.id,
                "index": chunk.chunk_index,
                "section": chunk.section,
                "page": chunk.page,
                "text": chunk.text,
                "token_count": chunk.token_count,
                "embedding_model": chunk.embedding_model,
                "embedding_version": chunk.embedding_version,
            }
            for chunk in chunks
        ]
    return payload


@router.post("/knowledge/ingest", response_model=RagIngestResponse, status_code=201)
def ingest_knowledge(
    request: RagIngestRequest, db: Session = Depends(get_db)
) -> RagIngestResponse:
    document, chunk_count, embedding_count = ingest_document(
        db,
        text=request.text,
        path=request.path,
        title=request.title,
        url=request.url,
        author=request.author,
        publisher=request.publisher,
        document_type=request.document_type,
        scientific_topic=request.scientific_topic,
        mission=request.mission,
        product_type=request.product_type,
        license_text=request.license,
        source_priority=request.source_priority,
        is_demo=False,
    )
    db.add(
        AuditLog(
            actor="api_client",
            action="knowledge.document_ingested",
            entity_type="document",
            entity_id=document.id,
            detail={
                "document_type": document.document_type,
                "chunks": chunk_count,
                "embeddings": embedding_count,
                "source_priority": document.source_priority,
            },
        )
    )
    db.commit()
    provider = get_model_registry().embedding_provider()
    return RagIngestResponse(
        document_id=document.id,
        title=document.title,
        chunks=chunk_count,
        embeddings=embedding_count,
        embedding_model=f"{provider.name}@{provider.version}",
        is_demo=document.is_demo,
    )


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------
@router.post("/copilot/ask", response_model=CopilotResponse)
def ask_copilot(request: CopilotRequest, db: Session = Depends(get_db)) -> CopilotResponse:
    return CopilotService(db).ask(request)


@router.get("/copilot/sessions")
def list_copilot_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.scalars(
        select(CopilotSession).order_by(CopilotSession.updated_at.desc()).limit(limit)
    ).all()
    return {
        "sessions": [
            {
                "id": session.id,
                "title": session.title,
                "aoi_id": session.aoi_id,
                "event_id": session.event_id,
                "result_id": session.result_id,
                "messages": len(session.messages or []),
                "updated_at": session.updated_at.isoformat(),
            }
            for session in rows
        ]
    }


@router.get("/copilot/sessions/{session_id}")
def get_copilot_session(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.get(CopilotSession, session_id)
    if not session:
        raise NotFoundError(f"Copilot session {session_id} not found")
    return {
        "id": session.id,
        "title": session.title,
        "aoi_id": session.aoi_id,
        "event_id": session.event_id,
        "result_id": session.result_id,
        "messages": session.messages or [],
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
    }
