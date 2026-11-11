"""Provider implementations for embeddings, reranking and language models.

Only this module knows provider wire formats. Every provider is selected through
the model registry, so swapping models later is configuration, not refactoring.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from app.core.errors import CapabilityUnavailableError
from app.ml.interfaces import EmbeddingProvider, LLMProvider, RerankerProvider

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-_.]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "by", "as", "at", "from", "that", "this", "it",
    "which", "what", "how", "why", "does", "do", "can", "could", "should",
}


def tokenize(text: str) -> list[str]:
    tokens = [m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")]
    return [t for t in tokens if t not in _STOPWORDS]


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic feature-hashing embedding.

    This is a real lexical vector representation (signed feature hashing with
    sublinear term frequency), suitable for offline retrieval evaluation. It is
    explicitly labelled deterministic and is not a semantic neural embedding.
    """

    def __init__(self, dimension: int = 384, name: str = "sarvex-hash-embedding", version: str = "1.0") -> None:
        if dimension < 32:
            raise ValueError("Embedding dimension must be >= 32")
        self.dimension = dimension
        self.name = name
        self.version = version

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = tokenize(text)
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        counts: dict[str, int] = {}
        for gram in grams:
            counts[gram] = counts.get(gram, 0) + 1
        for gram, count in counts.items():
            digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
            raw = int.from_bytes(digest, "big")
            idx = raw % self.dimension
            sign = -1.0 if (raw >> 63) & 1 else 1.0
            vec[idx] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": self.name,
            "version": self.version,
            "dimension": self.dimension,
            "type": "deterministic_feature_hashing",
            "semantic": False,
        }


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        version: str,
        dimension: int,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.name = model
        self.version = version
        self.dimension = dimension
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _call(self, texts: list[str]) -> list[list[float]]:
        if not self.configured:
            raise CapabilityUnavailableError(
                f"Embedding provider '{self.name}' has no base URL configured"
            )
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.name, "input": texts},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise CapabilityUnavailableError(f"Embedding request failed: {exc}") from exc
        entries = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
        vectors = [list(map(float, e["embedding"])) for e in entries]
        for vector in vectors:
            if len(vector) != self.dimension:
                raise CapabilityUnavailableError(
                    f"Embedding dimension mismatch: provider returned {len(vector)}, "
                    f"registry expects {self.dimension}. Update the model registry dimension."
                )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._call(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._call([text])[0]

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.configured else "unconfigured",
            "provider": self.name,
            "version": self.version,
            "dimension": self.dimension,
            "type": "openai_compatible",
            "base_url": self.base_url or None,
        }


class LexicalReranker(RerankerProvider):
    """Deterministic lexical reranker used offline and as a safe fallback."""

    name = "lexical-overlap-reranker"
    version = "1.0"

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        q = set(tokenize(query))
        if not q:
            return [(i, 0.0) for i in range(min(top_k, len(documents)))]
        scored: list[tuple[int, float]] = []
        for idx, doc in enumerate(documents):
            tokens = tokenize(doc)
            if not tokens:
                continue
            d = set(tokens)
            overlap = len(q & d) / max(len(q), 1)
            coverage = len(q & d) / max(len(d), 1)
            # Reward numbers shared with the query (units, dates are scientifically salient).
            q_nums = {t for t in tokenize(query) if t.replace(".", "").isdigit()}
            d_nums = {t for t in tokens if t.replace(".", "").isdigit()}
            numeric_bonus = 0.15 * (len(q_nums & d_nums) / max(len(q_nums), 1)) if q_nums else 0.0
            score = 0.7 * overlap + 0.3 * coverage + numeric_bonus
            scored.append((idx, float(score)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class HTTPReranker(RerankerProvider):
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        version: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.name = model
        self.version = version
        self.timeout = timeout

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        if not self.base_url:
            raise CapabilityUnavailableError(f"Reranker '{self.name}' has no base URL configured")
        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/rerank",
                    json={"model": self.name, "query": query, "documents": documents, "top_n": top_k},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise CapabilityUnavailableError(f"Reranker request failed: {exc}") from exc
        results = data.get("results") or data.get("data") or []
        out = [
            (int(item.get("index", 0)), float(item.get("relevance_score", item.get("score", 0.0))))
            for item in results
        ]
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:top_k]

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.base_url else "unconfigured",
            "provider": self.name,
            "version": self.version,
            "type": "http_rerank",
        }


