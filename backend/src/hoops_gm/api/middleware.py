"""Request context middleware.

Every request gets an id, bound into the logging context so that all log lines
emitted while handling it carry it, and returned as ``X-Request-ID`` so a
frontend or userscript bug report can be traced to server-side lines.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from hoops_gm.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"

log = get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a request id and log one structured line per request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request.failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            # Deliberately no clear_contextvars() here. The exception is about
            # to propagate to the application's 500 handler, which reads
            # request_id off the logging context to put it in the response
            # body and header. Clearing first leaves that handler with None —
            # losing correlation for exactly the errors it exists to trace.
            # The next request clears at the top of dispatch anyway.
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        log.info(
            "request.completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        structlog.contextvars.clear_contextvars()
        return response
