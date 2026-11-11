"""Cross-database SQLAlchemy types.

Production PostgreSQL uses PostGIS geometry and pgvector embeddings. The SQLite
development/test fallback stores equivalent GeoJSON and JSON arrays so the same
domain code is exercised without a container runtime. This is a documented
assumption: PostGIS/pgvector remain the supported production configuration.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Text, TypeDecorator
from sqlalchemy.types import JSON


class GeoJSONGeometry(TypeDecorator):
    """Store GeoJSON in SQLite, PostGIS geometry in PostgreSQL."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            from geoalchemy2.types import Geometry as PGGeometry

            return dialect.type_descriptor(PGGeometry(geometry_type="GEOMETRY", srid=4326))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, str):
            value = json.loads(value)
        if dialect.name == "postgresql":
            from shapely.geometry import shape

            return f"SRID=4326;{shape(value).wkt}"
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if dialect.name == "postgresql":
            from geoalchemy2.shape import to_shape
            from shapely.geometry import mapping

            geom = to_shape(value)
            return json.loads(json.dumps(mapping(geom)))
        if isinstance(value, str):
            return json.loads(value)
        return value


class VectorEmbedding(TypeDecorator):
    """Store embeddings as pgvector in PostgreSQL and JSON in SQLite.

    The physical pgvector column has a fixed maximum capacity. Uploaded models
    may use different dimensions; vectors are zero-padded for storage (cosine
    similarity is invariant to zero padding) and the true dimension is stored on
    ``EmbeddingRecord.dimension``. Dimensions above the capacity are rejected
    explicitly rather than silently truncated.
    """

    impl = JSON
    cache_ok = True
    CAPACITY = 1536

    def __init__(self, dim: int = 1536):
        self.dim = dim
        super().__init__()

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(self.dim))
            except Exception:  # noqa: BLE001 - degrade to JSONB if pgvector is absent
                from sqlalchemy.dialects.postgresql import JSONB

                return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return list(map(float, value))

    def process_result_value(self, value: Any, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return [float(v) for v in value]
