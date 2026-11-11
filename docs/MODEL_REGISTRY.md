# Model registry

## Configuration

Edit `backend/config/models.yaml`. Each entry declares category, name, provider,
version, task, framework, status, default flag, capabilities and health.

## Adding a model

1. Add an entry to `models.yaml`.
2. If a new provider is needed, implement the adapter in `app/ml/providers.py`.
3. Reload via `POST /api/v1/models/reload` or restart.
4. Verify with `GET /api/v1/models` and `/api/v1/health/models`.

## Secrets

Secrets are resolved from environment variables named in the registry
(`LLM_API_KEY`, `EMBEDDING_API_KEY`, `RERANKER_API_KEY`), never stored in YAML.

## Offline-safe defaults

Feature-hashing embeddings, lexical reranker and a deterministic grounded
composer work without network access and are marked degraded/semantically
limited.
