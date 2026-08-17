"""Health endpoints.

Two of them, because they answer different questions. ``/health`` is liveness
and must never touch a dependency — it is what the container healthcheck and
the userscript's connectivity probe use, and a health endpoint that fails when
the database is busy causes more outages than it detects.
``/health/ready`` is the one that actually checks the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from hoops_gm import __version__
from hoops_gm.api.deps import DatabaseDep, SettingsDep
from hoops_gm.api.schemas import HealthResponse, ReadinessResponse
from hoops_gm.core.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.environment,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe — verifies database connectivity",
)
def readiness(database: DatabaseDep, response: Response) -> ReadinessResponse:
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # The exception text can contain the connection URL, which can contain
        # a password. Log the type, return the type, never the message.
        log.error("readiness.database_unavailable", error_type=type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="degraded",
            database="unavailable",
            detail=f"database check failed: {type(exc).__name__}",
        )

    return ReadinessResponse(status="ok", database="ok")
