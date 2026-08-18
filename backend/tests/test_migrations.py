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
from sqlalchemy.exc import IntegrityError

from hoops_gm.db.base import Base, enum_check_constraint_names
from hoops_gm.db.models.enums import ExternalSource, FieldEvidence


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


def test_absence_split_activation_migration_allows_recurring_fingerprints(
    alembic_config: Config, migration_url: str
) -> None:
    command.upgrade(alembic_config, "0006")
    insert_run = text(
        """
        INSERT INTO absence_split_runs (
            id,
            season, season_type, evidence_version, input_fingerprint,
            schedule_version, schedule_refreshed_at, computed_at,
            result_count, skipped_one_sided_pairs
        ) VALUES (
            :id,
            '2025-26', 'regular', 'absence-splits-descriptive-v2', 'same-input',
            'schedule-v1', '2026-08-18 12:00:00', :computed_at, 1, 0
        )
        """
    )
    insert_split = text(
        """
        INSERT INTO absence_splits (
            id, run_id, beneficiary_player_id, absent_player_id, team_id,
            games_with, games_without, observed_absence_games,
            production_with, production_without, descriptive_deltas,
            uncertainty, provenance
        ) VALUES (
            :id, :run_id, 100, 101, 100, 1, 1, 1,
            '{}', '{}', '{}', '{}', '{}'
        )
        """
    )
    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO nba_teams (
                        id, nba_team_id, abbreviation, name, is_active
                    ) VALUES (100, 100, 'TST', 'Test Team', true)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO players (id, full_name, normalized_name, status)
                    VALUES
                        (100, 'Beneficiary', 'beneficiary', 'unknown'),
                        (101, 'Absent', 'absent', 'unknown')
                    """
                )
            )
            connection.execute(
                insert_run,
                {"id": 100, "computed_at": "2026-08-18 12:01:00"},
            )
            connection.execute(insert_split, {"id": 100, "run_id": 100})
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert_run,
                {"id": 101, "computed_at": "2026-08-18 12:02:00"},
            )

        command.upgrade(alembic_config, "head")

        with engine.begin() as connection:
            preserved = connection.scalar(text("SELECT COUNT(*) FROM absence_splits"))
            connection.execute(
                insert_run,
                {"id": 101, "computed_at": "2026-08-18 12:03:00"},
            )
            connection.execute(insert_split, {"id": 101, "run_id": 101})
        assert preserved == 1

        command.downgrade(alembic_config, "0006")

        with engine.connect() as connection:
            run_ids = connection.scalars(
                text("SELECT id FROM absence_split_runs ORDER BY id")
            ).all()
            split_run_ids = connection.scalars(
                text("SELECT run_id FROM absence_splits ORDER BY run_id")
            ).all()
        assert run_ids == [101]
        assert split_run_ids == [101]
    finally:
        engine.dispose()


def test_0006_preserves_and_backfills_existing_provenance(
    alembic_config: Config, migration_url: str
) -> None:
    command.upgrade(alembic_config, "0005")
    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO nba_teams "
                    "(id, nba_team_id, abbreviation, name, is_active, created_at, updated_at) "
                    "VALUES "
                    "(1, 1, 'AAA', 'Alpha', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "(2, 2, 'BBB', 'Beta', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO nba_games "
                    "(id, season, season_type, nba_game_id, game_date, status, "
                    "home_team_id, away_team_id, created_at, updated_at) "
                    "VALUES (1, '2026-27', 'regular', 'game-1', '2026-10-20', "
                    "'scheduled', 1, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO team_schedule "
                    "(id, season, season_type, game_id, team_id, opponent_team_id, "
                    "game_date, is_home, created_at, updated_at) "
                    "VALUES (1, '2026-27', 'regular', 1, 1, 2, '2026-10-20', true, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO opponent_context "
                    "(id, season, game_date, team_schedule_id, team_id, opponent_team_id, "
                    "is_home, pace_possessions, pace_window_games, category_defence, "
                    "defence_window_games, blowout_probability, garbage_time_suppression, "
                    "input_snapshot, model_version, schedule_version, schedule_refreshed_at, "
                    "computed_at, created_at, updated_at) "
                    "VALUES (1, '2026-27', '2026-10-20', 1, 1, 2, true, 100.0, 10, '{}', "
                    "10, 0.25, 0.1, '{}', 'model-v1', 'schedule-v1', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO off_night_slates "
                    "(id, season, slate_date, scheduled_game_count, scheduled_team_count, "
                    "is_off_night, light_slate_percentile, threshold_games, "
                    "threshold_percentile, model_version, schedule_version, "
                    "schedule_refreshed_at, computed_at, created_at, updated_at) "
                    "VALUES (1, '2026-27', '2026-10-20', 1, 2, true, 0.1, 3, 0.2, "
                    "'model-v1', 'schedule-v1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO refresh_runs "
                    "(id, artifact_type, version, season, source, summary, refreshed_at, "
                    "created_at, updated_at) VALUES "
                    "(1, 'schedule', 'schedule-v1', '2026-27', 'legacy', '{}', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                    "(2, 'model', 'model-v1', NULL, 'legacy', '{}', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "0006")
    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection:
            refresh_rows = connection.execute(
                text(
                    "SELECT artifact_type, artifact_key, season_key "
                    "FROM refresh_runs ORDER BY artifact_type"
                )
            ).all()
            context = connection.execute(
                text("SELECT source_version, garbage_time_suppression FROM opponent_context")
            ).one()
            slate = connection.execute(
                text("SELECT source_version, input_snapshot FROM off_night_slates")
            ).one()

        assert [tuple(row) for row in refresh_rows] == [
            ("model", "default", "*"),
            ("schedule", "nba-schedule", "2026-27"),
        ]
        assert context == ("legacy-unbound", 0.1)
        assert slate[0] == "legacy-unbound"
        assert slate[1] in ({}, "{}")

        inspector = inspect(engine)
        for table, column in (
            ("refresh_runs", "artifact_key"),
            ("refresh_runs", "season_key"),
            ("opponent_context", "source_version"),
            ("off_night_slates", "source_version"),
            ("off_night_slates", "input_snapshot"),
        ):
            columns = {item["name"]: item for item in inspector.get_columns(table)}
            assert columns[column]["default"] is None

        with engine.begin() as connection:
            connection.execute(
                text("UPDATE opponent_context SET garbage_time_suppression = NULL WHERE id = 1")
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("UPDATE opponent_context SET blowout_probability = 1.1 WHERE id = 1")
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text("UPDATE off_night_slates SET scheduled_game_count = -1 WHERE id = 1")
            )
    finally:
        engine.dispose()


def test_0006_refuses_a_lossy_downgrade_before_altering_schema(
    alembic_config: Config, migration_url: str
) -> None:
    command.upgrade(alembic_config, "0006")
    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO refresh_runs "
                    "(artifact_type, artifact_key, version, season, season_key, source, "
                    "summary, refreshed_at, created_at, updated_at) VALUES "
                    "('source', 'schedule-context-observations', 'source-v1', NULL, '*', "
                    "'fixture', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="refusing lossy 0006 downgrade"):
        command.downgrade(alembic_config, "0005")

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            source_rows = connection.scalar(
                text("SELECT COUNT(*) FROM refresh_runs WHERE artifact_type = 'source'")
            )
        assert revision == "0006"
        assert source_rows == 1
        assert "artifact_key" in {
            column["name"] for column in inspect(engine).get_columns("refresh_runs")
        }
    finally:
        engine.dispose()


def test_0006_refuses_to_discard_a_custom_schedule_scope(
    alembic_config: Config, migration_url: str
) -> None:
    command.upgrade(alembic_config, "0006")
    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO refresh_runs "
                    "(artifact_type, artifact_key, version, season, season_key, source, "
                    "summary, refreshed_at, created_at, updated_at) VALUES "
                    "('schedule', 'alternate-feed', 'schedule-v1', '2026-27', '2026-27', "
                    "'fixture', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="keyed schedule lineage outside nba-schedule"):
        command.downgrade(alembic_config, "0005")

    engine = create_engine(migration_url)
    try:
        with engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
        assert revision == "0006"
        assert "artifact_key" in {
            column["name"] for column in inspect(engine).get_columns("refresh_runs")
        }
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


def test_every_enum_column_has_its_own_check_listing_every_member(
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

    **Scoped per constraint, not per table.** The first version of this test
    joined every CHECK on a table into one string and searched that, so it only
    proved a literal appeared *somewhere* on the table. ``name_evidence``,
    ``team_evidence``, ``position_evidence`` and ``suffix_evidence`` all carry
    ``{agree, disagree, unknown}`` — so any three of those four CHECKs could
    have been missing from the migration entirely and it would still have
    passed. Those four columns are the R7 evidence mechanism.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        inspector = inspect(engine)
        problems: dict[str, str] = {}
        for table in Base.metadata.tables.values():
            constraints = {
                str(c.get("name") or ""): str(c.get("sqltext", ""))
                for c in inspector.get_check_constraints(table.name)
            }
            for column in table.columns:
                members = getattr(column.type, "enums", None)
                type_name = getattr(column.type, "name", None)
                if not members or not type_name:
                    continue

                # The naming convention makes this deterministic:
                # ck_<table>_<enum type name>.
                expected = f"ck_{table.name}_{type_name}"
                sqltext = constraints.get(expected)
                where = f"{table.name}.{column.name}"
                if sqltext is None:
                    problems[where] = (
                        f"no CHECK named {expected!r}; the table has {sorted(constraints)}"
                    )
                    continue
                if column.name not in sqltext:
                    problems[where] = f"{expected!r} does not constrain this column: {sqltext!r}"
                    continue
                missing = sorted(v for v in members if f"'{v}'" not in sqltext)
                if missing:
                    problems[where] = f"{expected!r} omits {missing}"
    finally:
        engine.dispose()

    assert not problems, (
        "enum columns whose migrated CHECK does not match the model: "
        f"{problems}. Autogenerate does not detect a widened enum — the "
        "migration has to drop and recreate the CHECK by hand, as 0002 does."
    )


def test_a_migrated_database_accepts_every_external_source_and_rejects_others(
    alembic_config: Config, migration_url: str
) -> None:
    """The behavioural version of the test above: insert, do not inspect.

    Reflection proves a constraint's *text*. This proves its *effect*, on the
    table where getting it wrong is most expensive — and through raw SQL, so it
    bypasses SQLAlchemy's Python-side enum validation. That validation is what
    made the original Phase 1 enum bug invisible: the ORM rejected bad values
    before they ever reached a database that would have accepted them.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO players (id, full_name, normalized_name, status, "
                    "created_at, updated_at) VALUES (1, 'X', 'x', 'active', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        insert = text(
            "INSERT INTO player_external_ids (player_id, source, external_id, "
            "confidence, match_method, is_manual_override, name_evidence, "
            "team_evidence, position_evidence, suffix_evidence, created_at, "
            "updated_at) VALUES (1, :source, :external_id, 1.0, 'fuzzy', false, "
            ":evidence, 'unknown', 'unknown', 'unknown', CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"
        )
        bad_insert = text(
            "INSERT INTO player_external_ids (player_id, source, external_id, "
            "confidence, match_method, is_manual_override, name_evidence, "
            "team_evidence, position_evidence, suffix_evidence, created_at, "
            "updated_at) VALUES (1, :source, :external_id, 1.0, 'fuzzy', false, "
            ":name_evidence, :team_evidence, :position_evidence, :suffix_evidence, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )

        for index, source in enumerate(ExternalSource):
            with engine.begin() as connection:
                connection.execute(
                    insert,
                    {
                        "source": source.value,
                        "external_id": f"ext-{index}",
                        "evidence": FieldEvidence.AGREE.value,
                    },
                )

        for evidence in FieldEvidence:
            with engine.begin() as connection:
                connection.execute(
                    insert,
                    {
                        "source": ExternalSource.MANUAL.value,
                        "external_id": f"ev-{evidence.value}",
                        "evidence": evidence.value,
                    },
                )

        # And the constraint must actually refuse something — in every evidence
        # column, not just the first. A bogus value rejected only by
        # `name_evidence` would leave the other three CHECKs untested, which is
        # the exact shape of the bug this pair of tests replaced.
        bad_cases: list[tuple[str, dict[str, str]]] = [
            ("bad-source", {"source": "espn-totally-bogus"}),
            ("bad-name", {"name_evidence": "maybe"}),
            ("bad-team", {"team_evidence": "maybe"}),
            ("bad-position", {"position_evidence": "maybe"}),
            ("bad-suffix", {"suffix_evidence": "maybe"}),
        ]
        for external_id, override in bad_cases:
            params = {
                "source": ExternalSource.NBA.value,
                "external_id": external_id,
                "name_evidence": FieldEvidence.AGREE.value,
                "team_evidence": FieldEvidence.UNKNOWN.value,
                "position_evidence": FieldEvidence.UNKNOWN.value,
                "suffix_evidence": FieldEvidence.UNKNOWN.value,
                **override,
            }
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(bad_insert, params)
    finally:
        engine.dispose()


def test_the_evidence_default_is_pessimistic_in_a_migrated_database(
    alembic_config: Config, migration_url: str
) -> None:
    """The pessimistic default has to hold on the paths that bypass Python.

    ``name_evidence`` and friends default to ``unknown`` at the **server**, not
    only in Python, so a raw ``text()`` insert, a data migration or a bulk load
    cannot silently claim evidence nobody gathered. That is the same property
    ``confidence`` and ``match_method`` already have, and the same reasoning as
    the Phase 1 enum-CHECK finding: a guarantee that only exists in the ORM is
    not a guarantee about the database.

    Asserted here on the *migrated* schema, and in ``test_schema.py`` on the
    ``create_all`` one, because those are two different code paths and Phase 2
    already found them disagreeing once.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO players (id, full_name, normalized_name, status, "
                    "created_at, updated_at) VALUES (1, 'X', 'x', 'active', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            # Every evidence column omitted on purpose.
            connection.execute(
                text(
                    "INSERT INTO player_external_ids (player_id, source, external_id, "
                    "confidence, match_method, is_manual_override, created_at, "
                    "updated_at) VALUES (1, 'nba', 'x1', 0.0, 'fuzzy', false, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            row = connection.execute(
                text(
                    "SELECT name_evidence, team_evidence, position_evidence, "
                    "suffix_evidence FROM player_external_ids WHERE external_id = 'x1'"
                )
            ).one()
    finally:
        engine.dispose()

    assert list(row) == [FieldEvidence.UNKNOWN.value] * 4, (
        "a caller that states no evidence must claim none; anything else "
        "invents the very thing these columns exist to make explicit"
    )


def test_a_migrated_league_settings_snapshot_enforces_its_check_constraints(
    alembic_config: Config, migration_url: str
) -> None:
    """The version and payload-hash CHECKs, asserted behaviourally on a real migration.

    Reflection would only prove the CHECK's text exists; this proves its
    effect, and through raw SQL so it bypasses any Python-side validation the
    ORM might otherwise be doing on the app's behalf.
    """
    command.upgrade(alembic_config, "head")

    engine = create_engine(migration_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO leagues (id, name, season, scoring_type, draft_type, "
                    "is_active, created_at, updated_at) VALUES (1, 'Test League', "
                    "'2026-27', 'h2h_categories', 'unknown', true, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                )
            )

        valid_sha256 = "a" * 64
        insert = text(
            "INSERT INTO league_settings_snapshots (league_id, version, schema_version, "
            "settings, source_summary, source_payload_sha256, observed_at, created_at, "
            "updated_at) VALUES (1, :version, 'v1', :settings, :source_summary, :sha256, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        with engine.begin() as connection:
            connection.execute(
                insert,
                {
                    "version": 1,
                    "settings": '{"trade_deadline": null}',
                    "source_summary": "{}",
                    "sha256": valid_sha256,
                },
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert,
                {
                    "version": 0,
                    "settings": "{}",
                    "source_summary": "{}",
                    "sha256": valid_sha256,
                },
            )

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert,
                {
                    "version": 2,
                    "settings": "{}",
                    "source_summary": "{}",
                    "sha256": "too-short",
                },
            )
    finally:
        engine.dispose()


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
                    # Matches alembic/env.py. Without it this test was strictly
                    # weaker than `alembic check` in exactly the dimension the
                    # pessimistic-evidence-default guarantee lives in: a server
                    # default present in the models and absent from the
                    # migration would not have been reported.
                    "compare_server_default": True,
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
