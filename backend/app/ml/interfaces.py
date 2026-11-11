"""Model interfaces and categories.

Business logic never names a concrete LLM/embedding/reranker. It asks the
registry for a category and receives a provider implementing these contracts.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelCategory(str, Enum):
    CHANGE_DETECTION = "change_detection"
    EVENT_CLASSIFICATION = "event_classifier"
    ANOMALY_DETECTION = "anomaly_detection"
    REGRESSION = "regression"
    SEGMENTATION = "segmentation"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    LLM = "llm"
    VISION_LANGUAGE = "vision_language"


@dataclass
class ModelSpec:
    category: str
    provider: str
    name: str
    version: str
    model_type: str = ""
    task: str | None = None
    framework: str | None = None
    artifact_uri: str | None = None
    dimension: int | None = None
    config: dict[str, Any] = field(default_factory=dict)
    is_default: bool = True

    def display_name(self) -> str:
        return f"{self.name}@{self.version}"


class EmbeddingProvider(ABC):
    name: str
    version: str
    dimension: int

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": self.name, "version": self.version, "dimension": self.dimension}


class RerankerProvider(ABC):
    name: str
    version: str

    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_k: int) -> list[tuple[int, float]]:
        ...

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": self.name, "version": self.version}


class LLMProvider(ABC):
    name: str
    version: str
    provider: str

    @abstractmethod
    def generate(self, *, system_prompt: str, user_prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """Return a dict matching the grounded copilot output contract."""
        ...

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": self.provider, "name": self.name, "version": self.version}


class ChangeDetector(ABC):
    """Required transparent/ML change detector interface."""

    name: str
    version: str

    @abstractmethod
    def fit(self, features: "Any", labels: "Any | None" = None) -> "ChangeDetector":
        ...

    @abstractmethod
    def predict(self, features: "Any") -> "Any":
        """Return a prediction array (same leading shape as features)."""
        ...

    @abstractmethod
    def score(self, features: "Any", labels: "Any") -> dict[str, float]:
        ...

    @abstractmethod
    def explain(self) -> dict[str, Any]:
        ...

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        ...


class GroundedAnswer(dict):
    """Marker type for the structured LLM output contract."""
