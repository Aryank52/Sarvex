"""Scientific evidence taxonomy.

SARVEX never collapses these stages. A detected surface change is not an
earthquake; a classification is not confirmation. The stage is persisted on
events and copied into every copilot response.
"""
from __future__ import annotations

from enum import Enum


class EvidenceStage(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    DETECTED = "DETECTED"
    CLASSIFIED = "CLASSIFIED"
    CONTEXTUALIZED = "CONTEXTUALIZED"
    HYPOTHESIZED = "HYPOTHESIZED"
    CONFIRMED = "CONFIRMED"


STAGE_RANK: dict[EvidenceStage, int] = {
    EvidenceStage.OBSERVED: 1,
    EvidenceStage.DERIVED: 2,
    EvidenceStage.DETECTED: 3,
    EvidenceStage.CLASSIFIED: 4,
    EvidenceStage.CONTEXTUALIZED: 5,
    EvidenceStage.HYPOTHESIZED: 6,
    EvidenceStage.CONFIRMED: 7,
}

STAGE_DESCRIPTIONS = {
    EvidenceStage.OBSERVED: "Measured directly in the SAR product.",
    EvidenceStage.DERIVED: "Computed deterministically from observations.",
    EvidenceStage.DETECTED: "Identified by an explicit algorithm; not a cause.",
    EvidenceStage.CLASSIFIED: "Assigned to a candidate category by a stated method.",
    EvidenceStage.CONTEXTUALIZED: "Spatially correlated with independent context layers.",
    EvidenceStage.HYPOTHESIZED: "A possible explanation requiring independent validation.",
    EvidenceStage.CONFIRMED: "Supported by authoritative external evidence.",
}


class EventType(str, Enum):
    SURFACE_DISTURBANCE = "SURFACE_DISTURBANCE"
    GROUND_DEFORMATION = "GROUND_DEFORMATION"
    FLOOD_WATER_CHANGE = "FLOOD_WATER_CHANGE"
    WETLAND_CHANGE = "WETLAND_CHANGE"
    AGRICULTURAL_CHANGE = "AGRICULTURAL_CHANGE"
    VEGETATION_CHANGE = "VEGETATION_CHANGE"
    CRYOSPHERE_CHANGE = "CRYOSPHERE_CHANGE"
    STRUCTURAL_CHANGE = "STRUCTURAL_CHANGE"
    UNCLASSIFIED_CHANGE = "UNCLASSIFIED_CHANGE"


class EventStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORROBORATED = "CORROBORATED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


# Categories are not causal explanations. Structural change is only assigned
# when the analysis supports a structural measurement, never from raw backscatter.
DEFORMATION_EVENT_TYPES = {EventType.GROUND_DEFORMATION}
SURFACE_EVENT_TYPES = {
    EventType.SURFACE_DISTURBANCE,
    EventType.FLOOD_WATER_CHANGE,
    EventType.WETLAND_CHANGE,
    EventType.VEGETATION_CHANGE,
    EventType.AGRICULTURAL_CHANGE,
    EventType.CRYOSPHERE_CHANGE,
    EventType.UNCLASSIFIED_CHANGE,
}


def can_promote(current: EvidenceStage, proposed: EvidenceStage) -> bool:
    """Confirming a hypothesis requires going beyond the algorithm itself."""
    return STAGE_RANK[proposed] > STAGE_RANK[current]


CAUSAL_TERMS = (
    "earthquake",
    "landslide",
    "eruption",
    "caused by",
    "due to the earthquake",
    "definitely",
    "certainly",
    "proves",
)
