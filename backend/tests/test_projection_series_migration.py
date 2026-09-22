"""Physical 0023 subtree preservation with FKs enabled, on both test dialects."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DataError, IntegrityError

from hoops_gm.db.base import Base
from hoops_gm.db.session import enable_sqlite_foreign_keys

_TABLES = (
    "players",
    "player_external_ids",
    "projection_sources",
    "projection_profile_versions",
    "projection_imports",
    "projections",
    "source_games_played_assumptions",
)
_SUBTREE = ("projection_imports", "projections", "source_games_played_assumptions")


@pytest.fixture
def migration_store(
    backend_dir: Path, tmp_path: Path, test_database_url: str | None
) -> Iterator[tuple[Config, Engine]]:
    url = test_database_url or f"sqlite:///{(tmp_path / 'series.db').as_posix()}"
    engine = sa.create_engine(url)
    assert engine.dialect.name == ("postgresql" if test_database_url else "sqlite"), (
        "series migration evidence must use the requested test dialect, never a fallback store"
    )
    if engine.dialect.name == "sqlite":
        enable_sqlite_foreign_keys(engine)
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.attributes["sqlalchemy_url"] = url
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    try:
        yield config, engine
    finally:
        # A defective rebuild can leave its scratch parent outside ORM metadata.
        # Clean it only after the test has asserted complete rollback.
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_projection_imports"))
        Base.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
        engine.dispose()


def _table(connection: Connection, name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), autoload_with=connection)


def _populate_0023(connection: Connection) -> None:
    when = datetime(2026, 9, 1, 12, 30, tzinfo=UTC)
    connection.execute(
        _table(connection, "players").insert(),
        {
            "id": 101,
            "full_name": "Synthetic Migration Player",
            "normalized_name": "synthetic migration player",
            "status": "unknown",
        },
    )
    connection.execute(
        _table(connection, "player_external_ids").insert(),
        {
            "id": 201,
            "player_id": 101,
            "source": "basketball_monster",
            "current_for_source": "basketball_monster",
            "external_id": "synthetic-migration-101",
            "confidence": 1.0,
            "match_method": "manual_override",
            "is_manual_override": True,
            "notes": "synthetic migration sentinel",
        },
    )
    connection.execute(
        _table(connection, "projection_sources").insert(),
        {
            "id": 1,
            "source": "basketball_monster",
            "display_name": "Synthetic migration publisher",
            "assumed_scoring_type": "h2h_categories",
            "notes": "preserve publisher default",
        },
    )
    connection.execute(
        _table(connection, "projection_profile_versions").insert(),
        {
            "id": 2,
            "source_id": 1,
            "profile_id": "synthetic-migration",
            "profile_version": "1",
            "verified": False,
            "verified_seasons": [],
            "verification_evidence": "Structural fixture, not release admission",
            "definition_sha256": "a" * 64,
            "definition": {"sentinel": ["retain", 7]},
        },
    )
    for index, season in enumerate(("2025-26", "2026-27")):
        connection.execute(
            _table(connection, "projection_imports").insert(),
            {
                "id": 11 + index,
                "source_id": 1,
                "profile_version_id": 2,
                "season": season,
                "imported_at": when,
                "content_sha256": str(index + 1) * 64,
                "profile_id": "synthetic-migration",
                "profile_version": "1",
                "profile_verified": False,
                "profile_definition_sha256": "a" * 64,
                "profile_lineage": {"sentinel": [index, None, {"unchanged": True}]},
                "original_filename": f"synthetic-unknown-variant-{index}.csv",
                "row_count": 3,
                "matched_count": 1,
                "needs_review_count": 1,
                "unmatched_count": 0,
                "rejected_count": 1,
                "assumed_scoring_type": None,
                "raw_payload_ref": "synthetic:never-read",
                "notes": "Do not infer a variant",
                "created_at": when,
                "updated_at": when,
            },
        )
        connection.execute(
            _table(connection, "projections").insert(),
            {
                "id": 31 + index,
                "projection_import_id": 11 + index,
                "player_id": 101,
                "season": season,
                "points_per_game": 7.25 + index,
                "field_goals_made_per_game": 2.0,
                "field_goals_attempted_per_game": 4.0,
                "free_throws_made_per_game": 1.25,
                "free_throws_attempted_per_game": 2.0,
                "created_at": when,
                "updated_at": when,
            },
        )
        connection.execute(
            _table(connection, "source_games_played_assumptions").insert(),
            {
                "id": 41 + index,
                "projection_id": 31 + index,
                "assumed_games_played": 68.5 + index,
                "assumed_games_played_raw": f"{68.5 + index} GP",
                "notes": "preserve raw source text",
                "created_at": when,
                "updated_at": when,
            },
        )


def _snapshot(connection: Connection) -> dict[str, list[dict[str, object]]]:
    return {
        name: [
            dict(row)
            for row in connection.execute(sa.select(table).order_by(table.c.id)).mappings()
        ]
        for name in _TABLES
        for table in (_table(connection, name),)
    }


def _schema(connection: Connection) -> dict[str, object]:
    inspector = sa.inspect(connection)
    return {
        name: {
            "columns": [
                {**column, "type": str(column["type"])} for column in inspector.get_columns(name)
            ],
            "foreign_keys": inspector.get_foreign_keys(name),
            "checks": inspector.get_check_constraints(name),
            "unique": inspector.get_unique_constraints(name),
            "indexes": inspector.get_indexes(name),
        }
        for name in _SUBTREE
    }


def _revision(connection: Connection) -> str:
    return str(connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one())


def test_full_physical_0023_fk_closure(migration_store: tuple[Config, Engine]) -> None:
    config, engine = migration_store
    command.upgrade(config, "0023")
    inspector = sa.inspect(engine)
    edges = {
        (table, fk["referred_table"], fk.get("options", {}).get("ondelete"))
        for table in inspector.get_table_names()
        for fk in inspector.get_foreign_keys(table)
    }
    reached = {"projection_imports"}
    while expanded := {table for table, parent, _ in edges if parent in reached} - reached:
        reached |= expanded
    assert reached == set(_SUBTREE)
    assert {(table, parent, action) for table, parent, action in edges if parent in reached} == {
        ("projections", "projection_imports", "CASCADE"),
        ("source_games_played_assumptions", "projections", "CASCADE"),
    }
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_populated_upgrade_preserves_every_column_and_constraints(
    migration_store: tuple[Config, Engine],
) -> None:
    config, engine = migration_store
    command.upgrade(config, "0023")
    with engine.begin() as connection:
        _populate_0023(connection)
        before = _snapshot(connection)
        child_schema = _schema(connection)
    command.upgrade(config, "0024")
    with engine.begin() as connection:
        after = _snapshot(connection)
        for row in after["projection_imports"]:
            assert row.pop("series_key") == "legacy"
            assert row.pop("series_display_name") is None
        assert after == before
        assert _revision(connection) == "0024"
        for table in _SUBTREE[1:]:
            assert _schema(connection)[table] == child_schema[table]
        imports = _table(connection, "projection_imports")
        original = before["projection_imports"][0]
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(imports.insert(), {**original, "id": 20})
        for number, key in enumerate(("josh", "bonus", "x" * 64), start=21):
            connection.execute(
                imports.insert(),
                {
                    **original,
                    "id": number,
                    "series_key": key,
                    "series_display_name": key.title(),
                },
            )
        for key in ("", "x" * 65):
            postgres_overlength = engine.dialect.name == "postgresql" and len(key) > 64
            expected_error = DataError if postgres_overlength else IntegrityError
            with pytest.raises(expected_error) as rejected, connection.begin_nested():
                connection.execute(
                    imports.insert(),
                    {
                        **original,
                        "id": 30,
                        "series_key": key,
                        "series_display_name": "Length boundary",
                    },
                )
            if postgres_overlength:
                assert getattr(rejected.value.orig, "sqlstate", None) == "22001"
            elif engine.dialect.name == "sqlite":
                assert (
                    str(rejected.value.orig)
                    == "CHECK constraint failed: ck_projection_imports_series_key_length"
                )
            else:
                assert getattr(rejected.value.orig, "sqlstate", None) == "23514"
                diagnostic = getattr(rejected.value.orig, "diag", None)
                assert (
                    getattr(diagnostic, "constraint_name", None)
                    == "ck_projection_imports_series_key_length"
                )
        for changes in (
            {"series_key": "missing-label", "series_display_name": None},
            {
                "series_key": "legacy",
                "series_display_name": "Josh",
                "content_sha256": "c" * 64,
            },
            {"series_key": "new", "series_display_name": " "},
            {"source_id": 999},
            {"profile_version_id": 999},
            {"content_sha256": "b" * 64, "row_count": -1},
            {"content_sha256": "b" * 64, "assumed_scoring_type": "invented"},
        ):
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(imports.insert(), {**original, "id": 30, **changes})
        projections = _table(connection, "projections")
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(projections.insert(), {**before["projections"][0], "id": 99})
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(projections.update().values(field_goals_made_per_game=100))
        assumptions = _table(connection, "source_games_played_assumptions")
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                assumptions.insert(),
                {
                    **before["source_games_played_assumptions"][0],
                    "id": 99,
                },
            )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(assumptions.update().values(assumed_games_played=101))


def test_all_legacy_downgrade_preserves_populated_subtree(
    migration_store: tuple[Config, Engine],
) -> None:
    config, engine = migration_store
    command.upgrade(config, "0023")
    with engine.begin() as connection:
        _populate_0023(connection)
        before = _snapshot(connection)
    command.upgrade(config, "0024")
    command.downgrade(config, "0023")
    with engine.connect() as connection:
        assert _revision(connection) == "0023"
        assert _snapshot(connection) == before
        assert "series_key" not in _table(connection, "projection_imports").c


def test_named_series_lossy_downgrade_refuses_before_mutation(
    migration_store: tuple[Config, Engine],
) -> None:
    config, engine = migration_store
    command.upgrade(config, "0024")
    with engine.begin() as connection:
        _populate_0023(connection)
        imports = _table(connection, "projection_imports")
        connection.execute(imports.update().values(series_key="josh", series_display_name="Josh"))
        before, schema = _snapshot(connection), _schema(connection)
    with pytest.raises(RuntimeError, match="discard explicitly declared"):
        command.downgrade(config, "0023")
    with engine.connect() as connection:
        assert _revision(connection) == "0024"
        assert _snapshot(connection) == before
        assert _schema(connection) == schema


def test_failure_during_upgrade_rolls_back_schema_revision_and_complete_subtree(
    migration_store: tuple[Config, Engine],
) -> None:
    config, engine = migration_store
    command.upgrade(config, "0023")
    with engine.begin() as connection:
        _populate_0023(connection)
        before, schema = _snapshot(connection), _schema(connection)
        table_names = sa.inspect(connection).get_table_names()
    reached: list[str] = []

    def fail_restoration(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if connection.engine.url != engine.url:
            return
        if connection.dialect.name == "sqlite":
            target = (
                statement.startswith('INSERT INTO "source_games_played_assumptions"')
                and "_series_0024_" in statement
            )
        else:
            target = statement.startswith("CREATE INDEX") and (
                "ix_projection_imports_source_series_season" in statement
            )
        if target:
            reached.append(connection.dialect.name)
            raise RuntimeError("injected series migration failure")

    sa.event.listen(Engine, "before_cursor_execute", fail_restoration)
    try:
        with pytest.raises(RuntimeError, match="injected series migration failure"):
            command.upgrade(config, "0024")
    finally:
        sa.event.remove(Engine, "before_cursor_execute", fail_restoration)
    assert reached == [engine.dialect.name]
    with engine.connect() as connection:
        assert sa.inspect(connection).get_table_names() == table_names
        assert _revision(connection) == "0023"
        assert _snapshot(connection) == before
        assert _schema(connection) == schema
    command.upgrade(config, "0024")


def test_unexpected_transitive_descendant_refuses_before_rebuild(
    migration_store: tuple[Config, Engine],
) -> None:
    config, engine = migration_store
    command.upgrade(config, "0023")
    with engine.begin() as connection:
        _populate_0023(connection)
        connection.execute(
            sa.text(
                "CREATE TABLE series_descendant_guard "
                "(id INTEGER PRIMARY KEY, assumption_id INTEGER NOT NULL "
                "REFERENCES source_games_played_assumptions(id) ON DELETE CASCADE)"
            )
        )
        connection.execute(
            sa.text("INSERT INTO series_descendant_guard (id, assumption_id) VALUES (1, 41)")
        )
        before, schema = _snapshot(connection), _schema(connection)
    try:
        with pytest.raises(RuntimeError, match="unexpected projection-import FK descendant"):
            command.upgrade(config, "0024")
        with engine.connect() as connection:
            assert _revision(connection) == "0023"
            assert _snapshot(connection) == before
            assert _schema(connection) == schema
            assert (
                connection.execute(
                    sa.text("SELECT assumption_id FROM series_descendant_guard")
                ).scalar_one()
                == 41
            )
    finally:
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TABLE series_descendant_guard"))
