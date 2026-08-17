"""Request-scoped dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from hoops_gm.core.config import Settings
from hoops_gm.db.session import Database


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> Iterator[Session]:
    """Yield a transactional session, committed on success."""
    with database.session() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DatabaseDep = Annotated[Database, Depends(get_database)]
SessionDep = Annotated[Session, Depends(get_session)]
