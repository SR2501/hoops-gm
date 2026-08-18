"""Authenticated transport boundary for the browser bridge."""

from __future__ import annotations

import json
import secrets
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, field_validator

from hoops_gm.api.deps import SessionDep, SettingsDep
from hoops_gm.core.bridge_pairing import BridgePairing
from hoops_gm.db.models.bridge import BridgePayload

router = APIRouter(prefix="/bridge", tags=["bridge"])


class PairingResponse(BaseModel):
    """The generated bearer secret, returned only on the successful pairing call."""

    bridge_secret: str = Field(alias="bridgeSecret")

    model_config = ConfigDict(populate_by_name=True)


class HandshakeRequest(BaseModel):
    """The protocol version spoken by the userscript."""

    model_config = ConfigDict(extra="forbid")

    protocol: Literal[1]


class HandshakeResponse(BaseModel):
    """Minimal stable response used to establish bridge compatibility."""

    status: Literal["ok"] = "ok"
    protocol: Literal[1] = 1


class BridgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_name: Literal["hoops-gm.bridge-payload.v1"] = Field(alias="schema")
    # "cache-storage", "rendered-view", and "manual-export" cover /fxpa/req
    # traffic issued by Fantrax's own service worker (fx-sw.js), which
    # page-world fetch/XHR patching structurally cannot observe. A rendered
    # view is deliberately labelled separately from a raw response.
    source: Literal["fetch", "xhr", "cache-storage", "rendered-view", "manual-export"]
    captured_at: AwareDatetime = Field(alias="capturedAt")
    request: BridgeRequestDetails
    response: BridgeResponseDetails
    body: BridgeBody
    dedupe_key: str = Field(alias="dedupeKey", min_length=1, max_length=256)


class BridgeRequestDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str = Field(min_length=1, max_length=32)
    url: str = Field(min_length=1, max_length=4096)

    @field_validator("method")
    @classmethod
    def method_is_uppercase(cls, value: str) -> str:
        return value.upper()


class BridgeResponseDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int | None = Field(default=None, ge=100, le=599)
    ok: bool
    content_type: str | None = Field(default=None, alias="contentType", max_length=512)


class BridgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    raw: str
    json_value: Any | None = Field(default=None, alias="json")
    parse_error: str | None = Field(default=None, alias="parseError", max_length=2048)


class BridgePayloadResponse(BaseModel):
    id: int
    status: Literal["stored"] = "stored"


def _bridge_secret_value(configured_secret: SecretStr | str | None) -> str | None:
    """Normalize the two intentional active-secret representations."""
    if configured_secret is None:
        return None
    if isinstance(configured_secret, SecretStr):
        return configured_secret.get_secret_value()
    return configured_secret


def require_bridge_secret(
    settings: SettingsDep,
    bridge_secret: str | None = Header(default=None, alias="X-Bridge-Secret"),
) -> None:
    """Authenticate both bridge operations without putting the secret in logs."""
    configured_secret = _bridge_secret_value(settings.bridge_secret)
    if not configured_secret:
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
    if not secrets.compare_digest(bridge_secret, configured_secret):
        raise HTTPException(
            status_code=401,
            detail="Bridge secret is incorrect.",
            headers={"X-Bridge-Error": "bridge_secret_invalid"},
        )


def _require_local_pairing_request(request: Request) -> None:
    host = request.client.host if request.client else None
    if (
        host not in {"127.0.0.1", "::1", "localhost"}
        and request.app.state.settings.environment != "test"
    ):
        raise HTTPException(
            status_code=403,
            detail="Bridge pairing is local-only.",
            headers={"X-Bridge-Error": "pairing_local_only"},
        )
    if request.headers.get("cookie") or request.headers.get("origin"):
        raise HTTPException(
            status_code=403,
            detail="Bridge pairing does not accept cookies or cross-origin requests.",
            headers={"X-Bridge-Error": "pairing_origin_forbidden"},
        )


