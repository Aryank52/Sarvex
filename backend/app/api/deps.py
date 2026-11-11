"""FastAPI dependencies: database sessions, rate limiting, correlation IDs."""
from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import RateLimitError
from app.core.ratelimit import RateLimiter
from app.db.session import get_session_factory

_limiter = RateLimiter(get_settings().rate_limit_per_minute)


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    settings = get_settings()
    if settings.environment == "test":
        return
    key = f"{client_key(request)}:{request.url.path}"
    if not _limiter.allow(key):
        raise RateLimitError(
            "Rate limit exceeded",
            detail={
                "limit_per_minute": settings.rate_limit_per_minute,
                "retry_after_seconds": 60,
            },
        )


def request_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")
