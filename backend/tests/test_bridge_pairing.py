"""Tests for the local bridge provisioning contract."""

from __future__ import annotations

import base64
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import LogCaptureFixture, raises

from hoops_gm.core.bridge_pairing import BridgePairing
from hoops_gm.core.config import Settings


def test_pairing_code_is_twelve_characters_and_expires() -> None:
    pairing = BridgePairing(Path("unused"), None)
    code = pairing.issue_code(now=100.0)
    assert len(code) == 12
    assert pairing.issue_code(now=699.0) == code
    with suppress(ValueError):
        pairing.consume_code(code, now=700.0)
    if pairing.has_secret:
        raise AssertionError("expired code was accepted")


def test_wrong_code_is_locked_after_five_attempts() -> None:
    pairing = BridgePairing(Path("unused"), None)
    code = pairing.issue_code(now=100.0)
    for _ in range(5):
        with suppress(ValueError):
            pairing.consume_code("WRONG-CODE", now=101.0)
    with suppress(ValueError):
        pairing.consume_code(code, now=101.0)
    if pairing.has_secret:
        raise AssertionError("locked code was accepted")


def test_pairing_is_exactly_once_and_persists_the_secret(tmp_path: Path) -> None:
    path = tmp_path / "bridge_secret"
    pairing = BridgePairing(path, None)
    code = pairing.issue_code()
    secret = pairing.consume_code(code)
    assert len(base64.urlsafe_b64decode(secret + "==")) == 32
    assert path.read_text(encoding="utf-8") == secret
    with raises(ValueError):
        pairing.consume_code(code)


def test_pairing_endpoint_returns_secret_once_and_does_not_log(
    app: FastAPI, client: TestClient, caplog: LogCaptureFixture
) -> None:
    code_response = client.get("/api/v1/bridge/pairing")
    assert code_response.status_code == 200
    code = code_response.json()["code"]
    assert len(code) == 12

    response = client.post(
        "/api/v1/bridge/pair",
        headers={"X-Hoops-GM-Pairing-Code": code},
    )
    assert response.status_code == 200
    secret = response.json()["bridgeSecret"]
    assert len(base64.urlsafe_b64decode(secret + "==")) == 32
    assert secret not in response.headers.get("x-request-id", "")
    assert secret not in str(caplog)

    replay = client.post(
        "/api/v1/bridge/pair",
        headers={"X-Hoops-GM-Pairing-Code": code},
    )
    assert replay.status_code == 401
    assert replay.json()["error"] == "pairing_code_invalid"


def test_configured_secret_disables_pairing(app: FastAPI, client: TestClient) -> None:
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(update={"bridge_secret": SecretStr("override")})
    app.state.bridge_pairing = BridgePairing(settings.bridge_secret_path, "override")

    response = client.get("/api/v1/bridge/pairing")
    assert response.status_code == 409
    assert response.json()["error"] == "bridge_secret_already_configured"


def test_pairing_rejects_origin_and_cookie(app: FastAPI, client: TestClient) -> None:
    assert (
        client.get("/api/v1/bridge/pairing", headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/v1/bridge/pairing", headers={"Cookie": "x=y"}).status_code == 403
