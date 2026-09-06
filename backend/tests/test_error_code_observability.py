"""Every typed refusal must log its error code, not just its status code.

`api/middleware.py`'s `request.completed` line logs `status_code` alone, and
before this fix `app.py`'s HTTP-exception and validation-exception handlers
logged nothing at all. Two distinct `409`s that demand different operator
actions (e.g. `schedule_grid_not_current` — re-import — versus
`schedule_grid_incomplete_evidence` — a refresh that can never populate the
contract) then read identically in the log. This asserts the `error` code
from `ErrorResponse` actually reaches a log record, distinguishable from a
same-status refusal carrying a different code — not just that *some* line
gets logged, which would pass even if every refusal logged the same
placeholder.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import LogCaptureFixture

from hoops_gm.core.config import Settings


def test_http_exception_logs_its_error_code(
    app: FastAPI, client: TestClient, caplog: LogCaptureFixture
) -> None:
    # No bridge secret configured: a reliable, already-typed HTTPException
    # path (503 bridge_secret_not_configured), no new route needed.
    with caplog.at_level("WARNING"):
        response = client.post("/api/v1/bridge/handshake", json={"protocol": 1})

    assert response.status_code == 503
    assert response.json()["error"] == "bridge_secret_not_configured"
    assert "bridge_secret_not_configured" in caplog.text
    assert "503" in caplog.text


def test_two_same_status_refusals_log_distinguishable_codes(
    app: FastAPI, client: TestClient, caplog: LogCaptureFixture
) -> None:
    """The concrete case the backlog item names: same status, different code."""
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(update={"bridge_secret": SecretStr("s3cr3t")})

    with caplog.at_level("WARNING"):
        missing_secret = client.post("/api/v1/bridge/handshake", json={"protocol": 1})
        caplog.clear()
        wrong_secret = client.post(
            "/api/v1/bridge/handshake",
            json={"protocol": 1},
            headers={"X-Bridge-Secret": "wrong"},
        )
        wrong_secret_log = caplog.text

    assert missing_secret.status_code == wrong_secret.status_code == 401
    assert missing_secret.json()["error"] == "bridge_secret_missing"
    assert wrong_secret.json()["error"] == "bridge_secret_invalid"
    # The two 401s must not collapse into the same log line: only the second
    # refusal's code should appear in the log captured around it.
    assert "bridge_secret_invalid" in wrong_secret_log
    assert "bridge_secret_missing" not in wrong_secret_log


def test_validation_error_logs_its_error_code(
    app: FastAPI, client: TestClient, caplog: LogCaptureFixture
) -> None:
    settings: Settings = app.state.settings
    app.state.settings = settings.model_copy(update={"bridge_secret": SecretStr("s3cr3t")})

    with caplog.at_level("WARNING"):
        response = client.post(
            "/api/v1/bridge/handshake",
            json={"protocol": 2},
            headers={"X-Bridge-Secret": "s3cr3t"},
        )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "validation_error" in caplog.text
    assert "422" in caplog.text


def test_middleware_request_completed_line_cannot_satisfy_the_assertions_above(
    app: FastAPI, client: TestClient, caplog: LogCaptureFixture
) -> None:
    """Negative control: prove these tests are exercising the new log line.

    `RequestContextMiddleware` already logged `status_code` on every request
    at INFO level (`request.completed`) before this fix existed. If the tests
    above captured at INFO instead of WARNING, they could pass on that
    pre-existing line alone — matching on the status code digits — without
    `app.py`'s new `request.error` line (added in `_error_response`) ever
    running. Capturing at WARNING is what rules that out. This confirms it
    directly: at WARNING, `request.completed` is absent and `request.error`
    is present, so the assertions above can only be satisfied by the new
    line, not the middleware's older one.
    """
    with caplog.at_level("WARNING"):
        client.post("/api/v1/bridge/handshake", json={"protocol": 1})

    assert "request.completed" not in caplog.text
    assert "request.error" in caplog.text
