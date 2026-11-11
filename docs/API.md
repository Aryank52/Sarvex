# API

Base path: `/api/v1`. OpenAPI: `/api/openapi.json`. Swagger: `/api/docs`.

## Endpoint groups

- `/health`, `/capabilities` — status and capability map
- `/aois` — AOI CRUD
- `/datasets`, `/observations`, `/products` — catalog
- `/catalog/search`, `/catalog/ingest`, `/catalog/upload` — discovery and ingestion
- `/analyses` — job queue, run, cancel, logs
- `/results` — results, features, layers (PNG/GeoTIFF), timeseries
- `/events` — events, geojson, stats, status review, confirm, evidence, context, exposures
- `/copilot/ask`, `/copilot/sessions` — grounded Q&A
- `/knowledge/*` — RAG search, ingest, stats, documents
- `/models` — registry, summary, reload, runs
- `/reports` — generate, list, get, download
- `/context/*` — context layers

## Error shape

```json
{ "code": "...", "message": "...", "detail": {...}, "correlation_id": "..." }
```

## Demo mode

`DEMO MODE` banner and `is_demo` flags are present at every level. Demo events
cannot be confirmed.
