"""Authenticated transport boundary for the browser bridge."""

from __future__ import annotations

import secrets
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from hoops_gm.api.deps import SettingsDep

router = APIRouter(prefix="/bridge", tags=["bridge"])


class HandshakeRequest(BaseModel):
    """The protocol version spoken by the userscript."""

    model_config = ConfigDict(extra="forbid")

    protocol: Literal[1]


class HandshakeResponse(BaseModel):
    """Minimal stable response used to establish bridge compatibility."""

    status: Literal["ok"] = "ok"
    protocol: Literal[1] = 1


@router.post(
    "/handshake",
    response_model=HandshakeResponse,
    summary="Establish the userscript bridge protocol",
)
def handshake(
    payload: HandshakeRequest,
    settings: SettingsDep,
    bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
) -> HandshakeResponse:
    """Authenticate the local userscript and confirm the protocol version.

    Secret values are deliberately never included in an exception, response, or
    log field. ``compare_digest`` also avoids turning this local boundary into a
    byte-by-byte secret oracle.
    """

    configured_secret = settings.bridge_secret
    if configured_secret is None or not configured_secret.get_secret_value():
        raise HTTPException(
            status_code=503,
            detail="Bridge authentication is not configured.",
            headers={"X-Bridge-Error": "bridge_secret_not_configured"},
        )
    if bridge_secret is None:
        raise HTTPException(
            status_code=401,
            detail="Bridge secret is required.",
            headers={"X-Bridge-Error": "bridge_secret_missing"},
        )
    if not secrets.compare_digest(bridge_secret, configured_secret.get_secret_value()):
        raise HTTPException(
            status_code=401,
            detail="Bridge secret is incorrect.",
            headers={"X-Bridge-Error": "bridge_secret_invalid"},
        )
    return HandshakeResponse(protocol=payload.protocol)
