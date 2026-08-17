"""Settings behaviour, including the ADR-001 local-first guarantees."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hoops_gm.core.config import REPO_ROOT, Settings


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_bind_to_loopback() -> None:
    """ADR-001. If this test ever needs changing, read the ADR first."""
    settings = _settings()

    assert settings.host == "127.0.0.1"
    assert settings.is_loopback_bind is True


def test_non_loopback_bind_is_detected() -> None:
    assert _settings(host="0.0.0.0").is_loopback_bind is False
    assert _settings(host="192.168.1.10").is_loopback_bind is False


def test_default_database_is_sqlite() -> None:
    settings = _settings()

    assert settings.is_sqlite is True


def test_relative_sqlite_path_is_anchored_to_the_repo_root() -> None:
    """The database must not move depending on where uvicorn was launched."""
    settings = _settings(database_url="sqlite:///./hoops_gm.db")

    assert settings.database_url == f"sqlite:///{(REPO_ROOT / 'hoops_gm.db').as_posix()}"


def test_absolute_sqlite_path_is_left_alone(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'explicit.db').as_posix()}"

    assert _settings(database_url=url).database_url == url


def test_in_memory_sqlite_is_left_alone() -> None:
    assert _settings(database_url="sqlite:///:memory:").database_url == "sqlite:///:memory:"


def test_postgres_url_is_left_alone() -> None:
    """The Postgres seam is a config change and nothing else (ADR-001)."""
    url = "postgresql+psycopg://user:pw@localhost:5432/hoops_gm"
    settings = _settings(database_url=url)

    assert settings.database_url == url
    assert settings.is_sqlite is False


def test_cors_origins_accept_a_comma_separated_string() -> None:
    settings = _settings(cors_origins="http://127.0.0.1:5173,http://localhost:4173")

    assert settings.cors_origins == ["http://127.0.0.1:5173", "http://localhost:4173"]


def test_secrets_are_not_printable() -> None:
    """A cookie that renders in a log line is a cookie in a bug report."""
    settings = _settings(fantrax_cookie="super-secret-cookie", bridge_secret="hunter2")

    assert "super-secret-cookie" not in repr(settings)
    assert "super-secret-cookie" not in str(settings)
    assert "hunter2" not in repr(settings)
    assert settings.fantrax_cookie is not None
    assert settings.fantrax_cookie.get_secret_value() == "super-secret-cookie"


def test_secrets_default_to_unset() -> None:
    settings = _settings()

    assert settings.bridge_secret is None
    assert settings.fantrax_cookie is None
    assert settings.fantrax_user_secret_id is None


def test_environment_is_constrained() -> None:
    with pytest.raises(ValueError):
        _settings(environment="staging")


def test_settings_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.port == 9001
    assert settings.log_level == "DEBUG"
