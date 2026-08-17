"""Alembic environment.

The database URL comes from application settings, never from ``alembic.ini``.
One source of truth means a migration cannot be run against a different
database from the one the app is using — a mistake that is very cheap to make
and very expensive mid-season.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from hoops_gm.core.config import get_settings
from hoops_gm.db.base import Base
from hoops_gm.db.session import enable_sqlite_foreign_keys

# Importing the models package is what populates Base.metadata. Without it,
# autogenerate cheerfully produces a migration that drops every table.
import hoops_gm.db.models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# An explicitly configured URL wins. Nothing sets one from the command line —
# alembic.ini deliberately has no ``sqlalchemy.url`` — so ordinary use always
# goes through application settings and the app and its migrations cannot end
# up pointed at different databases. Tests construct a ``Config`` in process
# and set the URL directly, which is the one case that needs the override.
_configured_url = config.get_main_option("sqlalchemy.url", None)
database_url = _configured_url or settings.database_url
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def _include_object(
    _object: object, name: str | None, type_: str, _reflected: bool, _compare_to: object
) -> bool:
    """Ignore Alembic's own bookkeeping table when comparing."""
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        # SQLite cannot ALTER most things in place. Batch mode rewrites the
        # table instead. This is a migration-tooling accommodation, not a
        # SQLite behaviour leaking into application queries.
        render_as_batch=database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

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
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
