"""RAG, copilot, models and reporting schemas."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, UTCDateTime

CorpusCategory = Literal[
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
]


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    top_k: int = Field(default=6, ge=1, le=20)
    categories: list[CorpusCategory] = Field(default_factory=list)
    keyword_weight: float = Field(default=0.45, ge=0, le=1)
    rerank: bool = True
    use_model: bool = True


class CitationOut(BaseModel):
    id: str
    chunk_id: str
    document_id: str
    title: str
    url: str | None = None
    publisher: str | None = None
    author: str | None = None
    publication_date: str | None = None
    section: str | None = None
    page: int | None = None
    document_type: str
    scientific_topic: str | None = None
    source_priority: int
    snippet: str
    score: float
    is_demo: bool = False


class RagSearchResponse(BaseModel):
    query: str
    citations: list[CitationOut]
    embedding_model: str
    reranker: str
    keyword_hits: int
    vector_hits: int
    latency_ms: float
    demo_mode: bool


class RagIngestRequest(BaseModel):
    path: str | None = None
    text: str | None = None
    title: str | None = None
    url: str | None = None
    author: str | None = None
    publisher: str | None = None
    document_type: CorpusCategory = "INTERNAL_SARVEX"
    scientific_topic: str | None = None
    mission: str | None = "NISAR"
    product_type: str | None = None
    license: str | None = None
    source_priority: int = Field(default=7, ge=1, le=7)


class RagIngestResponse(BaseModel):
    document_id: str
    title: str
    chunks: int
    embeddings: int
    embedding_model: str
    is_demo: bool


class RagDocumentOut(ORMModel):
    id: str
    title: str
    author: str | None
    publisher: str | None
    publication_date: UTCDateTime | None
    url: str | None
    document_type: str
    scientific_topic: str | None
    mission: str | None
    product_type: str | None
    license: str | None
    source_priority: int
    is_demo: bool
    created_at: UTCDateTime


class RagStats(BaseModel):
    documents: int
    chunks: int
    embeddings: int
    embedding_model: str
    reranker_model: str
    llm_model: str
    demo_documents: int


class CopilotRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    session_id: str | None = None
    aoi_id: str | None = None
    event_id: str | None = None
    result_id: str | None = None
    top_k: int = Field(default=6, ge=1, le=12)
    include_evidence: bool = True


class CopilotEvidence(BaseModel):
    citation_id: str
    title: str
    url: str | None
    publisher: str | None
    publication_date: str | None
    snippet: str
    is_demo: bool = False


class CopilotResponse(BaseModel):
    session_id: str
    answer: str
    observed_facts: list[str] = Field(default_factory=list)
    derived_findings: list[str] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    evidence: list[CopilotEvidence] = Field(default_factory=list)
    confidence: str
    limitations: list[str] = Field(default_factory=list)
    taxonomy_stage: str
    citations_validated: bool
    unsupported_claims: list[str] = Field(default_factory=list)
    model: str
    model_version: str
    provider: str
    degraded: bool = False
    demo_mode: bool = False
    retrieval: dict[str, Any] = Field(default_factory=dict)
    analysis_context: dict[str, Any] = Field(default_factory=dict)


class ModelInfoOut(BaseModel):
    category: str
    name: str
    provider: str
    version: str
    task: str | None = None
    framework: str | None = None
    status: str
    is_default: bool
    capabilities: dict[str, Any] = Field(default_factory=dict)
    health: dict[str, Any] = Field(default_factory=dict)


class ReportCreate(BaseModel):
    result_id: str | None = None
    event_id: str | None = None
    title: str | None = None
    format: Literal["markdown", "html"] = "markdown"


class ReportOut(ORMModel):
    id: str
    title: str
    report_type: str
    result_id: str | None
    event_id: str | None
    format: str
    content: str
    artifact_uri: str | None
    provenance: dict[str, Any]
    created_at: UTCDateTime


class ReportSummaryOut(ORMModel):
    id: str
    title: str
    report_type: str
    result_id: str | None
    event_id: str | None
    format: str
    artifact_uri: str | None
    created_at: UTCDateTime