class DeterministicGroundedLLM(LLMProvider):
    """Evidence-only composer used as the safe default and degraded fallback.

    It does not generate free-form scientific claims. Every sentence is built
    from the structured analysis context or from retrieved evidence snippets,
    and all evidence references are explicit.
    """

    name = "grounded-extractive-composer"
    version = "1.0"
    provider = "sarvex"

    def generate(self, *, system_prompt: str, user_prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        analysis = context.get("analysis") or {}
        event = context.get("event") or {}
        citations = context.get("citations") or []
        question = str(context.get("question") or user_prompt).strip()
        limitations = [
            "Explanations are limited to the structured measurements and retrieved evidence shown.",
            "Detected patterns do not establish causality.",
        ]
        observed: list[str] = []
        derived: list[str] = []
        interpretations: list[str] = []
        uncertainties: list[str] = []
        evidence_refs: list[dict[str, Any]] = []
        if analysis:
            observed.append(
                f"Analysis '{analysis.get('result_type')}' used products {', '.join(analysis.get('product_ids', [])) or 'unspecified'} "
                f"over {', '.join(str(d) for d in analysis.get('dates', []) if d) or 'unspecified dates'}."
            )
            stats = analysis.get("statistics") or {}
            if stats.get("median_change_db") is not None:
                derived.append(f"Median backscatter change in detected regions: {stats['median_change_db']:.2f} dB.")
            if stats.get("median_ratio_change_db") is not None:
                derived.append(
                    "Median VV/VH ratio change in detected regions: "
                    f"{stats['median_ratio_change_db']:.2f} dB."
                )
            if stats.get("total_change_area_km2") is not None:
                derived.append(f"Detected area: {stats['total_change_area_km2']:.3f} km².")
            if stats.get("median_displacement_mm") is not None:
                derived.append(f"Median LOS displacement: {stats['median_displacement_mm']:.2f} mm (relative to AOI median).")
            if stats.get("p95_displacement_mm") is not None:
                derived.append(
                    f"95th-percentile |LOS displacement|: {stats['p95_displacement_mm']:.2f} mm."
                )
            if stats.get("trend_db_per_year") is not None:
                derived.append(
                    f"Robust Theil-Sen backscatter trend: {stats['trend_db_per_year']:.3f} dB/year."
                )
            if stats.get("magnitude_m") is not None:
                derived.append(
                    "Estimated image offset magnitude: "
                    f"{stats['magnitude_m']:.2f} m (shift x={stats.get('shift_x_px', 0.0):.2f} px, "
                    f"y={stats.get('shift_y_px', 0.0):.2f} px)."
                )
            if analysis.get("confidence") is not None:
                uncertainties.append(f"Analysis confidence score: {float(analysis['confidence']):.2f} (detection confidence, not hazard probability).")
            if analysis.get("uncertainty") is not None:
                uncertainties.append(f"Reported uncertainty: {float(analysis['uncertainty']):.3f} {analysis.get('units') or ''}.")
            for lim in stats.get("limitations", []) or []:
                limitations.append(str(lim))
            if event:
                interpretations.append(
                    f"Event category '{event.get('event_type')}' is at taxonomy stage {event.get('taxonomy_stage')} "
                    f"({event.get('classification_method') or 'algorithmic detection'})."
                )
                for label in event.get("candidate_labels", []) or []:
                    interpretations.append(f"Candidate hypothesis label: {label} (requires independent validation).")
        for i, citation in enumerate(citations[:4], start=1):
            snippet = _first_sentence(citation.get("snippet", ""))
            if snippet:
                observed.append(f"Knowledge base [{i}]: {snippet}")
            evidence_refs.append(
                {
                    "citation_id": f"S{i}",
                    "title": citation.get("title"),
                    "url": citation.get("url"),
                    "snippet": snippet,
                    "publisher": citation.get("publisher"),
                }
            )
        if analysis:
            answer_parts = [str(analysis.get("summary") or "")]
            if interpretations:
                answer_parts.append(" ".join(interpretations[:2]))
            if evidence_refs:
                answer_parts.append("Scientific context is cited from the retrieved knowledge base [S1].")
            answer = " ".join(part for part in answer_parts if part).strip()
            confidence = "moderate" if (analysis.get("confidence") or 0) >= 0.6 else "low"
        elif evidence_refs:
            answer = (
                "No analysis result was supplied for this question. Based only on the retrieved knowledge base, "
                f"the most relevant evidence states: {_first_sentence(citations[0].get('snippet', ''))} [S1]."
            )
            confidence = "low"
        else:
            answer = (
                f"No grounded analysis result or knowledge-base evidence was available for '{question[:180]}'. "
                "SARVEX will not answer this scientific question from an ungrounded model."
            )
            confidence = "insufficient"
            interpretations = []
        return {
            "answer": answer,
            "observed_facts": observed,
            "derived_findings": derived,
            "interpretations": interpretations,
            "uncertainties": uncertainties,
            "evidence": evidence_refs,
            "confidence": confidence,
            "limitations": limitations,
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "provider": self.provider,
            "name": self.name,
            "version": self.version,
            "type": "deterministic_grounded",
            "generative": False,
        }


def _first_sentence(text: str) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", clean)
    return parts[0][:400]


class OpenAICompatibleLLM(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None,
        model: str,
        version: str,
        timeout: float = 90.0,
        json_mode: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.name = model
        self.version = version
        self.provider = "openai_compatible"
        self.timeout = timeout
        self.json_mode = json_mode

    def generate(self, *, system_prompt: str, user_prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise CapabilityUnavailableError(f"LLM '{self.name}' has no base URL configured")
        import json

        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload: dict[str, Any] = {
            "model": self.name,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt + "\n\nSTRUCTURED_CONTEXT:\n" + json.dumps(context, default=str)},
            ],
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            raise CapabilityUnavailableError(f"LLM request failed: {exc}") from exc
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise CapabilityUnavailableError("LLM did not return valid JSON contract") from exc
        if not isinstance(parsed, dict):
            raise CapabilityUnavailableError("LLM response is not a JSON object")
        parsed.setdefault("answer", "")
        parsed.setdefault("observed_facts", [])
        parsed.setdefault("derived_findings", [])
        parsed.setdefault("interpretations", [])
        parsed.setdefault("uncertainties", [])
        parsed.setdefault("evidence", [])
        parsed.setdefault("confidence", "low")
        parsed.setdefault("limitations", [])
        return parsed

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.base_url else "unconfigured",
            "provider": self.provider,
            "name": self.name,
            "version": self.version,
            "type": "openai_compatible",
            "base_url": self.base_url or None,
        }
