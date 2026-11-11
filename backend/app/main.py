"""SARVEX FastAPI application.

Startup is deliberately explicit and observable: database schema, model-registry
synchronization and (in demo/evaluation mode) synthetic fixture seeding happen
inside the lifespan handler. No data is fabricated at request time.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app import __version__
from app.api import api_router
from app.config import get_settings
from app.core.errors import SarvexError
from app.db.session import init_db, session_scope
from app.logging_config import configure_logging, correlation_id_var

logger = logging.getLogger("sarvex.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.structured_logs)
    logger.info(
        "Starting %s %s (environment=%s, demo_mode=%s, sqlite=%s)",
        settings.app_name,
        __version__,
        settings.environment,
        settings.demo_mode,
        settings.using_sqlite,
    )
    init_db()
    logger.info("Database schema ready")

    # Synchronize the declarative model registry into the database.
    try:
        from app.ml.registry import get_model_registry

        with session_scope() as session:
            count = get_model_registry().sync_to_db(session)
        logger.info("Model registry synchronized (%s entries)", count)
    except Exception:  # noqa: BLE001 - registry sync must not prevent startup
        logger.exception("Model registry synchronization failed")

    should_seed = settings.seed_demo_on_startup and settings.demo_mode != "off"
    if settings.environment == "production":
        # In production, demo fixtures are seeded only when demo mode is
        # explicitly forced on. Auto mode must never contaminate a real catalog.
        should_seed = should_seed and settings.demo_mode == "on"
    if should_seed:
        try:
            from app.services.demo import seed_demo

            with session_scope() as session:
                summary = seed_demo(session, include_analyses=True)
            logger.info(
                "Demo fixture seed: products=%s docs=%s analyses=%s",
                summary.get("products_ingested"),
                summary.get("documents"),
                len(summary.get("result_ids") or []),
            )
        except Exception:  # noqa: BLE001 - demo seeding is best-effort
            logger.exception("Demo fixture seeding failed")
    else:
        logger.info("Demo fixture seeding disabled")
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description=(
            "NISAR surface-change intelligence platform. Measurements come from SAR "
            "processing; explanations are evidence-grounded and never assert causes."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID", "X-SARVEX-Demo"],
    )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get("X-Correlation-ID") or uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        token = correlation_id_var.set(correlation_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        return response

    @app.exception_handler(SarvexError)
    async def sarvex_error_handler(request: Request, exc: SarvexError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Request validation failed",
                "detail": {"errors": exc.errors()},
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request error on %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "An unexpected error occurred. See server logs for the correlation ID.",
                "detail": {},
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", tags=["meta"])
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": __version__,
            "description": "NISAR surface-change intelligence platform",
            "docs": "/api/docs",
            "openapi": "/api/openapi.json",
            "api": "/api/v1",
            "data_mode": "DEMO" if settings.demo_mode == "on" else settings.demo_mode.upper(),
            "demo_notice": (
                "Demo mode uses synthetic SARVEX fixtures, never live NASA/ISRO data."
                if settings.demo_mode != "off"
                else None
            ),
        }

    @app.get("/health", tags=["meta"], include_in_schema=False)
    def liveness() -> dict:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
