"""Tests for the loopback-only userscript-serving route.

Covers the two behaviours this session was asked to harden: a missing build
must fail with a clear, actionable detail instead of a bare 404, and the
served bytes must never contain a bridge secret regardless of whether one is
configured (ADR-010 — the userscript only ever gets its secret through
pairing, never a build artifact).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hoops_gm.app import create_app
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base

USERSCRIPT_URL = "/bridge/userscript.user.js"


def test_missing_build_returns_a_clear_404(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"userscript_dist_path": tmp_path / "does-not-exist" / "hoops-gm.user.js"}
    )

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 404
    assert response.json()["error"] == "userscript_build_missing"
    assert "npm run build" in response.json()["detail"]
    assert "userscript/" in response.json()["detail"]


def test_unreadable_build_returns_a_distinct_500(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    dist_path = tmp_path / "hoops-gm.user.js"
    dist_path.mkdir()
    app.state.settings = app.state.settings.model_copy(update={"userscript_dist_path": dist_path})

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 500
    assert response.json()["error"] == "userscript_build_unreadable"
    assert "could not be read" in response.json()["detail"]


def test_serves_the_built_userscript_uncached(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    # write_bytes/read_bytes, not write_text/read_text: text mode translates
    # "\n" to os.linesep on write and back on read, which on Windows would
    # mask the route serving raw bytes exactly as stored on disk.
    content = b"// ==UserScript==\n// @name hoops-gm bridge\n// ==/UserScript==\n"
    dist_path = tmp_path / "hoops-gm.user.js"
    dist_path.write_bytes(content)
    app.state.settings = app.state.settings.model_copy(update={"userscript_dist_path": dist_path})

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"


def test_served_bytes_never_contain_the_configured_bridge_secret(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    secret = "super-secret-bridge-value"
    dist_path = tmp_path / "hoops-gm.user.js"
    dist_path.write_text("// ==UserScript==\n// no secret lives in a build\n// ==/UserScript==\n")
    app.state.settings = app.state.settings.model_copy(
        update={
            "userscript_dist_path": dist_path,
            "bridge_secret": SecretStr(secret),
        }
    )

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 200
    assert secret not in response.text


def test_served_bytes_never_contain_the_runtime_paired_bridge_secret(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    secret = "runtime-paired-bridge-value"
    dist_path = tmp_path / "hoops-gm.user.js"
    dist_path.write_text("// ==UserScript==\n// no secret lives in a build\n// ==/UserScript==\n")
    app.state.settings = app.state.settings.model_copy(
        update={
            "userscript_dist_path": dist_path,
            "bridge_secret": secret,
        }
    )

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 200
    assert secret not in response.text


def test_rejects_a_non_loopback_caller(tmp_path: Path) -> None:
    dist_path = tmp_path / "hoops-gm.user.js"
    dist_path.write_text("// ==UserScript==\n// ==/UserScript==\n")
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        userscript_dist_path=dist_path,
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as non_local_client:
        Base.metadata.create_all(app.state.database.engine)
        response = non_local_client.get(USERSCRIPT_URL)

    assert response.status_code == 403
    assert response.json()["error"] == "userscript_local_only"
