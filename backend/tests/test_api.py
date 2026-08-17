"""Health and metadata endpoints."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hoops_gm import __version__
from hoops_gm.core.config import Settings
from hoops_gm.db.session import Database


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "hoops-gm"
    assert body["version"] == __version__
    assert body["environment"] == "test"


def test_health_returns_a_request_id(client: TestClient) -> None:
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_health_echoes_a_supplied_request_id(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "abc123"})

    assert response.headers["X-Request-ID"] == "abc123"


def test_readiness_checks_the_database(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "detail": None}


def test_readiness_degrades_when_the_database_is_unreachable(
    app: FastAPI, client: TestClient
) -> None:
    unreachable = Settings(
        environment="test",
        database_url="sqlite:////no-such-directory/missing.db",
        _env_file=None,
    )
    app.state.database.dispose()
    app.state.database = Database.from_settings(unreachable)

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    # The detail must never leak a connection string; it can carry a password.
    assert "missing.db" not in body["detail"]


def test_meta_lists_the_implemented_entity_groups(client: TestClient) -> None:
    response = client.get("/api/v1/meta")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "hoops-gm"
    assert body["season"] == "2026-27"
    assert body["entity_groups"] == ["identity", "stats", "league", "schedule"]


def test_unknown_route_uses_the_stable_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error", "detail", "request_id"}
    assert body["error"] == "http_error"


def test_an_unhandled_exception_stays_inside_the_error_contract(app: FastAPI) -> None:
    """Review finding 5.

    A 500 used to escape as plain-text "Internal Server Error" with no
    X-Request-ID, breaking correlation for exactly the failures it exists to
    trace. Note that registering the handler was not sufficient on its own —
    the middleware also cleared the logging context before re-raising, so the
    handler saw request_id=None.
    """

    @app.get("/api/v1/_boom")
    def _boom() -> None:
        raise RuntimeError("database on fire")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/_boom")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error", "detail", "request_id"}
    assert body["error"] == "internal_error"
    assert body["request_id"], "correlation lost on the errors that most need it"
    assert response.headers["X-Request-ID"] == body["request_id"]
    # The exception message can carry a connection URL, and a URL can carry a
    # password. Only the type is safe to return.
    assert "database on fire" not in body["detail"]
    assert "RuntimeError" in body["detail"]


def test_openapi_document_is_servable(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/meta" in paths
