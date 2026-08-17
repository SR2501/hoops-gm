"""Contract tests for the authenticated userscript handshake."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hoops_gm.core.config import Settings

SECRET = "bridge-test-secret"


def _configure_secret(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(
        update={"bridge_secret": SecretStr(SECRET)}
    )


def test_handshake_accepts_protocol_one_with_the_configured_secret(
    app: FastAPI, client: TestClient
) -> None:
    _configure_secret(app)

    response = client.post(
        "/api/v1/bridge/handshake",
        json={"protocol": 1},
        headers={"X-Bridge-Secret": SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol": 1}


def test_handshake_rejects_a_missing_secret(app: FastAPI, client: TestClient) -> None:
    _configure_secret(app)

    response = client.post("/api/v1/bridge/handshake", json={"protocol": 1})

    assert response.status_code == 401
    assert response.json()["error"] == "bridge_secret_missing"
    assert response.json()["detail"] == "Bridge secret is required."


def test_handshake_rejects_an_incorrect_secret(app: FastAPI, client: TestClient) -> None:
    _configure_secret(app)

    response = client.post(
        "/api/v1/bridge/handshake",
        json={"protocol": 1},
        headers={"X-Bridge-Secret": "wrong-secret"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "bridge_secret_invalid"
    assert response.json()["detail"] == "Bridge secret is incorrect."


def test_handshake_reports_when_no_secret_is_configured(
    app: FastAPI, client: TestClient
) -> None:
    response = client.post(
        "/api/v1/bridge/handshake",
        json={"protocol": 1},
        headers={"X-Bridge-Secret": SECRET},
    )

    assert response.status_code == 503
    assert response.json()["error"] == "bridge_secret_not_configured"
    assert response.json()["detail"] == "Bridge authentication is not configured."


def test_handshake_rejects_invalid_protocol_and_body(
    app: FastAPI, client: TestClient
) -> None:
    _configure_secret(app)

    invalid_protocol = client.post(
        "/api/v1/bridge/handshake",
        json={"protocol": 2},
        headers={"X-Bridge-Secret": SECRET},
    )
    invalid_body = client.post(
        "/api/v1/bridge/handshake",
        json={"protocol": 1, "extra": True},
        headers={"X-Bridge-Secret": SECRET},
    )

    assert invalid_protocol.status_code == 422
    assert invalid_body.status_code == 422
    assert invalid_protocol.json()["error"] == "validation_error"
    assert invalid_body.json()["error"] == "validation_error"


def test_handshake_never_echoes_or_logs_the_secret(
    app: FastAPI, client: TestClient, caplog
) -> None:
    _configure_secret(app)

    response = client.post(
        "/api/v1/bridge/handshake",
        json={"protocol": 1},
        headers={"X-Bridge-Secret": SECRET},
    )

    assert SECRET not in response.text
    assert SECRET not in caplog.text
