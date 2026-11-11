"""Model registry: configuration-driven providers with DB synchronization.

Every model category resolves through ``config/models.yaml``. Supplied models
(LLM, embeddings, reranker, change detection, vision-language) are added there
and, if their wire protocol is new, as a provider adapter. No business logic
imports a concrete provider.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import CapabilityUnavailableError, ValidationError
from app.ml.interfaces import EmbeddingProvider, LLMProvider, ModelCategory, ModelSpec, RerankerProvider
from app.ml.providers import (
    DeterministicGroundedLLM,
    HashEmbeddingProvider,
    HTTPReranker,
    LexicalReranker,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLM,
)

logger = logging.getLogger("sarvex.models")

SUPPORTED_CATEGORIES = {c.value for c in ModelCategory}
EMBEDDING_STORAGE_CAPACITY = 1536


class ModelRegistry:
    """Loads, validates and instantiates configured models."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._specs: dict[str, list[ModelSpec]] = {}
        self._instances: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.config_path.exists():
            raise ValidationError(
                f"Model registry configuration not found: {self.config_path}",
                detail={"configured_path": str(self.config_path)},
            )
        with self.config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        models = raw.get("models") or {}
        if not isinstance(models, dict):
            raise ValidationError("models.yaml must contain a 'models' mapping")
        specs: dict[str, list[ModelSpec]] = {}
        for category, entries in models.items():
            if category not in SUPPORTED_CATEGORIES:
                logger.warning("Ignoring unknown model category '%s'", category)
                continue
            if not isinstance(entries, list):
                entries = [entries]
            parsed: list[ModelSpec] = []
            defaults = 0
            for entry in entries:
                spec = self._parse_spec(category, entry)
                defaults += 1 if spec.is_default else 0
                parsed.append(spec)
            if defaults > 1:
                raise ValidationError(f"Category '{category}' declares multiple default models")
            if parsed and defaults == 0:
                parsed[0].is_default = True
            specs[category] = parsed
        for category in SUPPORTED_CATEGORIES - set(specs):
            logger.info("Model category '%s' has no configured entry", category)
        self._specs = specs
        self._instances.clear()

    def _parse_spec(self, category: str, entry: dict[str, Any]) -> ModelSpec:
        if not isinstance(entry, dict):
            raise ValidationError(f"Model entry for '{category}' must be a mapping")
        for required in ("provider", "name", "version"):
            if not entry.get(required):
                raise ValidationError(f"Model entry in '{category}' is missing '{required}'")
        dimension = entry.get("dimension")
        if category == ModelCategory.EMBEDDING.value:
            if dimension is None:
                raise ValidationError(
                    f"Embedding model '{entry['name']}' requires an explicit dimension"
                )
            dimension = int(dimension)
            if dimension <= 0:
                raise ValidationError("Embedding dimension must be positive")
            if dimension > EMBEDDING_STORAGE_CAPACITY:
                raise ValidationError(
                    f"Embedding dimension {dimension} exceeds pgvector storage capacity "
                    f"{EMBEDDING_STORAGE_CAPACITY}. SARVEX rejects silent truncation; extend the "
                    "storage capacity in app/db/types.py and app/db/models.py deliberately.",
                    detail={"model": entry["name"], "capacity": EMBEDDING_STORAGE_CAPACITY},
                )
        return ModelSpec(
            category=category,
            provider=str(entry["provider"]),
            name=str(entry["name"]),
            version=str(entry["version"]),
            model_type=str(entry.get("type", "")),
            task=entry.get("task"),
            framework=entry.get("framework"),
            artifact_uri=entry.get("artifact_uri"),
            dimension=dimension,
            config=dict(entry.get("config") or {}),
            is_default=bool(entry.get("is_default", False)),
        )

    def reload(self) -> None:
        self._load()

    # ------------------------------------------------------------------
    # Specs / lookup
    # ------------------------------------------------------------------
    def specs(self, category: str) -> list[ModelSpec]:
        return list(self._specs.get(category, []))

    def all_specs(self) -> list[ModelSpec]:
        return [spec for specs in self._specs.values() for spec in specs]

    def default_spec(self, category: str) -> ModelSpec:
        specs = self._specs.get(category)
        if not specs:
            raise CapabilityUnavailableError(f"No model configured for category '{category}'")
        for spec in specs:
            if spec.is_default:
                return spec
        return specs[0]

    def get_spec(self, category: str, name: str | None = None) -> ModelSpec:
        if name is None:
            return self.default_spec(category)
        for spec in self._specs.get(category, []):
            if spec.name == name:
                return spec
        raise CapabilityUnavailableError(
            f"Model '{name}' is not configured for category '{category}'",
            detail={"available": [s.name for s in self._specs.get(category, [])]},
        )

    # ------------------------------------------------------------------
    # Credentials (environment indirection only)
    # ------------------------------------------------------------------
    @staticmethod
    def _env(spec: ModelSpec, key: str) -> str | None:
        env_name = spec.config.get(key)
        if not env_name:
            return None
        return os.getenv(str(env_name)) or None

    # ------------------------------------------------------------------
    # Provider factories
    # ------------------------------------------------------------------
    def embedding_provider(self, name: str | None = None) -> EmbeddingProvider:
        spec = self.get_spec(ModelCategory.EMBEDDING.value, name)
        cache_key = f"embedding:{spec.name}"
        if cache_key in self._instances:
            return self._instances[cache_key]
        model_type = spec.model_type
        if model_type in {"deterministic_feature_hashing", "hash"}:
            provider: EmbeddingProvider = HashEmbeddingProvider(
                dimension=int(spec.dimension or get_settings().embedding_dimension),
                name=spec.name,
                version=spec.version,
            )
        elif model_type == "openai_compatible":
            provider = OpenAICompatibleEmbeddingProvider(
                base_url=self._env(spec, "base_url_env"),
                api_key=self._env(spec, "api_key_env"),
                model=spec.name,
                version=spec.version,
                dimension=int(spec.dimension or 1536),
            )
        else:
            raise CapabilityUnavailableError(
                f"Embedding provider '{spec.provider}' has no registered adapter",
                detail={"model": spec.name, "type": model_type},
            )
        self._instances[cache_key] = provider
        return provider

    def reranker(self, name: str | None = None) -> RerankerProvider:
        spec = self.get_spec(ModelCategory.RERANKER.value, name)
        cache_key = f"reranker:{spec.name}"
        if cache_key in self._instances:
            return self._instances[cache_key]
        if spec.model_type in {"deterministic_lexical", "lexical"}:
            provider: RerankerProvider = LexicalReranker()
        elif spec.model_type == "http_rerank":
            provider = HTTPReranker(
                base_url=self._env(spec, "base_url_env"),
                api_key=self._env(spec, "api_key_env"),
                model=spec.name,
                version=spec.version,
            )
        else:
            raise CapabilityUnavailableError(
                f"Reranker provider '{spec.provider}' has no registered adapter",
                detail={"model": spec.name, "type": spec.model_type},
            )
        self._instances[cache_key] = provider
        return provider

    def llm(self, name: str | None = None) -> LLMProvider:
        spec = self.get_spec(ModelCategory.LLM.value, name)
        cache_key = f"llm:{spec.name}"
        if cache_key in self._instances:
            return self._instances[cache_key]
        if spec.model_type in {"deterministic_grounded", "grounded"}:
            provider: LLMProvider = DeterministicGroundedLLM()
        elif spec.model_type == "openai_compatible":
            provider = OpenAICompatibleLLM(
                base_url=self._env(spec, "base_url_env"),
                api_key=self._env(spec, "api_key_env"),
                model=spec.name,
                version=spec.version,
                json_mode=bool(spec.config.get("json_mode", True)),
            )
        else:
            raise CapabilityUnavailableError(
                f"LLM provider '{spec.provider}' has no registered adapter",
                detail={"model": spec.name, "type": spec.model_type},
            )
        self._instances[cache_key] = provider
        return provider

    def order_providers(self) -> list[LLMProvider]:
        """LLM providers in fallback order: default first, then alternatives."""
        default = self.default_spec(ModelCategory.LLM.value)
        ordered = [self.llm(default.name)]
        for spec in self.specs(ModelCategory.LLM.value):
            if spec.name != default.name:
                ordered.append(self.llm(spec.name))
        return ordered

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    def health(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for category in [c.value for c in ModelCategory]:
            for spec in self.specs(category):
                entry = {
                    "category": category,
                    "name": spec.name,
                    "provider": spec.provider,
                    "version": spec.version,
                    "task": spec.task,
                    "framework": spec.framework,
                    "is_default": spec.is_default,
                    "status": "configured",
                    "capabilities": {},
                }
                try:
                    if category == ModelCategory.EMBEDDING.value:
                        entry["capabilities"] = self.embedding_provider(spec.name).health()
                        entry["status"] = entry["capabilities"].get("status", "configured")
                    elif category == ModelCategory.RERANKER.value:
                        entry["capabilities"] = self.reranker(spec.name).health()
                        entry["status"] = entry["capabilities"].get("status", "configured")
                    elif category == ModelCategory.LLM.value:
                        entry["capabilities"] = self.llm(spec.name).health()
                        entry["status"] = entry["capabilities"].get("status", "configured")
                    elif category == ModelCategory.VISION_LANGUAGE.value:
                        entry["status"] = "disabled"
                        entry["capabilities"] = {"note": "No vision-language model configured"}
                    else:
                        entry["status"] = "configured"
                        entry["capabilities"] = {"type": spec.model_type or "deterministic"}
                except Exception as exc:  # noqa: BLE001 - health must not fail the endpoint
                    entry["status"] = "unavailable"
                    entry["capabilities"] = {"error": str(exc)}
                if spec.is_default and entry["status"] in {"unavailable", "unconfigured"}:
                    entry["status"] = "degraded"
                results.append(entry)
        return results

    def active_llm_health(self) -> dict[str, Any]:
        spec = self.default_spec(ModelCategory.LLM.value)
        try:
            health = self.llm(spec.name).health()
        except Exception as exc:  # noqa: BLE001
            return {"status": "unavailable", "error": str(exc), "name": spec.name}
        return {"name": spec.name, "version": spec.version, "provider": spec.provider, **health}

    # ------------------------------------------------------------------
    # Database synchronization
    # ------------------------------------------------------------------
    def sync_to_db(self, session: Session) -> int:
        """Upsert registry entries into the Model/ModelVersion tables."""
        from app.db.models import Model, ModelVersion

        count = 0
        for spec in self.all_specs():
            model = session.scalar(
                select(Model).where(
                    Model.category == spec.category,
                    Model.name == spec.name,
                    Model.version == spec.version,
                )
            )
            structured = dict(spec.config)
            structured["model_type"] = spec.model_type
            if spec.dimension:
                structured["dimension"] = spec.dimension
            if not model:
                model = Model(
                    category=spec.category,
                    name=spec.name,
                    provider=spec.provider,
                    version=spec.version,
                    artifact_uri=spec.artifact_uri,
                    task=spec.task,
                    framework=spec.framework,
                    config=structured,
                    status="ACTIVE",
                    is_default=spec.is_default,
                )
                session.add(model)
                session.flush()
            else:
                model.provider = spec.provider
                model.artifact_uri = spec.artifact_uri
                model.task = spec.task
                model.framework = spec.framework
                model.config = structured
                model.is_default = spec.is_default
            existing_version = session.scalar(
                select(ModelVersion).where(
                    ModelVersion.model_id == model.id,
                    ModelVersion.version == spec.version,
                )
            )
            if not existing_version:
                session.add(
                    ModelVersion(
                        model_id=model.id,
                        version=spec.version,
                        artifact_uri=spec.artifact_uri,
                        metrics={},
                        config=structured,
                    )
                )
            count += 1
        session.commit()
        return count

    def capability_summary(self) -> dict[str, Any]:
        llm = self.default_spec(ModelCategory.LLM.value)
        embedding = self.default_spec(ModelCategory.EMBEDDING.value)
        reranker = self.default_spec(ModelCategory.RERANKER.value)
        return {
            "llm": {"name": llm.name, "version": llm.version, "provider": llm.provider},
            "embedding": {
                "name": embedding.name,
                "version": embedding.version,
                "dimension": embedding.dimension,
            },
            "reranker": {"name": reranker.name, "version": reranker.version},
            "change_detection": {
                "name": self.default_spec(ModelCategory.CHANGE_DETECTION.value).name
            },
            "storage_capacity": EMBEDDING_STORAGE_CAPACITY,
        }


@lru_cache(maxsize=1)
def get_model_registry() -> ModelRegistry:
    return ModelRegistry(get_settings().models_config_file)


def reset_model_registry() -> None:
    get_model_registry.cache_clear()
