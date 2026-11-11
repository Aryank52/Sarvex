"""Scientific copilot orchestrator.

Bounded workflow, in order:

INTENT -> CONTEXT -> DATA LOOKUP -> ANALYSIS LOOKUP -> EVIDENCE RETRIEVAL ->
SCIENTIFIC REASONING -> RESPONSE -> CITATION VALIDATION

The orchestrator never exposes shell, filesystem or arbitrary network tools to
the language model. Measurements come from persisted analysis results; scientific
statements come from retrieved citations. The model only explains.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.taxonomy import EvidenceStage
from app.copilot.tools import (
    get_analysis_tool,
    get_aoi_tool,
    get_event_tool,
    get_timeseries_tool,
    inspect_metadata_tool,
)
from app.copilot.validator import validate_answer
from app.db.models import CopilotSession, Model, ModelRun, PromptTemplate
from app.logging_config import correlation_id_var
from app.ml.interfaces import LLMProvider
from app.ml.registry import get_model_registry
from app.rag.retrieval import RetrievedChunk, retrieve
from app.schemas.knowledge import CopilotRequest, CopilotResponse

logger = logging.getLogger("sarvex.copilot")

DEFAULT_SYSTEM_PROMPT = """You are the SARVEX scientific copilot for a NASA-ISRO NISAR surface-change intelligence platform.

