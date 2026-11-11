"""Multimodal (vision-language) adapter, capability-gated.

Scientific numbers always come from structured results; multimodal reasoning is
used only for explanation/interpretation of generated visualizations.
"""
from __future__ import annotations

from typing import Any

from app.core.errors import CapabilityUnavailableError


class MultimodalExplainer:
    def __init__(self, llm_provider: Any | None = None) -> None:
        self.llm = llm_provider

    def available(self) -> bool:
        if self.llm is None:
            return False
        health = getattr(self.llm, "health", lambda: {})()
        return bool(health.get("multimodal") or health.get("vision"))

    def explain_visuals(
        self,
        *,
        structured_result: dict[str, Any],
        image_descriptions: list[str],
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "available": False,
                "reason": "No multimodal LLM configured. Scientific numbers come from structured results.",
            }
        # Delegate to provider if it supports multimodal; otherwise unavailable.
        return {
            "available": False,
            "reason": "Multimodal provider does not expose a vision endpoint in this configuration.",
            "structured_result_keys": list(structured_result.keys()),
            "image_descriptions": image_descriptions,
        }
