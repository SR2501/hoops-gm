"""Serves the built userscript for Tampermonkey's one-time install and its
``@updateURL``/``@downloadURL`` auto-update checks.

Mounted unversioned, like ``/health``: this is a static-file surface, not a
JSON API contract, and Tampermonkey's update URL must stay stable regardless
of ``/api/v1`` evolving. Loopback-only (ADR-001) and, per ADR-010, never
serves anything containing a secret — the userscript obtains its bearer
secret only through the pairing handshake, never a build artifact, so these
bytes are safe to serve to any local caller that can already reach this port.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from hoops_gm.api.security import require_loopback_host

router = APIRouter(tags=["userscript"])

_BUILD_MISSING_DETAIL = (
    "The userscript build is missing. From the userscript/ directory, run "
    "`npm install` once and then `npm run build` to produce "
    "dist/hoops-gm.user.js, then reload this URL."
)


@router.get(
    "/bridge/userscript.user.js",
    summary="Serve the built userscript (install + @updateURL/@downloadURL target)",
)
def get_userscript(request: Request) -> Response:
    require_loopback_host(
        request,
        error_code="userscript_local_only",
        detail="The userscript is only served to the local machine.",
    )
    dist_path = request.app.state.settings.userscript_dist_path
    try:
        content = dist_path.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=404,
            detail=_BUILD_MISSING_DETAIL,
            headers={"X-Bridge-Error": "userscript_build_missing"},
        ) from exc

    return Response(
        content=content,
        media_type="text/javascript; charset=utf-8",
        # Tampermonkey's own update check already avoids the browser HTTP
        # cache, but an intermediate cache remembering a stale build would
        # quietly defeat auto-update entirely, so this is explicit rather
        # than left to the default.
        headers={"Cache-Control": "no-store"},
    )
