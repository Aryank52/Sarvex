"""SARVEX backend package.

The product is organized as a layered scientific system:

connectors -> products/adapters -> storage manifests -> processing -> events
-> evidence/RAG -> copilot explanations -> reports.

The LLM layer never becomes the source of truth: measurements and provenance
are persisted before any explanation is generated.
"""
from __future__ import annotations

import os
from pathlib import Path


def _repair_proj_environment() -> None:
    """Ignore an incompatible external PROJ data directory.

    A machine-wide ``PROJ_LIB`` (often left by a PostgreSQL/PostGIS install)
    can point at a ``proj.db`` whose layout is older than the bundled GDAL/PROJ
    expects. That makes every EPSG lookup fail with a confusing CRS error. When
    the referenced database is incompatible we remove the process-local
    overrides so rasterio/pyproj use their own bundled, matching data.
    """
    for variable in ("PROJ_LIB", "PROJ_DATA"):
        raw = os.environ.get(variable)
        if not raw:
            continue
        database = Path(raw) / "proj.db"
        if not database.is_file():
            os.environ.pop(variable, None)
            continue
        try:
            import sqlite3

            connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
            try:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key='DATABASE.LAYOUT.VERSION.MINOR'"
                ).fetchone()
            finally:
                connection.close()
            minor = int(row[0]) if row and row[0] is not None else 0
        except Exception:  # noqa: BLE001 - unreadable database is unusable
            minor = 0
        if minor < 6:
            os.environ.pop(variable, None)
            # A GDAL data directory shipped with the same old stack is equally
            # suspect; GDAL falls back to its bundled data when unset.
            os.environ.pop("GDAL_DATA", None)


_repair_proj_environment()

__version__ = "1.0.0"
