"""Shared request-origin guard for local-only surfaces (ADR-001).

Every route that must never answer a non-local caller — bridge pairing, the
userscript file itself — shares one definition of "local" rather than each
re-deriving its own notion of a loopback address.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def require_loopback_host(request: Request, *, error_code: str, detail: str) -> None:
    """Reject a request whose client address is not this machine.

    The ``environment == "test"`` escape hatch matches every other local-only
    route in this codebase: Starlette's ``TestClient`` reports a synthetic
    ``testclient`` host rather than a real loopback address, so without it
    every test would have to fake a socket peer just to reach the route.
    """
    host = request.client.host if request.client else None
    if host not in LOOPBACK_HOSTS and request.app.state.settings.environment != "test":
        raise HTTPException(
            status_code=403,
            detail=detail,
            headers={"X-Bridge-Error": error_code},
        )
