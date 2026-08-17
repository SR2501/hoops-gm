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


def test_openapi_document_is_servable(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/api/v1/meta" in paths
