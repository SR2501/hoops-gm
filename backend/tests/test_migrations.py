"""Migration tests.

The Definition of Done says the migration must run cleanly from empty. That
claim is worth exactly as much as the test that makes it, so it is made here
against a real, throwaway database rather than asserted in a README.

The second test is the one that keeps earning its keep: it fails whenever a
model changes without a migration, which is the single most common way a
local-first app breaks mid-season.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from hoops_gm.db.base import Base


@pytest.fixture
def alembic_config(backend_dir: Path, tmp_path: Path) -> Config:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}")
    return config


def test_there_is_exactly_one_head(alembic_config: Config) -> None:
    """Two heads means someone branched the history and CI should say so."""
    script = ScriptDirectory.from_config(alembic_config)

    assert len(script.get_heads()) == 1


def test_upgrade_from_empty_creates_every_table(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    engine = create_engine(alembic_config.get_main_option("sqlalchemy.url", ""))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "alembic_version" in tables
    assert set(Base.metadata.tables) <= tables


def test_the_migration_records_its_revision(alembic_config: Config) -> None:
    """A migration that applies the schema but not the version row is a trap.

    It happened during Phase 1: a PRAGMA issued on the connection in env.py
    made Alembic treat the transaction as externally managed, so the DDL landed
    but alembic_version stayed empty and the next upgrade tried to recreate
    everything.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(alembic_config.get_main_option("sqlalchemy.url", ""))
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        script = ScriptDirectory.from_config(alembic_config)
        assert current == script.get_current_head()
    finally:
        engine.dispose()


def test_models_and_migrations_agree(alembic_config: Config) -> None:
    """Fails on any model change that has no migration behind it."""
    command.upgrade(alembic_config, "head")

    engine = create_engine(alembic_config.get_main_option("sqlalchemy.url", ""))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "target_metadata": Base.metadata,
                    "include_object": lambda _obj, name, type_, *_rest: (
                        not (type_ == "table" and name == "alembic_version")
                    ),
                },
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"models and migrations disagree: {diff}"


def test_downgrade_to_base_is_possible(alembic_config: Config) -> None:
    """Migrations are forward-only in practice, but a stuck upgrade needs a way back."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = create_engine(alembic_config.get_main_option("sqlalchemy.url", ""))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert set(Base.metadata.tables) & tables == set()
