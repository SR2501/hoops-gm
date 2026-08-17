"""Application settings.

Everything configurable is an environment variable, documented in the repo-root
``.env.example``. Secrets are typed ``SecretStr`` so they cannot be printed into
a log line or an error response by accident.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# .../backend/src/hoops_gm/core/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _split_csv(value: object) -> object:
    """Accept ``a,b`` as well as a JSON list for list-valued settings."""
    if isinstance(value, str) and not value.strip().startswith("["):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CsvList = Annotated[list[str], BeforeValidator(_split_csv)]


class Settings(BaseSettings):
    """Runtime configuration, read from the environment and the repo-root .env."""

    model_config = SettingsConfigDict(
        # The repo-root .env is the real one; a backend/.env is honoured so the
        # service can be run from its own directory without surprises.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "hoops-gm"
    environment: Literal["development", "test", "production"] = "development"

    # --- Server. ADR-001: local-first, loopback by default. -----------------
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Observability ------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # --- Persistence --------------------------------------------------------
    # ADR-001: SQLite in development, Postgres later. Every access goes through
    # SQLAlchemy, so this stays a configuration change.
    database_url: str = "sqlite:///./hoops_gm.db"
    database_echo: bool = False

    # --- Frontend ------------------------------------------------------------
    # The dev server proxies /api, so CORS is a belt-and-braces default for
    # anyone running the two apps on different origins.
    cors_origins: CsvList = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    # --- Secrets. Never committed; .env.example documents the shape. ---------
    bridge_secret: SecretStr | None = None
    fantrax_user_secret_id: SecretStr | None = None
    fantrax_league_id: str | None = None
    fantrax_cookie: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def _resolve_relative_sqlite_path(cls, value: str) -> str:
        """Anchor a relative SQLite path to the repo root.

        The default ``sqlite:///./hoops_gm.db`` is relative to the working
        directory, which means the database moves depending on where uvicorn
        was launched from. Anchoring it is a configuration concern only — no
        SQLite-specific behaviour reaches a query.
        """
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        raw = value[len(prefix) :]
        if raw in {"", ":memory:"} or raw.startswith("/"):
            return value
        path = Path(raw)
        if path.is_absolute():
            return value
        return f"{prefix}{(REPO_ROOT / path).resolve().as_posix()}"

    @property
    def is_loopback_bind(self) -> bool:
        """True when the server binds an address only this machine can reach."""
        return self.host in LOOPBACK_HOSTS

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def get_settings() -> Settings:
    """Build settings from the environment.

    Deliberately uncached: tests and the Alembic environment both need to build
    settings under a patched environment, and a module-level cache turns that
    into a debugging exercise.
    """
    return Settings()
