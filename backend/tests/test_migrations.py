"""Migration tests.

The Definition of Done says the migration must run cleanly from empty. That
claim is worth exactly as much as the test that makes it, so it is made here
against a real, throwaway database rather than asserted in a README.

``test_models_and_migrations_agree`` is the one that keeps earning its keep: it
fails whenever a model changes without a migration, which is the single most
common way a local-first app breaks mid-season.

Set ``TEST_DATABASE_URL`` to run all of this against Postgres instead of
SQLite. CI does.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from hoops_gm.db.base import Base, enum_check_constraint_names


@pytest.fixture
def migration_url(tmp_path: Path, test_database_url: str | None) -> str:
    return test_database_url or f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"


@pytest.fixture
def alembic_config(backend_dir: Path, migration_url: str) -> Config:
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    # config.attributes, not set_main_option: main options live in a
    # ConfigParser using BasicInterpolation, so a URL containing '%' — the
    # normal case for a URL-encoded Postgres password — raises on read.
    config.attributes["sqlalchemy_url"] = migration_url
    return config


@pytest.fixture(autouse=True)
def _clean_database(migration_url: str) -> Iterator[None]:
    """Leave no tables behind. A Postgres test database is reused across tests."""
    yield
    engine = create_engine(migration_url)
    try:
        Base.metadata.drop_all(engine)
        with engine.connect() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
            connection.commit()
    finally:
        engine.dispose()


def test_there_is_exactly_one_head(alembic_config: Config) -> None:
    """Two heads means someone branched the history and CI should say so."""
    script = ScriptDirectory.from_config(alembic_config)

    assert len(script.get_heads()) == 1


def test_upgrade_from_empty_creates_every_table(alembic_config: Config, migration_url: str) -> None:
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "alembic_version" in tables
    assert set(Base.metadata.tables) <= tables


def test_the_migration_records_its_revision(alembic_config: Config, migration_url: str) -> None:
    """A migration that applies the schema but not the version row is a trap.

    It happened during Phase 1: a PRAGMA issued on the connection in env.py
    made Alembic treat the transaction as externally managed, so the DDL landed
    but alembic_version stayed empty and the next upgrade tried to recreate
    everything.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        script = ScriptDirectory.from_config(alembic_config)
        assert current == script.get_current_head()
    finally:
        engine.dispose()


def test_the_migration_creates_the_enum_check_constraints(
    alembic_config: Config, migration_url: str
) -> None:
    """Review finding 1, asserted against the migration rather than the models.

    ``create_constraint=True`` has to survive autogeneration into the migration
    file, or the models carry a guarantee the database was never given.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        inspector = inspect(engine)
        definitions = " ".join(
            str(constraint.get("sqltext", ""))
            for table in ("player_external_ids", "nba_games", "player_season_stats")
            for constraint in inspector.get_check_constraints(table)
        )
    finally:
        engine.dispose()

    assert "fantrax" in definitions, "no CHECK lists the permitted external sources"
    assert "regular" in definitions, "no CHECK lists the permitted season types"


def test_every_enum_member_is_accepted_by_a_migrated_database(
    alembic_config: Config, migration_url: str
) -> None:
    """Phase 2 review finding: adding an enum member produces no migration.

    ``enum_check_constraint_names`` excludes enum CHECKs from autogenerate
    comparison — necessary, or every ``alembic check`` reports one spurious
    removal per enum column. The consequence is that **widening an enum is
    invisible to autogenerate and to drift detection**, so the CHECK keeps the
    old value list while the models advertise the new one.

    That is not hypothetical. Phase 2 added three ``ExternalSource`` members,
    autogenerate emitted nothing for them, and
    ``INSERT INTO player_external_ids (source) VALUES ('fantrax_sportradar')``
    was rejected by a **migrated** database while succeeding against one built
    by ``Base.metadata.create_all`` — which is what the rest of this suite
    uses. Green tests, broken production, no drift reported.

    So this compares the two paths directly, on the real database, for every
    enum member. The next person to add one finds out here.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        inspector = inspect(engine)
        by_table_column: dict[tuple[str, str], set[str]] = {}
        for table in Base.metadata.tables.values():
            reflected = " ".join(
                str(constraint.get("sqltext", ""))
                for constraint in inspector.get_check_constraints(table.name)
            )
            for column in table.columns:
                enum_type = getattr(column.type, "enums", None)
                if not enum_type:
                    continue
                missing = {value for value in enum_type if f"'{value}'" not in reflected}
                if missing:
                    by_table_column[(table.name, column.name)] = missing
    finally:
        engine.dispose()

    assert not by_table_column, (
        "these enum values are declared on the models but are not permitted by "
        f"the migrated database's CHECK constraints: {by_table_column}. "
        "Autogenerate does not detect a widened enum — the migration has to "
        "drop and recreate the CHECK by hand, as 0002 does."
    )


def test_models_and_migrations_agree(alembic_config: Config, migration_url: str) -> None:
    """Fails on any model change that has no migration behind it."""
    command.upgrade(alembic_config, "head")

    enum_checks = enum_check_constraint_names(Base.metadata)

    def _include(_obj: object, name: str | None, type_: str, *_rest: object) -> bool:
        if type_ == "table" and name == "alembic_version":
            return False
        # Autogenerate reflects enum CHECKs from the database but skips them in
        # metadata, so leaving them in reports 18 phantom removals forever.
        return not (type_ == "check_constraint" and name in enum_checks)

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "target_metadata": Base.metadata,
                    "include_object": _include,
                },
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"models and migrations disagree: {diff}"


def test_downgrade_to_base_is_possible(alembic_config: Config, migration_url: str) -> None:
    """Migrations are forward-only in practice, but a stuck upgrade needs a way back."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = create_engine(migration_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert set(Base.metadata.tables) & tables == set()


def test_a_url_containing_a_percent_sign_does_not_crash_alembic(
    backend_dir: Path, tmp_path: Path
) -> None:
    """Review finding 6.

    A URL-encoded Postgres password (``%40`` for ``@``, ``%23`` for ``#``) used
    to raise a ConfigParser interpolation error with nothing in the message to
    suggest why — at exactly the moment ADR-001's "config change plus a data
    migration" gets exercised for the first time.
    """
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    url = f"sqlite:///{(tmp_path / 'pct%40db%23x.db').as_posix()}"
    config.attributes["sqlalchemy_url"] = url

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        assert "players" in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_a_settings_url_with_a_percent_sign_survives_env_py(
    monkeypatch: pytest.MonkeyPatch, backend_dir: Path, tmp_path: Path
) -> None:
    """The same path, but arriving through DATABASE_URL rather than an override."""
    url = f"sqlite:///{(tmp_path / 'env%40pct.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)

    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        assert "players" in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
