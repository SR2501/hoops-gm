"""The one-command demo launcher owns its configuration and child lifetimes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_demo.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_replaces_ambient_backend_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    monkeypatch.setenv("DATABASE_URL", "postgresql://real-season")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("LOG_LEVEL", "NOT_A_LEVEL")
    monkeypatch.setenv("LOG_FORMAT", "not-a-format")
    monkeypatch.setenv("BRIDGE_SECRET", "live-secret")
    monkeypatch.setenv("BRIDGE_SECRET_PATH", str(tmp_path / "live-secret-path"))
    monkeypatch.setenv("FANTRAX_COOKIE", "live-cookie")
    monkeypatch.setenv("FANTRAX_USER_SECRET_ID", "live-user-secret")
    monkeypatch.setenv("FANTRAX_LEAGUE_ID", "live-league")
    monkeypatch.setenv("FANTRAX_COOKIE_KEY", "live-cookie-key")
    monkeypatch.setenv("HOOPS_GM_DATABASE_URL", "sqlite:///also-wrong.db")
    monkeypatch.setenv("database_url", "sqlite:///case-folded-wrong.db")
    monkeypatch.setenv("hoops_gm_disable_dotenv", "0")
    bridge_secret_path = tmp_path / "demo-secret"

    env = module._python_env(
        "sqlite:///throwaway.db",
        port=8123,
        bridge_secret_path=bridge_secret_path,
        cors_origin="http://127.0.0.1:5173",
    )

    assert env["DATABASE_URL"] == "sqlite:///throwaway.db"
    assert env["APP_NAME"] == "hoops-gm-demo"
    assert env["ENVIRONMENT"] == "development"
    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "8123"
    assert env["LOG_LEVEL"] == "INFO"
    assert env["LOG_FORMAT"] == "console"
    assert env["DATABASE_ECHO"] == "false"
    assert env["BRIDGE_MAX_PAYLOAD_BYTES"] == "1048576"
    assert env["CORS_ORIGINS"] == '["http://127.0.0.1:5173"]'
    assert env["BRIDGE_SECRET_PATH"] == str(bridge_secret_path)
    assert env["HOOPS_GM_DISABLE_DOTENV"] == "1"
    for name in (
        "BRIDGE_SECRET",
        "FANTRAX_COOKIE",
        "FANTRAX_USER_SECRET_ID",
        "FANTRAX_LEAGUE_ID",
        "FANTRAX_COOKIE_KEY",
    ):
        assert name not in env


def test_launcher_replaces_ambient_frontend_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script()
    monkeypatch.setenv("DEV_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("VITE_API_BASE_URL", "https://not-the-demo.invalid")
    monkeypatch.setenv("VITE_API_PROXY_TARGET", "http://127.0.0.1:1")
    monkeypatch.setenv("HOOPS_GM_HOST", "0.0.0.0")
    monkeypatch.setenv("vite_api_base_url", "https://case-folded.invalid")

    env = module._frontend_env("http://127.0.0.1:8123")

    assert env["DEV_SERVER_HOST"] == "127.0.0.1"
    assert env["VITE_API_BASE_URL"] == ""
    assert env["VITE_API_PROXY_TARGET"] == "http://127.0.0.1:8123"
    assert not any(key.upper().startswith("HOOPS_GM_") for key in env)


def test_stop_terminates_the_exact_child_process() -> None:
    module = _load_script()
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        module._stop(process)
        assert process.poll() is not None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_termination_handler_requests_orderly_shutdown() -> None:
    module = _load_script()

    with pytest.raises(KeyboardInterrupt):
        module._request_shutdown(15, None)


@pytest.mark.skipif(os.name == "nt", reason="Windows os.kill bypasses Python signal handlers")
def test_sigterm_is_converted_to_orderly_launcher_shutdown() -> None:
    source = f"""
import importlib.util
import os
import signal

spec = importlib.util.spec_from_file_location("run_demo_signal_test", {str(SCRIPT)!r})
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def terminate():
    os.kill(os.getpid(), signal.SIGTERM)
    return 99

module._run = terminate
raise SystemExit(module.main())
"""

    result = subprocess.run([sys.executable, "-c", source], check=False)

    assert result.returncode == 0


def test_early_frontend_failure_stops_the_backend_child(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(module, "FRONTEND", frontend)

    class FakeProcess:
        def __init__(self, args: list[str], *, returncode: int | None) -> None:
            self.args = args
            self.returncode = returncode
            self.terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

        def wait(self, timeout: float) -> int:
            assert timeout == 5
            assert self.returncode is not None
            return self.returncode

        def kill(self) -> None:
            raise AssertionError("a responsive child must not need kill()")

    backend = FakeProcess(["python", "-m", "hoops_gm"], returncode=None)
    failed_frontend = FakeProcess(["node", "vite.js"], returncode=17)
    children = iter((backend, failed_frontend))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: next(children))
    monkeypatch.setattr(module, "_node_command", lambda: "node")

    assert module.main() == 3
    assert backend.terminated is True
    assert failed_frontend.terminated is False
