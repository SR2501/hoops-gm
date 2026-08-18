"""Engine and session management.

The engine is held on a small ``Database`` object rather than a module global
so that tests, the Alembic environment and the app can each build their own
without fighting over import order.

ADR-001 discipline: the only place in the codebase that is allowed to know
which dialect is in use is right here, in engine construction. Nothing
downstream may branch on it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import Executable

from hoops_gm.core.config import Settings


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    """Make SQLite enforce foreign keys, which it does not do by default.

    This is not a SQLite convenience — it is the opposite. Without it, SQLite
    silently accepts referential garbage that Postgres would reject, and the
    dialect swap in Phase 13 becomes a data cleanup rather than a config change.

    Registered as a connect-time event rather than executed on a live
    connection. Issuing the pragma on an open ``Connection`` implicitly starts
    a transaction, which makes Alembic treat the transaction as externally
    managed and silently skip its own commit.
    """

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_engine(settings: Settings) -> Engine:
    """Build the SQLAlchemy engine for the configured database URL."""
    kwargs: dict[str, Any] = {
        "echo": settings.database_echo,
        "future": True,
        # Fail fast on a stale pooled connection instead of at lineup lock.
        "pool_pre_ping": True,
    }

    if settings.is_sqlite:
        # SQLite's default check_same_thread guard does not survive FastAPI's
        # threadpool. An in-memory URL additionally needs a single shared
        # connection or each session gets its own empty database.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in settings.database_url:
            kwargs["poolclass"] = StaticPool

    engine = create_engine(settings.database_url, **kwargs)

    if engine.dialect.name == "sqlite":
        enable_sqlite_foreign_keys(engine)

    return engine


def acquire_transaction_lock(
    session: Session,
    *,
    scope_key: str,
    write_reservation: Executable,
) -> None:
    """Hold one logical scope until commit on both supported dialects.

    PostgreSQL uses a transaction-level advisory lock so even a scope with no
    lineage rows yet is serialized. SQLite needs a no-op UPDATE to acquire its
    database-wide write reservation before validation. Keeping this choice here
    preserves ADR-001's rule that downstream persistence code never branches on
    a dialect.
    """

    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        session.execute(write_reservation)
        return

    digest = hashlib.sha256(scope_key.encode("utf-8")).digest()
    advisory_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    session.execute(select(func.pg_advisory_xact_lock(advisory_key)))


@dataclass(slots=True)
class Database:
    """Engine plus session factory for one configured database."""

    engine: Engine
    session_factory: sessionmaker[Session]

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        engine = create_db_engine(settings)
        return cls(
            engine=engine,
            session_factory=sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
                class_=Session,
            ),
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Session scope that commits on success and rolls back on failure."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