@router.get("/pairing", summary="Display a one-time local bridge pairing code")
def pairing_code(request: Request) -> dict[str, str]:
    _require_local_pairing_request(request)
    pairing: BridgePairing = request.app.state.bridge_pairing
    if pairing.has_secret:
        raise HTTPException(
            status_code=409,
            detail="Bridge authentication is already configured.",
            headers={"X-Bridge-Error": "bridge_secret_already_configured"},
        )
    try:
        return {"code": pairing.issue_code()}
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail="Bridge authentication is already configured.",
            headers={"X-Bridge-Error": "bridge_secret_already_configured"},
        ) from exc


@router.post("/pair", response_model=PairingResponse, summary="Pair the local browser bridge")
def pair_bridge(
    request: Request,
    pairing_code: str | None = Header(default=None, alias="X-Hoops-GM-Pairing-Code"),
) -> PairingResponse:
    _require_local_pairing_request(request)
    if not pairing_code:
        raise HTTPException(
            status_code=401,
            detail="Pairing code is required.",
            headers={"X-Bridge-Error": "pairing_code_missing"},
        )
    pairing: BridgePairing = request.app.state.bridge_pairing
    try:
        secret = pairing.consume_code(pairing_code)
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail="Pairing code is invalid, expired, or locked.",
            headers={"X-Bridge-Error": "pairing_code_invalid"},
        ) from exc
    request.app.state.settings = request.app.state.settings.model_copy(
        update={"bridge_secret": secret}
    )
    return PairingResponse(bridge_secret=secret)


@router.post(
    "/handshake",
    response_model=HandshakeResponse,
    summary="Establish the userscript bridge protocol",
)
def handshake(
    payload: HandshakeRequest,
    _authenticated: None = Depends(require_bridge_secret),
) -> HandshakeResponse:
    """Authenticate the local userscript and confirm the protocol version.

    Secret values are deliberately never included in an exception, response, or
    log field. ``compare_digest`` also avoids turning this local boundary into a
    byte-by-byte secret oracle.
    """

    return HandshakeResponse(protocol=payload.protocol)


@router.post(
    "/payloads",
    response_model=BridgePayloadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Store one authenticated raw Fantrax bridge capture",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": BridgeRequest.model_json_schema()},
            },
        }
    },
)
async def store_payload(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    _authenticated: None = Depends(require_bridge_secret),
) -> BridgePayloadResponse:
    """Validate and persist the typed envelope without normalising Fantrax JSON."""
    content_length = request.headers.get("content-length")
    if content_length is not None and (
        not content_length.isdigit() or int(content_length) > settings.bridge_max_payload_bytes
    ):
        raise HTTPException(
            status_code=413,
            detail="Bridge payload exceeds the maximum allowed size.",
            headers={"X-Bridge-Error": "payload_too_large"},
        )
    raw_bytes = await request.body()
    if len(raw_bytes) > settings.bridge_max_payload_bytes:
        raise HTTPException(
            status_code=413,
            detail="Bridge payload exceeds the maximum allowed size.",
            headers={"X-Bridge-Error": "payload_too_large"},
        )
    try:
        raw_payload = raw_bytes.decode("utf-8")
        parsed = json.loads(raw_payload)
        payload = BridgeRequest.model_validate(parsed)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Bridge payload must be valid JSON matching the bridge envelope.",
            headers={"X-Bridge-Error": "validation_error"},
        ) from exc

    row = BridgePayload(
        schema_name=payload.schema_name,
        source=payload.source,
        captured_at=payload.captured_at,
        request_method=payload.request.method,
        request_url=payload.request.url,
        response_status=payload.response.status,
        response_ok=payload.response.ok,
        response_content_type=payload.response.content_type,
        body_raw=payload.body.raw,
        body_json=payload.body.json_value,
        body_parse_error=payload.body.parse_error,
        dedupe_key=payload.dedupe_key,
        raw_payload=raw_payload,
    )
    session.add(row)
    session.flush()
    return BridgePayloadResponse(id=row.id)
