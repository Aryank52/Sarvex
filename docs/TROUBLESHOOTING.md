# Troubleshooting

## C: drive full / SQLite disk I/O error

Point `TEMP` and `TMP` at an E: drive path before running tests:

```powershell
$env:TEMP='E:\PROJECTS\Sarvex\.tmp'; $env:TMP=$env:TEMP
```

## Host PROJ incompatibility

`app/__init__.py` removes bad global `PROJ_LIB`/`GDAL_DATA` overrides when the
PROJ layout minor is < 6. If rasterio still fails, set `PROJ_LIB` to a valid
proj.db directory.

## Docker unavailable

Compose/PostGIS/Redis/MinIO runtime verification cannot be performed locally
without Docker. Use SQLite/local mode (`DATABASE_URL` empty,
`OBJECT_STORAGE_BACKEND=local`) and note the gap.

## Bhoonidhi unconfigured

Set `BHOONIDHI_SEARCH_URL` and `BHOONIDHI_API_KEY`. Until then the connector
reports unconfigured; no fabricated results.

## ASF downloads fail

Authenticated downloads need Earthdata credentials
(`NASA_EARTHDATA_USERNAME`/`PASSWORD`/`TOKEN`). Public search works without them.

## ISCE3 missing

Install ISCE3 and ensure it is importable; otherwise SARVEX uses deterministic
baselines and reports adapter status.

## Frontend cannot reach API

In dev, Vite proxies `/api` to `http://localhost:8000`. Set
`VITE_API_BASE_URL` for a different origin. In production, nginx proxies `/api/`.
