"""The one-command demo launcher owns its configuration and child lifetimes."""

from __future__ import annotations

import importlib.util
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


def test_launcher_replaces_ambient_backend_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script()
    monkeypatch.setenv("DATABASE_URL", "postgresql://real-season")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.setenv("HOOPS_GM_DATABASE_URL", "sqlite:///also-wrong.db")
    monkeypatch.setenv("database_url", "sqlite:///case-folded-wrong.db")

    env = module._python_env("sqlite:///throwaway.db", port=8123)

    assert env["DATABASE_URL"] == "sqlite:///throwaway.db"
    assert env["ENVIRONMENT"] == "development"
    assert env["HOST"] == "127.0.0.1"
    assert env["PORT"] == "8123"
    assert not any(key.upper().startswith("HOOPS_GM_") for key in env)


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


def test_early_frontend_failure_stops_the_backend_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()

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
    frontend = FakeProcess(["node", "vite.js"], returncode=17)
    children = iter((backend, frontend))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: next(children))
    monkeypatch.setattr(module, "_node_command", lambda: "node")

    assert module.main() == 3
    assert backend.terminated is True
    assert frontend.terminated is False
