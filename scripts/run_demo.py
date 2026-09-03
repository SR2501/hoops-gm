"""Run the unified hoops-gm portal demo from one fresh throwaway database."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"
STARTUP_TIMEOUT_SECONDS = 45.0


def _python_env(database_url: str | None = None, *, port: int | None = None) -> dict[str, str]:
    env = os.environ.copy()
    source = str(BACKEND / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = source if not existing else os.pathsep.join((source, existing))
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    if port is not None:
        env["PORT"] = str(port)
    return env


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.resolve().as_posix()}"


def _npm_command() -> str:
    executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if executable is None:
        raise RuntimeError("npm is not on PATH; install Node.js before running the demo")
    return executable


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


def main() -> int:
    if not (FRONTEND / "node_modules").is_dir():
        print(
            "frontend dependencies are missing; run `cd frontend; npm install` once, then retry",
            file=sys.stderr,
        )
        return 2

    processes: list[subprocess.Popen[bytes]] = []
    with tempfile.TemporaryDirectory(prefix="hoops-gm-demo-") as directory:
        database_url = _sqlite_url(Path(directory) / "demo.db")
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
            env=_python_env(),
            check=False,
        )
        if seeded.returncode != 0:
            return seeded.returncode

        try:
            backend = subprocess.Popen(
                [sys.executable, "-m", "hoops_gm"],
                cwd=BACKEND,
                env=_python_env(database_url, port=backend_port),
            )
            processes.append(backend)
            frontend_env = os.environ.copy()
            frontend_env["VITE_API_PROXY_TARGET"] = backend_url
            frontend = subprocess.Popen(
                [
                    _npm_command(),
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(frontend_port),
                    "--strictPort",
                ],
                cwd=FRONTEND,
                env=frontend_env,
            )
            processes.append(frontend)

            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            _wait_for_url(
                f"{backend_url}/health/ready",
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


if __name__ == "__main__":
    raise SystemExit(main())
