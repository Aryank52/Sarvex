# Implementation gap map

## ALREADY WORKING

- FastAPI backend, routers, middleware, error handlers
- DB models, Postgres/PostGIS/pgvector + SQLite fallback
- Eight NISAR product adapters and connectors (ASF, Bhoonidhi, STAC, local, demo)
- Processing engine: backscatter, InSAR, polarimetric, offsets, timeseries
- ISCE3 adapter probe
- Job queue with states and standalone worker
- Model registry + providers (embedding, reranker, LLM)
- RAG ingestion + hybrid retrieval + reranker + copilot with citation validation
- Evidence/context/exposure engine
- Reports
- Demo seeding
- Frontend: dashboard, explore, catalog, analyses, events, copilot, models, reports, method
- Docker Compose, Dockerfiles, nginx
- 53 backend tests + frontend build

## NEEDS IMPLEMENTATION (this upgrade)

- SARFeatureEngine (feature groups A-G) — new
- SARVEX-HFCE deterministic + ML (XGBoost) — new
- Training dataset builder + spatial/temporal split + metrics + SHAP — new
- NLP intent parser (AnalysisIntent) — new
- LLM tool-calling orchestration + NVIDIA provider — extend
- Evidence graph persistence — extend
- Frontend: model insights, training dashboard, evidence panel, event detail enhancements — extend
- NISAR provider abstraction layer (NISARDataProvider) — extend connectors
- Product adapters formalised — extend
- Experiment/ablation infrastructure — new
- CLI tools — new
- Tests expanded to 100+

## NEEDS REAL DATA

- Live NISAR observations require Earthdata/Bhoonidhi credentials and network.
- Training labels require authoritative external event datasets; weak/pseudo labels
  are used honestly with label_type metadata.

## NEEDS MODEL INTEGRATION / TRAINING

- HFCE training on traceable features; metrics recorded with caveats.

## NEEDS VALIDATION

- Spatial/temporal holdout evaluation documented; no fabricated accuracy claims.
