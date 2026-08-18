"""Portability guarantees for the SQLite → Postgres seam (ADR-001).

ADR-001 says the move to Postgres must be a configuration change, not a
rewrite. That only stays true if it is checked. These tests are the check.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import DefaultClause

from hoops_gm.core.config import Settings
from hoops_gm.db.base import NAMING_CONVENTION, Base
from hoops_gm.db.session import Database

# Every module may use SQLAlchemy. Only engine construction may know which
# database is behind it.
_DIALECT_AWARE_MODULES = {"session.py", "config.py"}
#: Dialect *branching* — asking which database this is in order to behave
#: differently, or passing a dialect-specific keyword. Logging the dialect is
#: fine; branching on it is not.
_DIALECT_BRANCH_PATTERN = re.compile(
    r"dialect\.name\s*(==|!=|\bin\b)|dialect_name\s*(==|!=)|is_sqlite"
    r"|sqlite_\w+\s*=|postgresql_\w+\s*=|\.with_variant\("
)


def _source_files() -> list[Path]:
    package_root = Path(__file__).resolve().parents[1] / "src" / "hoops_gm"
    return sorted(package_root.rglob("*.py"))


def test_no_native_enum_types_are_declared() -> None:
    """A native Postgres enum needs a migration to add a value; VARCHAR does not."""
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, SAEnum) and column.type.native_enum
    ]

    assert offenders == []


def test_every_constraint_and_index_is_named() -> None:
    """Unnamed constraints get different names on each dialect and cannot be dropped."""
    unnamed: list[str] = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if constraint.name is None:
                unnamed.append(f"{table.name}: {type(constraint).__name__}")
        unnamed.extend(f"{table.name}: index" for index in table.indexes if not index.name)

    assert unnamed == []


def test_constraint_names_fit_postgres_identifier_limit() -> None:
    """Postgres silently truncates at 63 characters, which collides names."""
    names: list[str] = []
    for table in Base.metadata.tables.values():
        names.extend(c.name for c in table.constraints if isinstance(c.name, str))
        names.extend(i.name for i in table.indexes if isinstance(i.name, str))

    too_long = [name for name in names if len(name) > 63]

    assert too_long == []


def test_naming_convention_is_applied_to_the_metadata() -> None:
    assert dict(Base.metadata.naming_convention) == NAMING_CONVENTION


def test_no_module_outside_engine_construction_branches_on_dialect() -> None:
    """The discipline ADR-001 asks for, enforced rather than remembered."""
    offenders: list[str] = []
    for path in _source_files():
        if path.name in _DIALECT_AWARE_MODULES:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if _DIALECT_BRANCH_PATTERN.search(code):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")

    assert offenders == []


def test_no_raw_driver_sql_in_the_package() -> None:
    """Raw driver SQL is where dialect differences hide."""
    offenders: list[str] = []
    for path in _source_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "exec_driver_sql" in line.split("#", 1)[0]:
                offenders.append(f"{path.name}:{lineno}")

    assert offenders == []


@pytest.mark.sqlite_only
def test_sqlite_enforces_foreign_keys(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{(tmp_path / 'fk.db').as_posix()}",
        _env_file=None,
    )
    database = Database.from_settings(settings)
    try:
        with database.session() as session:
            enabled = session.execute(text("PRAGMA foreign_keys")).scalar_one()
        assert enabled == 1
    finally:
        database.dispose()


def test_every_model_is_registered_and_created(session: Session) -> None:
    """Guards against a model that was never imported into db.models."""
    inspector = inspect(session.get_bind())
    created = set(inspector.get_table_names())

    assert set(Base.metadata.tables) <= created


@pytest.mark.parametrize(
    "group,expected",
    [
        ("identity", {"nba_teams", "players", "player_external_ids"}),
        ("stats", {"nba_games", "player_game_logs", "player_season_stats"}),
        (
            "league",
            {
                "leagues",
                "league_scoring_profiles",
                "league_scoring_categories",
                "fantasy_teams",
                "roster_slots",
                "rosters",
                "scoring_periods",
                "matchups",
                "matchup_category_results",
                "transactions",
            },
        ),
        ("schedule", {"team_schedule", "opponent_context", "off_night_slates"}),
    ],
)
def test_phase_one_entity_groups_are_present(group: str, expected: set[str]) -> None:
    assert expected <= set(Base.metadata.tables), group


def test_later_phase_entity_groups_are_absent() -> None:
    """Projections, valuation, draft and bridge belong to other agents.

    ``player_participation`` was on this list until Phase 2 and has been
    removed deliberately, because the boundary it was drawing turned out to be
    in the wrong place. The plan groups the whole of Availability together, but
    the group contains two different kinds of thing:

    * what a source **said happened** — who played, who was inactive, what
      reason was given. That is an observation, it arrives through an adapter,
      and capturing it is what ingest is for;
    * what a model **infers from that** — ``p(play)``, reliability, shutdown
      risk. Those are `quant`'s and are still absent below.

    DNP reasons and inactive lists cannot be ingested without somewhere to put
    them, and the alternative — ingesting them into a table `quant` has not
    designed yet — is worse than agreeing the split here. Keeping the two apart
    also stops a model's output from later being mistaken for an observation,
    which is the failure this project can least afford.

    ``injury_reports`` stays absent: the NBA injury report is a Phase 4 source
    and nothing ingests it yet.
    """
    not_yet = {
        "injury_reports",
        "availability_predictions",
        "reliability_metrics",
        "shutdown_risk",
        "usage_redistribution",
        "stock_movements",
        "projections",
        "blended_projections",
        "expected_games",
        "valuations",
        "risk_adjusted_valuations",
        "drafts",
        "draft_picks",
        "automation_actions",
    }

    assert not_yet & set(Base.metadata.tables) == set()


def test_the_observed_participation_ledger_is_present() -> None:
    """Phase 2 owns the observed half of Availability. See the note above."""
    assert "player_participation" in Base.metadata.tables
    columns = set(Base.metadata.tables["player_participation"].columns.keys())
    # The two columns that exist because of what the sources actually do.
    assert "raw_comment" in columns, (
        "the normalisation of a DNP reason will be wrong at first and must be "
        "re-derivable from the source's own words"
    )
    assert "inactive_list_available" in columns, (
        "'nobody was inactive' and 'the source stopped telling us' are different "
        "facts, and BoxScoreSummaryV2 erased the difference for a whole season"
    )


def test_absence_splits_are_descriptive_observation_evidence() -> None:
    run_table = Base.metadata.tables["absence_split_runs"]
    table = Base.metadata.tables["absence_splits"]
    columns = set(table.columns.keys())

    assert {
        "season",
        "season_type",
        "evidence_version",
        "input_fingerprint",
        "schedule_version",
        "result_count",
        "skipped_one_sided_pairs",
    } <= set(run_table.columns.keys())
    assert {
        "run_id",
        "games_with",
        "games_without",
        "observed_absence_games",
        "provenance",
        "uncertainty",
    } <= columns
    assert {
        "inferred_absence_games",
        "excluded_unknown_games",
        "membership_method",
    }.isdisjoint(columns)
    data_layer_default = table.c.data_layer.server_default
    claim_type_default = table.c.claim_type.server_default
    assert isinstance(data_layer_default, DefaultClause)
    assert isinstance(claim_type_default, DefaultClause)
    assert data_layer_default.arg == "observations"
    assert claim_type_default.arg == "descriptive"


def test_schedule_context_tables_are_present() -> None:
    """The phase-4 quant context tables are now explicit model outputs."""
    assert "opponent_context" in Base.metadata.tables
    assert "off_night_slates" in Base.metadata.tables
    context_columns = set(Base.metadata.tables["opponent_context"].columns.keys())
    assert {
        "team_schedule_id",
        "model_version",
        "schedule_version",
        "schedule_refreshed_at",
        "category_defence",
    }.issubset(context_columns)
    slate_columns = set(Base.metadata.tables["off_night_slates"].columns.keys())
    assert {
        "scheduled_game_count",
        "is_off_night",
        "model_version",
        "schedule_version",
        "schedule_refreshed_at",
    }.issubset(slate_columns)


def test_the_raw_bridge_payload_table_is_present() -> None:
    """Bridge captures are raw observations and are now part of the backend seam."""
    assert "bridge_payloads" in Base.metadata.tables
