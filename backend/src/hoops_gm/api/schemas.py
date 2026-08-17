"""Response models for the API.

Kept explicit rather than derived from the ORM. The frontend's typed client
mirrors these by hand for now, and an implicit schema that changes when a
column is renamed is not a contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness. Answers "is the process up", nothing more."""

    status: Literal["ok"] = "ok"
    service: str = Field(description="Application name")
    version: str = Field(description="Backend package version")
    environment: str = Field(description="development, test or production")


class ReadinessResponse(BaseModel):
    """Readiness. Answers "can it serve a request that touches the database"."""

    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    #: Present only when the database check failed. Never contains a URL or
    #: credential — connection strings can carry secrets.
    detail: str | None = None


class ErrorResponse(BaseModel):
    """The stable error envelope. Every non-2xx response uses this shape."""

    error: str = Field(description="Machine-readable error code")
    detail: str = Field(description="Human-readable explanation")
    request_id: str | None = Field(
        default=None, description="Correlates with the X-Request-ID response header"
    )
