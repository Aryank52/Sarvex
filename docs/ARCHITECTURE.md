# Architecture

## Layers

```
React/Vite frontend (MapLibre)
        |
        | /api/v1
        v
FastAPI (routers, middleware, error handlers)
        |
        +-- Services: jobs, demo seed, reports, RAG, copilot
        +-- Processing engine (processors + artifacts)
        +-- Connectors (ASF, Bhoonidhi, STAC, local, demo)
        +-- Model registry + providers
        v
PostgreSQL/PostGIS/pgvector (or SQLite fallback) + object storage (local/S3/MinIO) + Redis
```

## Domain model

Core tables: `aois`, `datasets`, `observations`, `products`, `processing_jobs`,
`processing_runs`, `analysis_results`, `sar_features`, `change_events`,
`event_observation_links`, `event_evidence_links`, `event_context_links`,
`event_exposures`, `infrastructure_assets`, `context_layers`, `geospatial_contexts`,
`time_series`, `evidence_items`, `copilot_sessions`, `copilot_messages`,
`rag_documents`, `rag_chunks`, `rag_embeddings`, `model_runs`, `models`.

Every result links to a run; every run records algorithm, version, parameters,
inputs, CRS, units and provenance. Jobs carry logs and progress.

## Job lifecycle

`QUEUED -> CLAIMED -> VALIDATING -> DOWNLOADING -> PREPROCESSING -> PROCESSING ->
ANALYZING -> POSTPROCESSING -> COMPLETED` (or `FAILED` / `CANCELLED`).

- Dev/demo: `RUN_INLINE_WORKER=true` runs jobs in a daemon thread after creation.
- Production: standalone worker (`python -m app.worker`) claims jobs atomically
  (`QUEUED -> CLAIMED`) so multiple workers do not double-process.
- Stale claims are requeued after `WORKER_STALE_MINUTES`.

## Processing

Processors are registered by analysis type: backscatter, change_detection,
deformation, polarimetric, offsets, timeseries. Each validates inputs, writes
GeoTIFF/PNG artifacts to object storage, persists a result with statistics and
layer metadata, and emits change events. Artifacts carry title, units, method,
source, product ids, dates, bbox, CRS, legend and image coordinates.

## Storage

- Database: Postgres/PostGIS/pgvector in production; SQLite fallback for dev/test.
- Object storage: local filesystem or S3-compatible (MinIO). URIs are stored;
  PNG/GeoTIFF are served via `/api/v1/results/{id}/layers/{name}`.
- Redis: reserved for caching/queue coordination; the job queue is DB-backed.

## Model layer

`backend/config/models.yaml` declares models by category (embedding, reranker,
llm, change_detection). `ModelRegistry` resolves providers, health and capability
summaries. No model name is hard-coded in business logic. Offline-safe defaults
are explicitly marked degraded.

## RAG and copilot

Documents are chunked and embedded (zero-padded to storage capacity). Hybrid
retrieval combines lexical and vector scores, reranks, and assembles bounded
context. The copilot uses read-only tools for measured facts and validates every
`[S#]` citation before returning. Unsupported claims are neutralised.

## Frontend

React 18 + Vite + TypeScript. MapLibre renders OSM raster basemap plus event
GeoJSON and georeferenced PNG overlays. No UI framework; custom CSS design
system. Dev proxy `/api -> http://localhost:8000`.
