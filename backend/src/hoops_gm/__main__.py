"""Run the backend: ``python -m hoops_gm``."""

from __future__ import annotations

import uvicorn

from hoops_gm.core.config import get_settings
from hoops_gm.core.logging import configure_logging, get_logger


def main() -> None:
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
