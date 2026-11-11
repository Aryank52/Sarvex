# SARVEX — NISAR Surface-Change Intelligence Platform

SARVEX turns NISAR-family synthetic-aperture radar (SAR) products into
measured surface-change intelligence. Every measurement carries units,
uncertainty and provenance. Explanations are evidence-grounded and never assert
a cause. Detection is never automatically promoted to confirmation.

Built for the NASA Space Apps 2026 challenge "Dancing with the SARs".

## Highlights

- Eight NISAR product adapters (RSLC, GSLC, GCOV, RIFG, RUNW, GUNW, ROFF, GOFF) plus
  ISRO Bhoonidhi, STAC, local upload and a labelled demo connector.
- Deterministic scientific baselines: temporal median, robust MAD z-score,
  CUSUM, Theil-Sen trend, phase-correlation offsets, InSAR LOS displacement.
- Model registry with provider abstraction; offline-safe defaults that are
  explicitly marked degraded rather than silently substituted.
- Hybrid RAG (lexical + vector, reranked) with grounded copilot and citation
  validation.
- Immutable provenance, async jobs with defined states, event taxonomy from
  OBSERVED to CONFIRMED, and an independent-evidence confirmation gate.
- Explicit DEMO MODE with synthetic, labelled fixtures; demo data is never
  presented as NASA/ISRO observations.
- FastAPI + Postgres/PostGIS/pgvector/Redis/MinIO in production; SQLite/local
  fallback for development and tests.
- React/Vite/TypeScript frontend with a MapLibre mission-control console.
- Docker Compose deployment and a comprehensive test suite (53 tests).

## Quick start (local, no Docker)

Backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e .
copy ..\.env.example .env   # then edit
python -m app.worker --once  # optional
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

## Quick start (Docker Compose)

```bash
docker compose up --build
```

Frontend: http://localhost:8080  Backend: http://localhost:8000  API docs: http://localhost:8000/api/docs

## Tests

```bash
cd backend
$env:TEMP='E:\PROJECTS\Sarvex\.tmp'; $env:TMP=$env:TEMP
python -m pytest tests -q
```

Expected: 53 passed. Point `TEMP`/`TMP` at an E: drive path; the C: drive has limited free space.

## Documentation

See `docs/`:

- `ARCHITECTURE.md` — system design and data flow
- `DATA_SOURCES.md` — connectors and credential policy
- `SAR_PROCESSING.md` — algorithms and units
- `ML_ARCHITECTURE.md` — model registry and providers
- `RAG_ARCHITECTURE.md` — retrieval and grounded copilot
- `API.md` — endpoint overview
- `DEPLOYMENT.md` — Docker and local deployment
- `DEMO_MODE.md` — synthetic fixture policy
- `MODEL_REGISTRY.md` — configuring models
- `SCIENTIFIC_GUARDRAILS.md` — evidence discipline
- `TROUBLESHOOTING.md` — common issues

## Licence and attribution

SARVEX is a software platform. It does not redistribute NASA or ISRO data.
All third-party data retains its original licence and attribution, carried in
product manifests and reports. Demo fixtures are SARVEX-authored synthetics.
