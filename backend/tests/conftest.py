"""Shared test fixtures.

Every test runs against a throwaway SQLite database built from the ORM
metadata, except the migration tests, which deliberately build theirs by
running Alembic — those two paths have to be checked separately or a schema
that only exists in the models passes silently.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hoops_gm.app import create_app
from hoops_gm.core.config import Settings
from hoops_gm.db.base import Base
from hoops_gm.db.session import Database

# Any FANTRAX_* or DATABASE_URL already exported into the developer's shell
# would otherwise bleed into the test run.
_ENV_TO_CLEAR = (
    "DATABASE_URL",
    "HOST",
    "PORT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "ENVIRONMENT",
    "CORS_ORIGINS",
    "BRIDGE_SECRET",
    "FANTRAX_USER_SECRET_ID",
    "FANTRAX_LEAGUE_ID",
    "FANTRAX_COOKIE",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed at a file-backed SQLite database in a temp directory."""
    db_path = (tmp_path / "test.db").as_posix()
    return Settings(
        environment="test",
        database_url=f"sqlite:///{db_path}",
        log_format="json",
        _env_file=None,
    )


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    db = Database.from_settings(settings)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        Base.metadata.drop_all(db.engine)
        db.dispose()


@pytest.fixture
def session(database: Database) -> Iterator[Session]:
    """A session that never commits.

    Several schema tests deliberately provoke an IntegrityError. Committing on
    teardown would then fail in the fixture rather than in the test, which
    turns a clear assertion into a confusing error.
    """
    db_session = database.session_factory()
    try:
        yield db_session
    finally:
        db_session.rollback()
        db_session.close()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI, settings: Settings) -> Iterator[TestClient]:
    """Client with the schema created, since lifespan builds its own Database."""
    with TestClient(app) as test_client:
        Base.metadata.create_all(app.state.database.engine)
        yield test_client


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def pytest_report_header() -> str:
    return f"hoops-gm backend tests (cwd={os.getcwd()})"
