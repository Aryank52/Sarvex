"""NLP intent parsing endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import rate_limit
from app.nlp.intent import parse_intent

router = APIRouter(tags=["nlp"], dependencies=[Depends(rate_limit)])


@router.post("/nlp/parse")
def parse(payload: dict[str, Any]) -> dict[str, Any]:
    query = str(payload.get("query") or payload.get("question") or "")
    intent = parse_intent(query)
    return {"query": query, "intent": intent.to_dict()}
