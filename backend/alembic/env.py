"""Alembic environment.

The database URL comes from application settings, never from ``alembic.ini``.
One source of truth means a migration cannot be run against a different
database from the one the app is using — a mistake that is very cheap to make
and very expensive mid-season.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from hoops_gm.core.config import get_settings
from hoops_gm.db.base import Base, UTCDateTime, enum_check_constraint_names
from hoops_gm.db.session import enable_sqlite_foreign_keys

# Importing the models package is what populates Base.metadata. Without it,
# autogenerate cheerfully produces a migration that drops every table.
import hoops_gm.db.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# The URL never passes through ``config.set_main_option``. Alembic stores main
# options in a ConfigParser using BasicInterpolation, which treats ``%`` as an
# escape — so a URL-encoded Postgres password (``%40`` for ``@``, ``%23`` for
# ``#``) crashes ``alembic upgrade head`` with an interpolation error that says
# nothing about why. That would fire at exactly the moment ADR-001's "config
# change plus a data migration" is being exercised for the first time.
#
# ``config.attributes`` is a plain dict and bypasses the ConfigParser entirely.
# Tests construct a Config in process and set the URL there; ordinary CLI use
# has no attribute set and falls through to application settings, so the app
# and its migrations cannot end up pointed at different databases.
_configured_url = config.attributes.get("sqlalchemy_url")
database_url: str = _configured_url or settings.database_url

target_metadata = Base.metadata

_ENUM_CHECK_NAMES = enum_check_constraint_names(target_metadata)


def _include_object(
    _object: object, name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    """Filter objects out of autogenerate comparison.

    Two exclusions, both narrow:

    * Alembic's own ``alembic_version`` bookkeeping table.
    * The CHECK constraints SQLAlchemy generates for enum columns, which
      autogenerate reflects from the database but skips in metadata — see
      ``enum_check_constraint_names``. Their existence is asserted by
      ``test_database_guarantees.py`` against raw SQL, which is a stronger
      check than their presence in a diff.
    """
    if type_ == "table" and name == "alembic_version":
        return False
    return not (type_ == "check_constraint" and name in _ENUM_CHECK_NAMES)


def _render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Render custom column types as plain SQLAlchemy types.

    Autogenerate would otherwise emit ``hoops_gm.db.base.UTCDateTime()`` into
    the migration, which makes a migration depend on live application code —
    so renaming or moving that class silently breaks the ability to migrate an
    old database. Migrations must stay readable and runnable years after the
    code they were generated from has moved on. ``UTCDateTime`` is only a
    bind/result behaviour; its DDL is exactly ``DateTime(timezone=True)``.
    """
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        render_item=_render_item,
        # SQLite cannot ALTER most things in place. Batch mode rewrites the
        # table instead. This is a migration-tooling accommodation, not a
        # SQLite behaviour leaking into application queries.
        render_as_batch=database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # create_engine directly rather than engine_from_config: the URL must not
    # be round-tripped through the ConfigParser (see the note above).
    connectable = create_engine(database_url, poolclass=pool.NullPool)

    if connectable.dialect.name == "sqlite":
        # Registered on the engine, not executed on the connection. Running a
        # statement on the connection before context.configure() starts a
        # transaction, and Alembic then treats the transaction as externally
        # managed and never commits the alembic_version row — the schema
        # applies but the database claims to be at no revision.
        enable_sqlite_foreign_keys(connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=_include_object,
            render_item=_render_item,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
