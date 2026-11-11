# RAG architecture

## Ingestion

Documents are registered with metadata (author, publisher, date, URL, type,
topic, mission, product type, licence, source priority, demo flag). They are
chunked and embedded. Demo documents use `is_demo=true` and
`source_priority=7`; official documents outrank them.

## Retrieval

Hybrid search combines lexical and vector scores with a configurable
`keyword_weight`, then reranks. Top-k passages are returned with document,
section and source priority. Snippets retain citations.

## Grounded copilot

1. Retrieve passages.
2. Assemble bounded context via read-only tools (measured statistics, stage,
   uncertainty, events).
3. Compose an explanation with the configured LLM provider.
4. Validate every `[S#]` citation resolves; neutralise unsupported causal
   claims.

The model receives no filesystem, shell or network access. Sessions are
persisted with messages and context ids.

## Knowledge stats

`/api/v1/knowledge/stats` reports documents, chunks, embeddings, embedding model,
reranker model, LLM model and demo document count.
