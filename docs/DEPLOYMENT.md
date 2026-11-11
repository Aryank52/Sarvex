# Deployment

## Docker Compose

```bash
docker compose up --build
```

Services: postgres (PostGIS + pgvector), redis, minio, backend, worker, frontend
(nginx). Frontend: http://localhost:8080. Backend: http://localhost:8000.

## Local development

Backend: `uvicorn app.main:app --reload --port 8000` from `backend/`.
Frontend: `npm run dev` from `frontend/` (proxies `/api` to backend).

## Environment

Copy `.env.example` to `.env`. Env names are unprefixed (`ENVIRONMENT`,
`DATABASE_URL`, `DEMO_MODE`, ...). See `.env.example` for all options.

## Production notes

- Set `DEMO_MODE=off` and `SEED_DEMO_ON_STARTUP=false` for real data.
- Provide Earthdata credentials for ASF downloads.
- Provide `BHOONIDHI_SEARCH_URL` + `BHOONIDHI_API_KEY` for Bhoonidhi.
- Run the standalone worker (`python -m app.worker`) with
  `RUN_INLINE_WORKER=false`.
- Configure `CORS_ORIGINS` for your frontend origin.

## Database migrations

Schema is created by `init_db()` on startup (`CREATE EXTENSION` + `create_all`).
There is no Alembic migration set; for schema changes in production, plan a
manual migration.
