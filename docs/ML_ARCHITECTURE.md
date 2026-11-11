# ML architecture

## Model registry

`backend/config/models.yaml` declares models by category: embedding, reranker,
llm, change_detection. `ModelRegistry` resolves providers, health and capability
summaries. Business logic requests a capability, never a vendor name.

## Providers

- Embedding: configurable OpenAI-compatible or deterministic feature-hashing
  (offline-safe, marked semantically limited).
- Reranker: configurable or lexical fallback (marked degraded).
- LLM: configurable OpenAI-compatible or deterministic grounded composer.

## Guarantees

- No model is hard-coded in application logic.
- No silent truncation: vectors above the configured storage capacity (1536) are
  rejected; shorter vectors are zero-padded without changing cosine similarity.
- Degradation is visible in responses, health endpoint and UI.
- Models explain detections; they never confirm events or invent measurements.
- Model runs are recorded with purpose, model, version, status, latency and
  correlation id.
