"""Citation and claim validation for grounded scientific answers.

The validator enforces three hard rules:
1. Every evidence entry must correspond to a retrieved citation.
2. Citation markers in the answer must reference supplied evidence.
3. Causal or certainty language is rejected unless the taxonomy stage is
   CONFIRMED and an external evidence source supports it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CAUSAL_TERMS = (
    "earthquake",
    "landslide",
    "eruption",
    "tsunami",
    "caused by",
    "proves",
    "proven",
    "definitely",
    "certainly",
    "undoubtedly",
    "confirmed that",
    "is due to",
)

_CITATION_MARKER = re.compile(r"\[S(\d+)\]")


@dataclass
class ValidationResult:
    valid: bool
    unsupported_claims: list[str] = field(default_factory=list)
    missing_citations: list[str] = field(default_factory=list)
    sanitized_answer: str = ""
    notes: list[str] = field(default_factory=list)


def validate_answer(
    *,
    answer: str,
    evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    taxonomy_stage: str,
    analysis_present: bool,
    question: str,
) -> ValidationResult:
    unsupported: list[str] = []
    missing: list[str] = []
    notes: list[str] = []
    sanitized = answer or ""

    citation_ids = {str(c.get("id")) for c in citations}
    citation_titles = {str(c.get("title")) for c in citations}

    # 1. Evidence must be grounded in retrieved citations.
    for ev in evidence:
        ev_id = ev.get("citation_id") or ev.get("id")
        title = str(ev.get("title") or "")
        if ev_id and str(ev_id) in citation_ids:
            continue
        if title and title in citation_titles:
            continue
        note = f"Evidence entry '{title or ev_id}' was not present in the retrieved citation set"
        unsupported.append(note)
        notes.append(note)

    # 2. Citation markers must resolve.
    for marker in _CITATION_MARKER.findall(sanitized):
        if not 1 <= int(marker) <= len(citations):
            missing.append(f"[S{marker}]")
    if missing:
        for marker in set(missing):
            sanitized = sanitized.replace(marker, "")
        notes.append("Citation markers without a matching retrieved source were removed")

    # 3. Causal / certainty language gate.
    lower = sanitized.lower()
    if taxonomy_stage != "CONFIRMED":
        for term in CAUSAL_TERMS:
            if term in lower:
                unsupported.append(
                    f"Causal/certainty term '{term}' used at taxonomy stage {taxonomy_stage}"
                )
        if unsupported:
            sanitized = _neutralize(sanitized)
            notes.append(
                "Causal or certainty language was neutralized because the evidence stage is "
                f"{taxonomy_stage}, not CONFIRMED"
            )

    # 4. An ungrounded answer must not pretend to answer a scientific question.
    if not analysis_present and not citations and len(sanitized.split()) > 25:
        sanitized = (
            "No grounded measurement or retrieved scientific evidence is available for this "
            "question. SARVEX will not answer from an ungrounded model."
        )
        unsupported.append("Answer attempted without measurements or citations")
        notes.append("Ungrounded answer replaced with an explicit refusal")

    # 5. Requests for raw computation that the copilot cannot perform are not
    #    silently answered; this is enforced in the orchestrator before calling.
    if any(term in question.lower() for term in ("shell", "command line", "execute code", "read file")):
        notes.append("Copilot tools are read-only; execution requests are unsupported")

    return ValidationResult(
        valid=not unsupported and not missing,
        unsupported_claims=unsupported,
        missing_citations=missing,
        sanitized_answer=sanitized.strip(),
        notes=notes,
    )


def _neutralize(text: str) -> str:
    replacements = {
        "caused by": "spatially coincident with",
        "is due to": "is spatially coincident with",
        "proves": "is consistent with",
        "proven": "indicated",
        "definitely": "possibly",
        "certainly": "possibly",
        "undoubtedly": "possibly",
        "confirmed that": "suggests that",
        "earthquake": "possible seismic-related change (unconfirmed)",
        "landslide": "possible slope-related change (unconfirmed)",
        "eruption": "possible volcanic-related change (unconfirmed)",
        "tsunami": "possible tsunami-related change (unconfirmed)",
    }
    out = text
    for source, target in replacements.items():
        out = re.sub(re.escape(source), target, out, flags=re.IGNORECASE)
    return out
