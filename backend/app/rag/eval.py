"""RAG evaluation helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.rag.retrieval import retrieve


def evaluate_retrieval(
    session: Session,
    questions: list[dict[str, Any]],
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Evaluate retrieval against a list of {query, expected_keywords} items."""
    results = []
    recalls = []
    for item in questions:
        query = item["query"]
        expected = [str(k).lower() for k in item.get("expected_keywords", [])]
        chunks, _meta = retrieve(session, query, top_k=top_k)
        text = " ".join(c.text.lower() for c in chunks)
        hits = sum(1 for k in expected if k in text)
        recall = hits / max(len(expected), 1) if expected else 1.0
        recalls.append(recall)
        results.append(
            {
                "query": query,
                "top_k": top_k,
                "retrieved": len(chunks),
                "expected_keywords": expected,
                "hits": hits,
                "recall": recall,
                "titles": [c.title for c in chunks],
            }
        )
    return {
        "n_questions": len(questions),
        "mean_recall": float(sum(recalls) / max(len(recalls), 1)),
        "results": results,
    }
