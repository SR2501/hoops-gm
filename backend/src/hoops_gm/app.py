"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from hoops_gm import __version__
from hoops_gm.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from hoops_gm.api.routes import api_v1_router, ops_router
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.core.config import Settings, get_settings
from hoops_gm.core.logging import configure_logging, get_logger
from hoops_gm.db.session import Database

log = get_logger(__name__)


def _current_request_id() -> str | None:
    bound = structlog.contextvars.get_contextvars().get("request_id")
    return bound if isinstance(bound, str) else None


def _error_response(status_code: int, error: str, detail: str) -> JSONResponse:
    payload = ErrorResponse(error=error, detail=detail, request_id=_current_request_id())
    headers = {}
    if payload.request_id:
        headers[REQUEST_ID_HEADER] = payload.request_id
    return JSONResponse(status_code=status_code, content=payload.model_dump(), headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Settings and the database live on ``app.state`` rather than in module
    globals, so a test can build an app against a throwaway database without
    unpicking import order.
    """
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database.from_settings(settings)
        app.state.database = database

        log.info(
            "app.startup",
            service=settings.app_name,
            version=__version__,
            environment=settings.environment,
            host=settings.host,
            port=settings.port,
            dialect=database.engine.dialect.name,
        )
        if not settings.is_loopback_bind:
            # Not fatal — a container has to bind 0.0.0.0 for a published port
            # to reach it — but it must never happen quietly. See ADR-001 and
            # the comment on the port mapping in docker-compose.yml.
            log.warning(
                "app.non_loopback_bind",
                host=settings.host,
                adr="ADR-001",
                message=(
                    "binding a non-loopback address exposes the service, and it "
                    "holds Fantrax credentials and personal-use projection data"
                ),
            )

        try:
            yield
        finally:
            database.dispose()
            log.info("app.shutdown")

    app = FastAPI(
        title="hoops-gm",
        version=__version__,
        summary="Fantasy basketball league management — local-first backend",
        lifespan=lifespan,
        # Local-first: docs are for the owner and cost nothing to leave on.
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Routes may provide a stable machine-readable code without creating a
        # second error envelope. The header is consumed here, never returned.
        error = (exc.headers or {}).get("X-Bridge-Error", "http_error")
        return _error_response(exc.status_code, error, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(422, "validation_error", str(exc.errors()))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        """Keep 500s inside the error contract.

        Without this, Starlette returns a plain-text "Internal Server Error"
        with no ``X-Request-ID`` — correlation is broken for precisely the
        failures it exists to trace. The detail is the exception *type*, never
        its message: an exception string can carry a connection URL, and a
        connection URL can carry a password.
        """
        log.error("request.unhandled_exception", error_type=type(exc).__name__)
        return _error_response(
            500,
            "internal_error",
            f"Unhandled {type(exc).__name__}. See the server log for this request id.",
        )

    app.include_router(ops_router)
    app.include_router(api_v1_router)

    return app
