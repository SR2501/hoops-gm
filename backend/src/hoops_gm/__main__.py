"""Run the backend: ``python -m hoops_gm``."""

from __future__ import annotations

import argparse

import uvicorn

from hoops_gm.core.config import get_settings
from hoops_gm.core.logging import configure_logging, get_logger


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="python -m hoops_gm",
        description="Run the hoops-gm backend server.",
    )


def main() -> None:
    # Parse arguments before touching settings, logging, or the network.
    # ``--help`` is the one command a stranger runs to find out what this
    # program does, and argparse's built-in ``-h``/``--help`` handling prints
    # usage and exits here — before ``get_settings()`` would read ``.env``
    # (including Fantrax credentials) or ``uvicorn.run`` binds a port.
    _build_parser().parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    get_logger(__name__).info("server.starting", host=settings.host, port=settings.port)
    uvicorn.run(
        "hoops_gm.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
