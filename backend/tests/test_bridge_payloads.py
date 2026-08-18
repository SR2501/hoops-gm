"""HTTP and persistence contract tests for raw bridge captures."""

from __future__ import annotations

import json
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from hoops_gm.core.config import Settings
from hoops_gm.db.models.bridge import BridgePayload

SECRET = "bridge-test-secret"


def _auth(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(update={"bridge_secret": SecretStr(SECRET)})


def _envelope() -> dict[str, object]:
    return {
        "schema": "hoops-gm.bridge-payload.v1",
        "source": "xhr",
        "capturedAt": "2026-08-17T21:00:00Z",
        "request": {"method": "post", "url": "https://www.fantrax.com/fxpa/req"},
        "response": {"status": 502, "ok": False, "contentType": "text/html"},
        "body": {
            "raw": "<html>bad gateway</html>",
            "json": None,
            "parseError": "Unexpected token <",
        },
        "dedupeKey": "POST:deadbeef:badcafe",
    }


def test_payload_requires_the_same_bridge_secret(app: FastAPI, client: TestClient) -> None:
    _auth(app)
    response = client.post("/api/v1/bridge/payloads", json=_envelope())
    assert response.status_code == 401
    assert response.json()["error"] == "bridge_secret_missing"


def test_payload_contract_is_advertised_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    operation = paths["/api/v1/bridge/payloads"]["post"]
    assert operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert operation["requestBody"]["content"]["application/json"]


def test_payload_persists_exact_envelope_and_raw_diagnostic_fields(
    app: FastAPI, client: TestClient
) -> None:
    _auth(app)
    assert isinstance(app.state.settings.bridge_secret, SecretStr)
    raw = json.dumps(_envelope(), separators=(",", ":"))
    response = client.post(
        "/api/v1/bridge/payloads",
        content=raw,
        headers={"Content-Type": "application/json", "X-Bridge-Secret": SECRET},
    )
    assert response.status_code == 201

    with app.state.database.session() as session:
        row = session.scalar(select(BridgePayload))
        assert row is not None
        assert row.raw_payload == raw
        assert row.body_raw == "<html>bad gateway</html>"
        assert row.body_parse_error == "Unexpected token <"
        assert row.body_json is None
        assert row.request_method == "POST"


def test_runtime_paired_secret_authenticates_and_persists_payload(
    app: FastAPI, client: TestClient
) -> None:
    pairing_response = client.get("/api/v1/bridge/pairing")
    assert pairing_response.status_code == 200

    pair_response = client.post(
        "/api/v1/bridge/pair",
        headers={"X-Hoops-GM-Pairing-Code": pairing_response.json()["code"]},
    )
    assert pair_response.status_code == 200
    runtime_secret = pair_response.json()["bridgeSecret"]
    assert isinstance(runtime_secret, str)
    assert isinstance(app.state.settings.bridge_secret, str)

    response = client.post(
        "/api/v1/bridge/payloads",
        json=_envelope(),
        headers={"X-Bridge-Secret": runtime_secret},
    )
    assert response.status_code == 201

    with app.state.database.session() as session:
        row = session.scalar(select(BridgePayload))
        assert row is not None
        assert row.id == response.json()["id"]
        assert row.dedupe_key == _envelope()["dedupeKey"]


def test_payload_accepts_cache_storage_source_for_service_worker_owned_traffic(
    app: FastAPI, client: TestClient
) -> None:
    """/fxpa/req calls initiated by fx-sw.js never reach page fetch/XHR

    patching; Cache Storage is a per-origin store the page can legitimately
    read alongside the service worker, so it is a distinct, lower-confidence
    capture source rather than "fetch" or "xhr".
    """
    _auth(app)
    envelope = {
        **_envelope(),
        "source": "cache-storage",
        "request": {"method": "post", "url": "https://www.fantrax.com/fxpa/req"},
        "response": {"status": 200, "ok": True, "contentType": "application/json"},
        "body": {"raw": '{"picks":[1,2,3]}', "json": {"picks": [1, 2, 3]}, "parseError": None},
    }
    response = client.post(
        "/api/v1/bridge/payloads", json=envelope, headers={"X-Bridge-Secret": SECRET}
    )
    assert response.status_code == 201

    with app.state.database.session() as session:
        row = session.scalar(select(BridgePayload))
        assert row is not None
        assert row.source == "cache-storage"


def test_payload_accepts_manual_export_source_with_no_response_status(
    app: FastAPI, client: TestClient
) -> None:
    """The guaranteed owner-triggered fallback has no HTTP response of its

    own -- it exports whatever is already rendered on the page -- so
    ``response.status`` is legitimately ``null`` rather than an HTTP code.
    """
    _auth(app)
    envelope = {
        **_envelope(),
        "source": "manual-export",
        "request": {"method": "GET", "url": "https://www.fantrax.com/fantasy/league/abc/draft"},
        "response": {"status": None, "ok": True, "contentType": "text/html"},
        "body": {"raw": "<div>draft board</div>", "json": None, "parseError": "Unexpected token <"},
    }
    response = client.post(
        "/api/v1/bridge/payloads", json=envelope, headers={"X-Bridge-Secret": SECRET}
    )
    assert response.status_code == 201

    with app.state.database.session() as session:
        row = session.scalar(select(BridgePayload))
        assert row is not None
        assert row.source == "manual-export"
        assert row.response_status is None
        assert row.request_url == "https://www.fantrax.com/fantasy/league/abc/draft"


def test_payload_accepts_automatic_rendered_view_source(app: FastAPI, client: TestClient) -> None:
    """The automatic service-worker fallback is not mislabelled as raw RPC."""

    _auth(app)
    envelope = {
        **_envelope(),
        "source": "rendered-view",
        "request": {
            "method": "GET",
            "url": "https://www.fantrax.com/fantasy/league/abc/players",
        },
        "response": {"status": None, "ok": True, "contentType": "text/html"},
        "body": {
            "raw": "<main>rendered players</main>",
            "json": None,
            "parseError": "Unexpected token <",
        },
    }
    response = client.post(
        "/api/v1/bridge/payloads", json=envelope, headers={"X-Bridge-Secret": SECRET}
    )
    assert response.status_code == 201

    with app.state.database.session() as session:
        row = session.scalar(select(BridgePayload))
        assert row is not None
        assert row.source == "rendered-view"
        assert row.response_status is None
        assert row.body_raw == "<main>rendered players</main>"


def test_payload_rejects_an_unknown_source(app: FastAPI, client: TestClient) -> None:
    _auth(app)
    envelope = {**_envelope(), "source": "service-worker-direct"}
    response = client.post(
        "/api/v1/bridge/payloads", json=envelope, headers={"X-Bridge-Secret": SECRET}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_payload_rejects_malformed_json_inside_the_envelope(
    app: FastAPI, client: TestClient
) -> None:
    _auth(app)
    response = client.post(
        "/api/v1/bridge/payloads",
        content=b"{not-json",
        headers={"Content-Type": "application/json", "X-Bridge-Secret": SECRET},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_payload_rejects_unknown_envelope_fields(app: FastAPI, client: TestClient) -> None:
    _auth(app)
    request_data = cast(dict[str, object], _envelope()["request"])
    invalid = {
        **_envelope(),
        "request": {**request_data, "headers": {"cookie": "secret"}},
    }
    response = client.post(
        "/api/v1/bridge/payloads", json=invalid, headers={"X-Bridge-Secret": SECRET}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_payload_rejects_oversized_input(app: FastAPI, client: TestClient) -> None:
    _auth(app)
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(update={"bridge_max_payload_bytes": 32})
    response = client.post(
        "/api/v1/bridge/payloads",
        content=b"x" * 33,
        headers={"X-Bridge-Secret": SECRET},
    )
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"
