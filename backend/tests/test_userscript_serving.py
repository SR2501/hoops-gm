"""Tests for loopback-only userscript delivery and version status.

The tests drive the artifact bytes through the real route boundary: stale or
uncheckable metadata must never be served, while matching bytes remain exact.
They also retain ADR-010's guarantee that the artifact never acquires a
configured or runtime-paired bridge secret.
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
STATUS_URL = "/bridge/userscript-status.json"


def _configure_build(
    app: FastAPI,
    tmp_path: Path,
    *,
    source_version: str = "0.5.4",
    served_version: str | None = "0.5.4",
) -> tuple[Path, bytes | None]:
    package_path = tmp_path / "package.json"
    package_path.write_text(f'{{"version":"{source_version}"}}', encoding="utf-8")
    dist_path = tmp_path / "dist" / "hoops-gm.user.js"
    content = None
    if served_version is not None:
        dist_path.parent.mkdir()
        content = (
            "// ==UserScript==\n"
            "// @name hoops-gm bridge\n"
            f"// @version {served_version}\n"
            "// ==/UserScript==\n"
            "\n"
            "globalThis.HoopsGmBridge = {};\n"
        ).encode()
        dist_path.write_bytes(content)
    app.state.settings = app.state.settings.model_copy(
        update={
            "userscript_package_path": package_path,
            "userscript_dist_path": dist_path,
        }
    )
    return dist_path, content


def test_missing_build_returns_a_clear_404(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    _configure_build(app, tmp_path, served_version=None)

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 404
    assert response.json()["error"] == "userscript_build_missing"
    assert "npm run build" in response.json()["detail"]
    assert "userscript/" in response.json()["detail"]


def test_unreadable_build_returns_a_distinct_500(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    dist_path, _content = _configure_build(app, tmp_path, served_version=None)
    dist_path.mkdir(parents=True)

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
    _dist_path, content = _configure_build(app, tmp_path)
    assert content is not None

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "text/javascript; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-hoops-gm-userscript-version"] == "0.5.4"


def test_served_bytes_never_contain_the_configured_bridge_secret(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    secret = "super-secret-bridge-value"
    dist_path, _content = _configure_build(app, tmp_path)
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
    dist_path, _content = _configure_build(app, tmp_path)
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
    package_path = tmp_path / "package.json"
    package_path.write_text('{"version":"0.5.4"}', encoding="utf-8")
    dist_path = tmp_path / "hoops-gm.user.js"
    dist_path.write_text(
        "// ==UserScript==\n// @version 0.5.4\n// ==/UserScript==\n",
        encoding="utf-8",
    )
    settings = Settings(
        environment="development",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        bridge_secret_path=tmp_path / "bridge_secret",
        userscript_dist_path=dist_path,
        userscript_package_path=package_path,
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as non_local_client:
        Base.metadata.create_all(app.state.database.engine)
        response = non_local_client.get(USERSCRIPT_URL)

    assert response.status_code == 403
    assert response.json()["error"] == "userscript_local_only"


def test_refuses_to_serve_an_artifact_with_a_stale_version(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    _configure_build(app, tmp_path, source_version="0.5.4", served_version="0.5.3")

    response = client.get(USERSCRIPT_URL)

    assert response.status_code == 409
    assert response.json()["error"] == "userscript_build_version_mismatch"
    assert "npm run build" in response.json()["detail"]
    assert b"globalThis.HoopsGmBridge" not in response.content


def test_status_reports_matching_and_update_available_from_the_served_artifact(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    _configure_build(app, tmp_path)

    current = client.get(STATUS_URL, params={"installed_version": "0.5.4"})
    update = client.get(STATUS_URL, params={"installed_version": "0.5.3"})

    assert current.status_code == 200
    assert current.json() == {
        "status": "current",
        "installed_version": "0.5.4",
        "source_version": "0.5.4",
        "served_version": "0.5.4",
        "reason": None,
    }
    assert update.status_code == 200
    assert update.json() == {
        "status": "update_available",
        "installed_version": "0.5.3",
        "source_version": "0.5.4",
        "served_version": "0.5.4",
        "reason": "installed_version_behind",
    }
    assert update.headers["cache-control"] == "no-store"


def test_status_reports_source_artifact_mismatch_without_serving_stale_bytes(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    _configure_build(app, tmp_path, source_version="0.5.4", served_version="0.5.3")

    response = client.get(STATUS_URL, params={"installed_version": "0.5.3"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "mismatch",
        "installed_version": "0.5.3",
        "source_version": "0.5.4",
        "served_version": "0.5.3",
        "reason": "userscript_build_version_mismatch",
    }


def test_status_is_explicitly_uncheckable_for_missing_or_invalid_metadata(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    dist_path, _content = _configure_build(app, tmp_path, served_version=None)

    missing = client.get(STATUS_URL, params={"installed_version": "0.5.3"})
    dist_path.parent.mkdir(exist_ok=True)
    dist_path.write_text(
        "// ==UserScript==\n// @name hoops-gm bridge\n// ==/UserScript==\n",
        encoding="utf-8",
    )
    invalid = client.get(STATUS_URL, params={"installed_version": "0.5.3"})

    assert missing.json()["status"] == "uncheckable"
    assert missing.json()["reason"] == "userscript_build_missing"
    assert invalid.json()["status"] == "uncheckable"
    assert invalid.json()["reason"] == "userscript_build_version_uncheckable"


def test_refuses_a_version_line_outside_a_valid_userscript_metadata_block(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    dist_path, _content = _configure_build(app, tmp_path)
    malformed_artifacts = (
        "// @version 0.5.4\n// ==/UserScript==\nglobalThis.HoopsGmBridge = {};\n",
        "// ==UserScript==garbage\n// @version 0.5.4\n// ==/UserScript==\n",
        "// ==UserScript==\n// @version 0.5.4\n// ==/UserScript==garbage\n",
    )

    for artifact in malformed_artifacts:
        dist_path.write_text(artifact, encoding="utf-8")
        response = client.get(USERSCRIPT_URL)
        assert response.status_code == 500
        assert response.json()["error"] == "userscript_build_version_uncheckable"
        assert b"globalThis.HoopsGmBridge" not in response.content


def test_status_refuses_to_call_an_installed_version_ahead_current(
    app: FastAPI, client: TestClient, tmp_path: Path
) -> None:
    _configure_build(app, tmp_path)

    ahead = client.get(STATUS_URL, params={"installed_version": "0.5.10"})
    absent = client.get(STATUS_URL)

    assert ahead.json()["status"] == "mismatch"
    assert ahead.json()["reason"] == "installed_version_ahead"
    assert absent.json()["status"] == "uncheckable"
    assert absent.json()["reason"] == "installed_version_uncheckable"
