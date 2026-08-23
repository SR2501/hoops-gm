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
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.engine import URL, make_url
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


def render_store_url(url: URL) -> tuple[str, str | None]:
    """Describe a connection URL for display: safe text, plus a local path.

    Lives here rather than at the call site because deciding *whether a store
    is a local file* is dialect knowledge, and ADR-001 confines that to engine
    construction. The caller receives a dialect-neutral pair and never asks
    which database it is talking to.

    The password is hidden because this string is written into logs, CI
    summaries and handoff entries — naming a store must never become a way to
    leak a credential.
    """
    database = url.database
    local_path: str | None = None
    if url.get_backend_name() == "sqlite" and database and database != ":memory:":
        local_path = str(Path(database).resolve())
    return url.render_as_string(hide_password=True), local_path


def missing_local_store(url: URL | str) -> str | None:
    """The store's path, when the URL names a local file that does not exist.

    Exists because SQLite **creates** a database on connect rather than
    refusing. For a writer that is the desired behaviour; for a read-only
    reporting tool it is a trap, and a specific one: a mistyped path yields a
    brand-new empty file, and every subsequent count against it is honest,
    reproducible and zero. That is how a *fresh* false zero gets manufactured
    by the very check meant to settle one.

    Returns ``None`` for a store that exists, and for any store that is not a
    local file (a server-backed URL cannot be inspected this cheaply, and its
    own connection error is the loud failure).
    """
    resolved = make_url(url) if isinstance(url, str) else url
    _, local_path = render_store_url(resolved)
    if local_path is not None and not Path(local_path).exists():
        return local_path
    return None


def absent_store_refusal(url: URL | str) -> str | None:
    """A ready-to-print refusal when the configured store is an absent local file.

    Returns ``None`` when there is nothing to refuse, so a caller reads as
    ``if (refusal := absent_store_refusal(...)) is not None: print(refusal)``.

    **What this does and does not buy**, since the tempting claim is wrong and
    was made in an earlier handoff entry before being driven. Without it, an
    absent path yields a new *unmigrated* file and the next query dies on
    ``no such table``: that is loud, so it is not a silent wrong number. What it
    is, is **litter plus a misdiagnosis** — the error blames the schema when the
    fault is the path. This turns that into an accurate message naming the file.

    It does **not** close the false-zero hole. A store that is *migrated and
    empty* answers everything honestly with zero and exits successfully, and
    that is what actually produced the 2026-08-22 contradiction. The remedy for
    that one is reporting the store alongside the count, not refusing to open
    it.

    Commands that *write* deliberately do not use this: creating the database
    is correct for them.
    """
    absent = missing_local_store(url)
    if absent is None:
        return None
    return (
        f"ERROR: no database file at {absent}\n"
        f"  Refusing to create one: SQLite would make an empty, unmigrated database "
        f"here, and the `no such table` that followed would blame the schema for "
        f"what is a wrong path.\n"
        f"  Check DATABASE_URL, or run `alembic upgrade head` to build it "
        f"deliberately."
    )


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