NON-NEGOTIABLE RULES:
1. Measurements come only from the supplied STRUCTURED_CONTEXT. Never invent numbers, units, dates, product identifiers or observations.
2. Scientific statements must be supported by the supplied citations. Cite the supplied references as [S1], [S2], ... only.
3. Never assert a cause. Use the evidence taxonomy: OBSERVED, DERIVED, DETECTED, CLASSIFIED, CONTEXTUALIZED, HYPOTHESIZED, CONFIRMED.
4. A detected change is not an earthquake, flood, landslide or eruption. Causal language requires CONFIRMED independent evidence.
5. State uncertainty and limitations explicitly. Include units with every number.
6. If the context is insufficient, say so. Do not answer from general knowledge.
7. The evidence array must only contain entries from the supplied citations, using citation_id values S1..Sn.
8. Reply with a single JSON object using exactly this contract:
{
  "answer": "string",
  "observed_facts": ["string"],
  "derived_findings": ["string"],
  "interpretations": ["string"],
  "uncertainties": ["string"],
  "evidence": [{"citation_id": "S1", "title": "...", "url": "...", "snippet": "..."}],
  "confidence": "low|moderate|high|insufficient",
  "limitations": ["string"]
}
"""


class CopilotService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.registry = get_model_registry()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def ask(self, request: CopilotRequest) -> CopilotResponse:
        started = time.perf_counter()
        copilot_session = self._resolve_session(request)
        analysis = self._analysis_context(request, copilot_session)
        event = self._event_context(request, copilot_session)
        aoi_id = (
            request.aoi_id
            or (event.get("aoi_id") if event else None)
            or (analysis.get("aoi_id") if analysis else None)
            or copilot_session.aoi_id
        )
        aoi = get_aoi_tool(self.session, aoi_id) if aoi_id else None
        if event and not analysis:
            analysis = get_analysis_tool(self.session, event.get("analysis_result_id"))
        timeseries = get_timeseries_tool(
            self.session,
            result_id=analysis.get("result_id") if analysis else None,
            aoi_id=aoi_id,
            event_id=event.get("id") if event else None,
        )
        metadata = inspect_metadata_tool(
            self.session, (analysis or {}).get("product_ids", [])
        )

        query = self._retrieval_query(request.question, event=event, analysis=analysis)
        chunks, retrieval_meta = retrieve(
            self.session,
            query=query,
            top_k=request.top_k,
            rerank=True,
            use_model=True,
        )
        citations = [chunk.citation() for chunk in chunks]
        context = {
            "question": request.question,
            "aoi": aoi,
            "event": event,
            "analysis": analysis,
            "timeseries": timeseries,
            "product_metadata": metadata,
            "citations": [
                {**citation, "citation_ref": f"S{i}"} for i, citation in enumerate(citations, start=1)
            ],
            "taxonomy_stage": self._taxonomy_stage(event, analysis),
            "demo_mode": self._is_demo(event, analysis, chunks),
            "tool_policy": "Read-only lookups already performed; no shell/filesystem/network tools are exposed.",
        }
        system_prompt = self._system_prompt()
        user_prompt = self._user_prompt(request, context, event, analysis)

        llm_response, provider_info, degraded, failure = self._generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context=context,
            analysis_present=bool(analysis),
            citations=citations,
        )

        validation = validate_answer(
            answer=str(llm_response.get("answer", "")),
            evidence=list(llm_response.get("evidence") or []),
            citations=citations,
            taxonomy_stage=context["taxonomy_stage"],
            analysis_present=bool(analysis),
            question=request.question,
        )

        # Normalize evidence into the API contract, resolving S-refs.
        evidence_out = self._normalize_evidence(
            llm_response.get("evidence") or [], citations, chunks
        )
        if request.include_evidence and not evidence_out and citations:
            # The validator rejects non-grounded evidence, but retrieval evidence
            # is still useful to the user. Present it as "retrieved", not claimed.
            evidence_out = [
                {
                    "citation_id": f"S{i}",
                    "title": c.get("title") or "",
                    "url": c.get("url"),
                    "publisher": c.get("publisher"),
                    "publication_date": c.get("publication_date"),
                    "snippet": c.get("snippet") or "",
                    "is_demo": bool(c.get("is_demo")),
                }
                for i, c in enumerate(citations, start=1)
            ]

        confidence = str(llm_response.get("confidence") or "low").lower()
        if confidence not in {"low", "moderate", "high", "insufficient"}:
            confidence = "low"
        if validation.unsupported_claims and confidence == "high":
            confidence = "moderate"

        demo_mode = context["demo_mode"]
        response = CopilotResponse(
            session_id=copilot_session.id,
            answer=validation.sanitized_answer or str(llm_response.get("answer") or ""),
            observed_facts=[str(x) for x in (llm_response.get("observed_facts") or [])],
            derived_findings=[str(x) for x in (llm_response.get("derived_findings") or [])],
            interpretations=[str(x) for x in (llm_response.get("interpretations") or [])][:8],
            uncertainties=[str(x) for x in (llm_response.get("uncertainties") or [])][:8],
            evidence=evidence_out[:8],
            confidence=confidence,
            limitations=[str(x) for x in (llm_response.get("limitations") or [])][:10],
            taxonomy_stage=context["taxonomy_stage"],
            citations_validated=validation.valid,
            unsupported_claims=validation.unsupported_claims[:10],
            model=provider_info["name"],
            model_version=provider_info["version"],
            provider=provider_info["provider"],
            degraded=degraded,
            demo_mode=demo_mode,
            retrieval=retrieval_meta,
            analysis_context={
                "result_id": analysis.get("result_id") if analysis else None,
                "event_id": event.get("id") if event else None,
                "aoi_id": aoi_id,
                "product_ids": (analysis or {}).get("product_ids", []),
                "dataset_ids": (analysis or {}).get("datasets", []),
                "timeseries_count": len(timeseries),
                "validation_notes": validation.notes,
                "llm_failure": failure,
            },
        )
        latency_ms = (time.perf_counter() - started) * 1000
        self._persist_run(
            request=request,
            response=response,
            context=context,
            retrieval_meta=retrieval_meta,
            latency_ms=latency_ms,
            provider_info=provider_info,
            failure=failure,
        )
        self._append_message(copilot_session, request, response)
        return response

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------
    def _resolve_session(self, request: CopilotRequest) -> CopilotSession:
        if request.session_id:
            session = self.session.get(CopilotSession, request.session_id)
            if not session:
                raise NotFoundError(f"Copilot session {request.session_id} not found")
            return session
        session = CopilotSession(
            aoi_id=request.aoi_id,
            event_id=request.event_id,
            result_id=request.result_id,
            title=request.question[:120],
            messages=[],
        )
        self.session.add(session)
        self.session.flush()
        return session

    def _analysis_context(self, request: CopilotRequest, session: CopilotSession) -> dict[str, Any] | None:
        result_id = request.result_id or session.result_id
        if result_id:
            analysis = get_analysis_tool(self.session, result_id=result_id)
            if not analysis:
                raise NotFoundError(f"Analysis result {result_id} not found")
            return analysis
        # If an event is supplied, its parent result is the analysis context.
        if request.event_id or session.event_id:
            from app.db.models import ChangeEvent

            event_id = request.event_id or session.event_id
            event = self.session.get(ChangeEvent, event_id)
            if event and (event.properties or {}).get("analysis_result_id"):
                return get_analysis_tool(
                    self.session, result_id=(event.properties or {})["analysis_result_id"]
                )
        return None

    def _event_context(self, request: CopilotRequest, session: CopilotSession) -> dict[str, Any] | None:
        event_id = request.event_id or session.event_id
        if not event_id:
            return None
        event = get_event_tool(self.session, event_id)
        if not event:
            raise NotFoundError(f"Change event {event_id} not found")
        return event

    @staticmethod
    def _taxonomy_stage(event: dict[str, Any] | None, analysis: dict[str, Any] | None) -> str:
        if event and event.get("taxonomy_stage"):
            return str(event["taxonomy_stage"])
        if analysis:
            return EvidenceStage.DETECTED.value
        return EvidenceStage.OBSERVED.value

    @staticmethod
    def _is_demo(event: dict[str, Any] | None, analysis: dict[str, Any] | None, chunks: list[RetrievedChunk]) -> bool:
        flags = [bool(event and event.get("is_demo")), bool(analysis and analysis.get("is_demo"))]
        if chunks and all(chunk.is_demo for chunk in chunks):
            flags.append(True)
        return any(flags)

    @staticmethod
    def _retrieval_query(question: str, *, event: dict[str, Any] | None, analysis: dict[str, Any] | None) -> str:
        parts = [question]
        if event:
            parts.append(str(event.get("event_type", "")).replace("_", " "))
        if analysis:
            parts.extend(str(t) for t in analysis.get("product_types", [])[:3])
            parts.append(str(analysis.get("result_type", "")).replace("_", " "))
        return " ".join(p for p in parts if p).strip()

    def _system_prompt(self) -> str:
        template = self.session.scalar(
            select(PromptTemplate)
            .where(PromptTemplate.name == "copilot_system", PromptTemplate.is_active.is_(True))
            .order_by(PromptTemplate.created_at.desc())
            .limit(1)
        )
        return template.template if template else DEFAULT_SYSTEM_PROMPT

    @staticmethod
    def _user_prompt(
        request: CopilotRequest,
        context: dict[str, Any],
        event: dict[str, Any] | None,
        analysis: dict[str, Any] | None,
    ) -> str:
        lines = [f"USER QUESTION: {request.question}", ""]
        if analysis:
            lines.append(
                f"ANALYSIS: {analysis.get('result_type')} | units {analysis.get('units')} | "
                f"confidence {analysis.get('confidence')} | uncertainty {analysis.get('uncertainty')}"
            )
        if event:
            lines.append(
                f"EVENT: {event.get('event_type')} | stage {event.get('taxonomy_stage')} | "
                f"magnitude {event.get('magnitude')} {event.get('magnitude_unit')} | "
                f"area_m2 {event.get('area_m2')}"
            )
        if context.get("citations"):
            lines.append("RETRIEVED CITATIONS (cite as [S1], [S2], ...):")
            for citation in context["citations"]:
                lines.append(
                    f"[{citation['citation_ref']}] {citation.get('title')} — {citation.get('snippet')}"
                )
        lines.append("")
        lines.append(
            "Explain strictly from the structured context and citations. State units, uncertainty "
            "and limitations. Do not claim a cause. Return JSON only."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Generation with explicit fallback
    # ------------------------------------------------------------------
    def _generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context: dict[str, Any],
        analysis_present: bool,
        citations: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, str], bool, str | None]:
        default_spec = self.registry.default_spec("llm")
        providers: list[LLMProvider] = []
        try:
            providers.append(self.registry.llm(default_spec.name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Default LLM unavailable: %s", exc)
        try:
            for provider in self.registry.order_providers():
                if provider not in providers:
                    providers.append(provider)
        except Exception:  # noqa: BLE001
            pass
        if not providers:
            # Last-resort deterministic refusal composer, still registry-defined.
            from app.ml.providers import DeterministicGroundedLLM

            providers = [DeterministicGroundedLLM()]
            default_spec = self.registry.default_spec("llm")

        failure: str | None = None
        for provider in providers:
            try:
                output = provider.generate(
                    system_prompt=system_prompt, user_prompt=user_prompt, context=context
                )
                info = {
                    "name": getattr(provider, "name", default_spec.name),
                    "version": getattr(provider, "version", default_spec.version),
                    "provider": getattr(provider, "provider", default_spec.provider),
                }
                # A deterministic, non-generative composer is transparently marked
                # as degraded even when configured as default.
                health = provider.health()
                degraded = bool(
                    health.get("generative") is False
                    or health.get("type") == "deterministic_grounded"
                    or provider is not providers[0]
                )
                if provider is not providers[0] and failure:
                    logger.warning("LLM fallback engaged after: %s", failure)
                return output, info, degraded, failure
            except Exception as exc:  # noqa: BLE001 - fallback path is explicit
                failure = f"{provider.__class__.__name__}: {exc}"
                logger.warning("LLM provider failed, trying fallback: %s", failure)
                continue
        # All providers failed: deterministic refusal, clearly marked.
        info = {"name": "grounded-fallback", "version": "1.0", "provider": "sarvex"}
        return (
            {
                "answer": "No language-model provider was available. SARVEX will not answer without grounded evidence.",
                "observed_facts": [],
                "derived_findings": [],
                "interpretations": [],
                "uncertainties": ["Model provider unavailable."],
                "evidence": [],
                "confidence": "insufficient",
                "limitations": ["LLM unavailable; no explanatory text generated."],
            },
            info,
            True,
            failure,
        )

    @staticmethod
    def _normalize_evidence(
        evidence: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        chunks: list[RetrievedChunk],
    ) -> list[dict[str, Any]]:
        by_ref = {f"S{i}": c for i, c in enumerate(citations, start=1)}
        by_id = {str(c.get("id")): c for c in citations}
        by_title = {str(c.get("title")): c for c in citations}
        output: list[dict[str, Any]] = []
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            ref = str(entry.get("citation_id") or entry.get("id") or "")
            citation = by_ref.get(ref) or by_id.get(ref) or by_title.get(str(entry.get("title") or ""))
            if not citation:
                continue
            output.append(
                {
                    "citation_id": ref if ref.startswith("S") else f"S{citations.index(citation) + 1}",
                    "title": citation.get("title") or "",
                    "url": citation.get("url"),
                    "publisher": citation.get("publisher"),
                    "publication_date": citation.get("publication_date"),
                    "snippet": str(entry.get("snippet") or citation.get("snippet") or "")[:800],
                    "is_demo": bool(citation.get("is_demo")),
                }
            )
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for entry in output:
            key = entry["citation_id"] + entry["title"]
            if key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        return unique

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _persist_run(
        self,
        *,
        request: CopilotRequest,
        response: CopilotResponse,
        context: dict[str, Any],
        retrieval_meta: dict[str, Any],
        latency_ms: float,
        provider_info: dict[str, str],
        failure: str | None,
    ) -> None:
        model = self.session.scalar(
            select(Model).where(
                Model.category == "llm",
                Model.name == provider_info["name"],
                Model.version == provider_info["version"],
            )
        )
        self.session.add(
            ModelRun(
                model_id=model.id if model else None,
                purpose="copilot",
                model_name=provider_info["name"],
                model_version=provider_info["version"],
                input_summary={
                    "question_hash": hashlib.sha256(request.question.encode("utf-8")).hexdigest()[:16],
                    "question_length": len(request.question),
                    "event_id": (context.get("event") or {}).get("id"),
                    "result_id": (context.get("analysis") or {}).get("result_id"),
                    "citations": len(context.get("citations") or []),
                    "demo_mode": response.demo_mode,
                },
                output_summary={
                    "confidence": response.confidence,
                    "citations_validated": response.citations_validated,
                    "unsupported_claims": len(response.unsupported_claims),
                    "degraded": response.degraded,
                },
                latency_ms=latency_ms,
                status="COMPLETED" if not failure else "DEGRADED",
                error=failure,
                correlation_id=correlation_id_var.get(),
            )
        )
        self.session.commit()

    def _append_message(
        self, copilot_session: CopilotSession, request: CopilotRequest, response: CopilotResponse
    ) -> None:
        messages = list(copilot_session.messages or [])
        messages.append(
            {
                "role": "user",
                "content": request.question,
                "at": datetime.now(timezone.utc).isoformat(),
                "event_id": response.analysis_context.get("event_id"),
                "result_id": response.analysis_context.get("result_id"),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "content": response.answer,
                "at": datetime.now(timezone.utc).isoformat(),
                "confidence": response.confidence,
                "degraded": response.degraded,
                "citations_validated": response.citations_validated,
                "model": response.model,
                "model_version": response.model_version,
            }
        )
        copilot_session.messages = messages[-40:]
        if request.aoi_id:
            copilot_session.aoi_id = request.aoi_id
        if request.event_id:
            copilot_session.event_id = request.event_id
        if request.result_id:
            copilot_session.result_id = request.result_id
        copilot_session.title = copilot_session.title or request.question[:120]
        self.session.commit()
