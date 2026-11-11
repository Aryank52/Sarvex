"""SQLAlchemy engine/session management."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.base import Base


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.resolved_database_url
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        from pathlib import Path

        db_path = url.replace("sqlite:///", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
    return engine


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(create_extensions: bool = True) -> None:
    """Create tables. In Postgres also ensure PostGIS/pgvector extensions exist."""
    settings = get_settings()
    engine = get_engine()
    if engine.dialect.name == "postgresql" and create_extensions:
        from sqlalchemy import text

        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception:  # noqa: BLE001 - optional for RAG JSON fallback
                pass
    # Import models so the metadata is populated.
    from app.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def reset_db() -> None:
    from app.db import models  # noqa: F401

    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())
