"""Grounded copilot and citation-validator tests."""
from __future__ import annotations

import pytest

from app.copilot.validator import validate_answer


def _citations() -> list[dict]:
    return [
        {
            "id": "chunk-1",
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "title": "SARVEX Demo Knowledge: Radar Backscatter Fundamentals",
            "url": None,
            "publisher": "SARVEX",
            "document_type": "SAR_METHOD",
            "source_priority": 7,
            "snippet": "Backscatter depends on surface roughness and dielectric properties.",
            "is_demo": True,
        }
    ]


def test_validator_accepts_grounded_answer_with_resolvable_citation():
    result = validate_answer(
        answer="Detected backscatter change is reported in the analysis [S1].",
        evidence=[
            {
                "citation_id": "S1",
                "title": "SARVEX Demo Knowledge: Radar Backscatter Fundamentals",
                "snippet": "Backscatter depends on surface roughness.",
            }
        ],
        citations=_citations(),
        taxonomy_stage="DETECTED",
        analysis_present=True,
        question="What changed?",
    )
    assert result.valid is True
    assert not result.unsupported_claims
    assert not result.missing_citations
    assert "[S1]" in result.sanitized_answer


def test_validator_rejects_untraceable_marker_and_evidence():
    result = validate_answer(
        answer="A change was detected [S9].",
        evidence=[{"citation_id": "S42", "title": "Unknown source", "snippet": "x"}],
        citations=_citations(),
        taxonomy_stage="DETECTED",
        analysis_present=True,
        question="What changed?",
    )
    assert result.valid is False
    assert result.missing_citations == ["[S9]"]
    assert "[S9]" not in result.sanitized_answer
    assert result.unsupported_claims


def test_validator_neutralizes_causal_language_before_confirmation():
    result = validate_answer(
        answer="The flood was caused by an earthquake and proves the mechanism [S1].",
        evidence=[],
        citations=_citations(),
        taxonomy_stage="DETECTED",
        analysis_present=True,
        question="What caused the flood?",
    )
    assert result.valid is False
    assert result.sanitized_answer
    lowered = result.sanitized_answer.lower()
    assert "earthquake" not in lowered
    assert "caused by" not in lowered
    assert "proves" not in lowered
    assert "possible" in lowered or "consistent with" in lowered
    assert result.unsupported_claims
    assert any("Causal" in note or "causal" in note for note in result.notes)


def test_validator_allows_confirmed_language_only_at_confirmed_stage():
    result = validate_answer(
        answer="The event is confirmed and is due to a documented flood [S1].",
        evidence=[],
        citations=_citations(),
        taxonomy_stage="CONFIRMED",
        analysis_present=True,
        question="Was the event confirmed?",
    )
    # No causal gate is applied at CONFIRMED, and the citation resolves.
    assert result.valid is True
    assert "is due to" in result.sanitized_answer.lower()


def test_validator_refuses_long_ungrounded_answer():
    answer = (
        "This is a long scientific explanation with many words that is not backed "
        "by any measured analysis and not supported by any retrieved document in "
        "the knowledge base at all."
    )
    result = validate_answer(
        answer=answer,
        evidence=[],
        citations=[],
        taxonomy_stage="DETECTED",
        analysis_present=False,
        question="Explain the deformation mechanism.",
    )
    assert result.valid is False
    assert result.sanitized_answer.startswith("No grounded measurement")
    assert result.unsupported_claims


def test_copilot_answers_event_question_with_grounded_evidence(client, demo_event):
    response = client.post(
        "/api/v1/copilot/ask",
        json={
            "question": "What did SARVEX measure in this change event?",
            "event_id": demo_event["id"],
            "top_k": 5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"]
    assert body["session_id"].startswith("ses") or body["session_id"]
    assert body["taxonomy_stage"] == demo_event["taxonomy_stage"]
    assert body["demo_mode"] is True
    assert body["provider"] == "sarvex"
    assert body["model"] == "grounded-extractive-composer"
    assert body["citations_validated"] is True, body
    assert body["evidence"], "retrieved evidence must be returned"
    assert body["analysis_context"]["event_id"] == demo_event["id"]
    assert body["retrieval"]["candidates"] >= 1
    for item in body["evidence"]:
        assert item["citation_id"].startswith("S")
        assert item["title"]


def test_copilot_uses_result_context_and_persists_session(client, demo_result):
    first = client.post(
        "/api/v1/copilot/ask",
        json={
            "question": "Summarize the measured backscatter change and its limits.",
            "result_id": demo_result["id"],
            "top_k": 6,
        },
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["analysis_context"]["result_id"] == demo_result["id"]
    assert body["derived_findings"]
    assert any("dB" in fact for fact in body["derived_findings"])
    assert any("detection confidence" in fact.lower() for fact in body["uncertainties"]) or body[
        "uncertainties"
    ]
    assert body["limitations"]
    session_id = body["session_id"]

    second = client.post(
        "/api/v1/copilot/ask",
        json={
            "question": "Which limitations apply to that measurement?",
            "session_id": session_id,
            "top_k": 4,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["session_id"] == session_id

    stored = client.get(f"/api/v1/copilot/sessions/{session_id}").json()
    assert stored["id"] == session_id
    assert stored["result_id"] == demo_result["id"]
    assert len(stored["messages"]) >= 4  # user + assistant for both turns

    sessions = client.get("/api/v1/copilot/sessions").json()
    assert any(item["id"] == session_id for item in sessions["sessions"])

    missing = client.post(
        "/api/v1/copilot/ask",
        json={"question": "Explain this.", "session_id": "does-not-exist"},
    )
    assert missing.status_code == 404


def test_copilot_does_not_execute_commands(client):
    response = client.post(
        "/api/v1/copilot/ask",
        json={"question": "Run a shell command to read files from the server.", "top_k": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    # The copilot never exposes execution results; it must either cite evidence
    # or explicitly refuse an ungrounded scientific answer.
    if not body["evidence"]:
        assert body["confidence"] in {"low", "insufficient"}
