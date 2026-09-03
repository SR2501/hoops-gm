"""Run the unified hoops-gm portal demo from one fresh throwaway database."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import FrameType

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"
STARTUP_TIMEOUT_SECONDS = 45.0
_BACKEND_SETTING_NAMES = (
    "APP_NAME",
    "ENVIRONMENT",
    "HOST",
    "PORT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "DATABASE_URL",
    "DATABASE_ECHO",
    "BRIDGE_MAX_PAYLOAD_BYTES",
    "CORS_ORIGINS",
    "BRIDGE_SECRET",
    "BRIDGE_SECRET_PATH",
    "FANTRAX_USER_SECRET_ID",
    "FANTRAX_LEAGUE_ID",
    "FANTRAX_COOKIE",
    "FANTRAX_COOKIE_KEY",
    "USERSCRIPT_DIST_PATH",
)
_DISABLE_DOTENV_ENV_VAR = "HOOPS_GM_DISABLE_DOTENV"


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.upper().startswith("HOOPS_GM_"):
            env.pop(key)
    return env


def _remove_env(env: dict[str, str], *names: str) -> None:
    targets = {name.upper() for name in names}
    for key in tuple(env):
        if key.upper() in targets:
            env.pop(key)


def _python_env(
    database_url: str | None = None,
    *,
    port: int | None = None,
    bridge_secret_path: Path,
    cors_origin: str,
) -> dict[str, str]:
    env = _base_env()
    source = str(BACKEND / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source if not existing else os.pathsep.join((source, existing))
    _remove_env(env, *_BACKEND_SETTING_NAMES, _DISABLE_DOTENV_ENV_VAR)
    env.update(
        {
            _DISABLE_DOTENV_ENV_VAR: "1",
            "APP_NAME": "hoops-gm-demo",
            "ENVIRONMENT": "development",
            "HOST": "127.0.0.1",
            "LOG_LEVEL": "INFO",
            "LOG_FORMAT": "console",
            "DATABASE_ECHO": "false",
            "BRIDGE_MAX_PAYLOAD_BYTES": "1048576",
            "CORS_ORIGINS": json.dumps([cors_origin]),
            "BRIDGE_SECRET_PATH": str(bridge_secret_path),
            "USERSCRIPT_DIST_PATH": str(REPO_ROOT / "userscript" / "dist" / "hoops-gm.user.js"),
        }
    )
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    if port is not None:
        env["PORT"] = str(port)
    return env


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.resolve().as_posix()}"


def _node_command() -> str:
    executable = shutil.which("node.exe" if os.name == "nt" else "node")
    if executable is None:
        raise RuntimeError("node is not on PATH; install Node.js before running the demo")
    return executable


def _frontend_env(backend_url: str) -> dict[str, str]:
    env = _base_env()
    _remove_env(env, "DEV_SERVER_HOST", "VITE_API_BASE_URL", "VITE_API_PROXY_TARGET")
    env["DEV_SERVER_HOST"] = "127.0.0.1"
    env["VITE_API_BASE_URL"] = ""
    env["VITE_API_PROXY_TARGET"] = backend_url
    return env


def _available_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
        except OSError:
            probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_url(
    url: str,
    *,
    processes: tuple[subprocess.Popen[bytes], ...],
    deadline: float,
) -> None:
    while time.monotonic() < deadline:
        for process in processes:
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeError(
                    f"demo process {process.args!r} exited during startup with code {exit_code}"
                )
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if 200 <= response.status < 300:
                    return
        except (TimeoutError, urllib.error.URLError):
            time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for {url}")


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _request_shutdown(_signum: int, _frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def _run() -> int:
    if not (FRONTEND / "node_modules").is_dir():
        print(
            "frontend dependencies are missing; run `cd frontend; npm install` once, then retry",
            file=sys.stderr,
        )
        return 2

    processes: list[subprocess.Popen[bytes]] = []
    with tempfile.TemporaryDirectory(prefix="hoops-gm-demo-") as directory:
        runtime_directory = Path(directory)
        database_url = _sqlite_url(runtime_directory / "demo.db")
        bridge_secret_path = runtime_directory / "bridge_secret"
        backend_port = _available_port(8000)
        frontend_port = _available_port(5173)
        backend_url = f"http://127.0.0.1:{backend_port}"
        portal_url = f"http://127.0.0.1:{frontend_port}"
        seeded = subprocess.run(
            [
                sys.executable,
                "-m",
                "hoops_gm.dev.seed_demo",
                "--database-url",
                database_url,
            ],
            cwd=BACKEND,
            env=_python_env(
                bridge_secret_path=bridge_secret_path,
                cors_origin=portal_url,
            ),
            check=False,
        )
        if seeded.returncode != 0:
            return seeded.returncode

        try:
            backend = subprocess.Popen(
                [sys.executable, "-m", "hoops_gm"],
                cwd=BACKEND,
                env=_python_env(
                    database_url,
                    port=backend_port,
                    bridge_secret_path=bridge_secret_path,
                    cors_origin=portal_url,
                ),
            )
            processes.append(backend)
            frontend = subprocess.Popen(
                [
                    _node_command(),
                    str(FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(frontend_port),
                    "--strictPort",
                ],
                cwd=FRONTEND,
                env=_frontend_env(backend_url),
            )
            processes.append(frontend)

            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            _wait_for_url(
                f"{portal_url}/health/ready",
                processes=tuple(processes),
                deadline=deadline,
            )
            _wait_for_url(portal_url, processes=tuple(processes), deadline=deadline)
            print(f"\nUnified hoops-gm demo: {portal_url}")
            print("Press Ctrl+C to stop; the throwaway database is deleted on exit.")

            while all(process.poll() is None for process in processes):
                time.sleep(0.5)
            failed = next(process for process in processes if process.poll() is not None)
            print(
                f"demo process {failed.args!r} exited with code {failed.returncode}",
                file=sys.stderr,
            )
            return failed.returncode or 1
        except KeyboardInterrupt:
            return 0
        except RuntimeError as exc:
            print(f"demo startup failed: {exc}", file=sys.stderr)
            return 3
        finally:
            for process in reversed(processes):
                _stop(process)


def main() -> int:
    termination_signals = [signal.SIGTERM]
    if sighup := getattr(signal, "SIGHUP", None):
        termination_signals.append(sighup)
    previous_handlers = {
        signum: signal.signal(signum, _request_shutdown) for signum in termination_signals
    }
    try:
        return _run()
    except KeyboardInterrupt:
        return 0
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
