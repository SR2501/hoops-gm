"""The generic projection CSV importer — ``csv-importer``, Phase 5.

Three layers, tested at their own level:

* **profiles** — pure data, no test needed beyond the parity check below.
* **parser** (``parse_projection_csv``) — pure and offline, so every
  validation rule is exercised without a database.
* **importer** (``import_projection_csv``) — the DB-writing boundary,
  covering identity resolution, versioning and idempotency.

The FantasyPros/Hashtag/Basketball Monster fixtures here are **synthetic**,
authored for this test suite — not a live capture, and not real published
projections (plan.md: projection data is personal-use only, so a purchased or
Patreon-gated CSV has no business being committed). They exist to prove the
column-mapping code path runs and to pin the *unverified* header aliases in
``profiles.py`` against a regression, not to claim the mapping matches a real
vendor file — see the caveat in that module's docstring.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource, FieldEvidence, MatchMethod
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.identity.names import normalize_name
from hoops_gm.identity.report import partition, render_summary, to_csv
from hoops_gm.ingest.projections import (
    BASKETBALL_MONSTER_PROFILE,
    CANONICAL_STAT_FIELDS,
    FANTASYPROS_PROFILE,
    HASHTAG_PROFILE,
    MANUAL_PROFILE,
    ColumnProfile,
    ProjectionProfileError,
    StatColumn,
    ValueShape,
    import_projection_csv,
    parse_projection_csv,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projections"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def seed_player(
    session: Session,
    *,
    nba_id: int,
    name: str,
    team_abbreviation: str | None = None,
    position: str | None = None,
) -> Player:
    """Create a canonical player with an NBA crosswalk link.

    Mirrors what ``import_nba_players`` produces in real ingestion, kept
    minimal here so these tests do not depend on the full NBA fixture corpus
    ``test_importers.py`` uses.
    """
    team_id = None
    if team_abbreviation:
        team = session.scalar(select(NbaTeam).where(NbaTeam.abbreviation == team_abbreviation))
        if team is None:
            team_count = session.scalar(select(func.count()).select_from(NbaTeam)) or 0
            team = NbaTeam(
                nba_team_id=1000 + team_count,
                abbreviation=team_abbreviation,
                name=f"{team_abbreviation} Team",
            )
            session.add(team)
            session.flush()
        team_id = team.id

    player = Player(
        full_name=name,
        normalized_name=normalize_name(name).key,
        primary_position=position,
        current_team_id=team_id,
    )
    session.add(player)
    session.flush()
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.NBA,
            current_for_source=ExternalSource.NBA.value,
            external_id=str(nba_id),
            external_name=name,
            normalized_name=normalize_name(name).key,
            external_team=team_abbreviation,
            confidence=1.0,
            match_method=MatchMethod.ANCHOR_ID,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()
    return player


@pytest.fixture
def seeded_players(session: Session) -> Session:
    seed_player(session, nba_id=1, name="Player Alpha", team_abbreviation="BOS", position="SF")
    seed_player(session, nba_id=2, name="Player Beta", team_abbreviation="LAL", position="PG")
    seed_player(session, nba_id=3, name="Player Gamma", team_abbreviation="DEN", position="C")
    return session


# --------------------------------------------------------------------------
# Schema/profile parity
# --------------------------------------------------------------------------


def test_canonical_stat_fields_match_the_projection_schema() -> None:
    """The same discipline ``stats.BOX_SCORE_STAT_KEYS`` uses for box scores.

    A field added to one and not the other is either a column nothing can
    ever populate, or a parsed value nothing can ever store — both are bugs
    that would otherwise wait for someone to notice by hand.
    """
    columns = set(Projection.__table__.columns.keys())
    assert set(CANONICAL_STAT_FIELDS) <= columns


def test_projection_schema_has_no_games_played_or_expected_games_column() -> None:
    """ADR-002, enforced by absence rather than merely documented."""
    columns = set(Projection.__table__.columns.keys())
    assert "games_played" not in columns
    assert "expected_games" not in columns
    assert "assumed_games_played" not in columns


# --------------------------------------------------------------------------
# Parser: happy path and per-game/season-total conversion
# --------------------------------------------------------------------------


def test_manual_profile_parses_per_game_rates_and_gp_assumption() -> None:
    result = parse_projection_csv(load("manual_sample.csv"), MANUAL_PROFILE, season="2026-27")

    assert result.total_rows == 4
    assert result.rejected_count == 0
    assert len(result.rows) == 4

    alpha = next(row for row in result.rows if row.player_name == "Player Alpha")
    assert alpha.assumed_games_played == 70
    assert alpha.assumed_games_played_raw == "70"
    assert alpha.points_per_game == 24.2
    assert alpha.field_goals_made_per_game == 8.6
    assert alpha.field_goals_attempted_per_game == 17.5
    # The raw row survives untouched, keyed by the file's own headers.
    assert alpha.raw_row["team"] == "BOS"


def test_season_total_column_is_divided_by_games_played() -> None:
    """A source publishing a season total, not a per-game rate, is common.

    ADR-002 requires the conversion to happen here rather than downstream —
    the profile states the column's shape once, and getting it wrong is
    exactly the "conflating production with a games-played assumption" bug
    the whole module exists to prevent.
    """
    profile = ColumnProfile(
        source=MANUAL_PROFILE.source,
        display_name="season-total test profile",
        name_aliases=("player_name",),
        games_played_aliases=("gp",),
        stat_columns=(
            StatColumn("points_per_game", ("points_total",), shape=ValueShape.SEASON_TOTAL),
        ),
    )
    csv_text = "player_name,gp,points_total\nPlayer Alpha,80,1600\n"
    result = parse_projection_csv(csv_text, profile, season="2026-27")

    assert result.rejected_count == 0
    assert result.rows[0].points_per_game == 20.0  # 1600 / 80


def test_season_total_without_games_played_is_a_warning_not_a_fabrication() -> None:
    profile = ColumnProfile(
        source=MANUAL_PROFILE.source,
        display_name="season-total test profile",
        name_aliases=("player_name",),
        stat_columns=(
            StatColumn("points_per_game", ("points_total",), shape=ValueShape.SEASON_TOTAL),
        ),
    )
    csv_text = "player_name,points_total\nPlayer Alpha,1600\n"
    result = parse_projection_csv(csv_text, profile, season="2026-27")

    assert result.rejected_count == 0
    assert result.rows[0].points_per_game is None
    assert any("season total" in issue.message for issue in result.warnings)


# --------------------------------------------------------------------------
# Parser: validation
# --------------------------------------------------------------------------


def test_missing_player_name_is_fatal() -> None:
    csv_text = "player_name,points_per_game\n,20.0\nPlayer Beta,18.0\n"
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.total_rows == 2
    assert result.rejected_count == 1
    assert len(result.rows) == 1
    assert result.rows[0].player_name == "Player Beta"


def test_unparsable_number_rejects_only_its_row() -> None:
    csv_text = "player_name,points_per_game\nPlayer Alpha,not-a-number\nPlayer Beta,18.0\n"
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.rejected_count == 1
    assert len(result.rows) == 1
    assert result.rows[0].player_name == "Player Beta"
    assert any(issue.fatal and "unparsable" in issue.message for issue in result.issues)


def test_games_played_outside_plausible_range_is_fatal() -> None:
    csv_text = "player_name,games_played\nPlayer Alpha,250\n"
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.rejected_count == 1
    assert result.rows == []


def test_duplicate_name_within_file_rejects_all_occurrences() -> None:
    csv_text = (
        "player_name,team,points_per_game\n"
        "Player Alpha,BOS,24.2\n"
        "Player Alpha,BOS,24.5\n"
        "Player Beta,LAL,18.0\n"
    )
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.rejected_count == 2
    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert sum("duplicate" in issue.message for issue in result.issues) == 2


def test_makes_exceeding_attempts_is_fatal() -> None:
    csv_text = (
        "player_name,field_goals_made_per_game,field_goals_attempted_per_game\n"
        "Player Alpha,10.0,8.0\n"
    )
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.rejected_count == 1
    assert result.rows == []
    assert any("exceed" in issue.message for issue in result.issues)


def test_missing_name_column_raises_a_profile_error() -> None:
    """A header mismatch this total is not a per-row problem — the whole
    file cannot be read under this profile."""
    csv_text = "totally_unrelated_column\nsomething\n"
    with pytest.raises(ProjectionProfileError):
        parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")


# --------------------------------------------------------------------------
# Parser: vendor profiles (unverified aliases; see module docstring)
# --------------------------------------------------------------------------


@pytest.mark.adapter_contract
def test_fantasypros_profile_resolves_headers_and_flags_percentage_only() -> None:
    result = parse_projection_csv(
        load("fantasypros_sample.csv"), FANTASYPROS_PROFILE, season="2026-27"
    )

    assert result.rejected_count == 0
    alpha = next(row for row in result.rows if row.player_name == "Player Alpha")
    assert alpha.points_per_game == 24.2
    assert alpha.three_pointers_made_per_game == 2.5
    # FantasyPros' free export gives FG%/FT% with no makes or attempts, so
    # these must stay unset rather than being invented from a percentage.
    assert alpha.field_goals_made_per_game is None
    assert alpha.free_throws_made_per_game is None
    assert any(
        "percentage" in issue.message and not issue.fatal
        for issue in result.issues
        if issue.row_number == alpha.row_number
    )


@pytest.mark.adapter_contract
def test_hashtag_profile_resolves_full_shooting_volume() -> None:
    result = parse_projection_csv(load("hashtag_sample.csv"), HASHTAG_PROFILE, season="2026-27")

    assert result.rejected_count == 0
    beta = next(row for row in result.rows if row.player_name == "Player Beta")
    assert beta.field_goals_made_per_game == 6.1
    assert beta.field_goals_attempted_per_game == 13.2
    assert beta.offensive_rebounds_per_game == 1.0
    assert beta.defensive_rebounds_per_game == 3.5


@pytest.mark.adapter_contract
def test_basketball_monster_profile_resolves_headers() -> None:
    result = parse_projection_csv(
        load("basketball_monster_sample.csv"), BASKETBALL_MONSTER_PROFILE, season="2026-27"
    )

    assert result.rejected_count == 0
    gamma = next(row for row in result.rows if row.player_name == "Player Gamma")
    assert gamma.rebounds_per_game == 10.2
    assert gamma.free_throws_made_per_game == 3.0
    assert gamma.free_throws_attempted_per_game == 3.8


# --------------------------------------------------------------------------
# Importer: identity resolution, versioning, idempotency
# --------------------------------------------------------------------------


def test_import_writes_projections_only_for_accepted_matches(seeded_players: Session) -> None:
    session = seeded_players
    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_text=load("manual_sample.csv"),
        original_filename="manual_sample.csv",
    )

    assert outcome.import_created is True
    assert outcome.projection_import.row_count == 4
    assert outcome.projection_import.matched_count == 3
    unresolved = (
        outcome.projection_import.unmatched_count + outcome.projection_import.needs_review_count
    )
    assert unresolved == 1

    projections = session.query(Projection).all()
    assert {p.player.full_name for p in projections} == {
        "Player Alpha",
        "Player Beta",
        "Player Gamma",
    }

    alpha = next(p for p in projections if p.player.full_name == "Player Alpha")
    assert alpha.points_per_game == 24.2
    assert alpha.season == "2026-27"
    assert alpha.games_played_assumption is not None
    assert alpha.games_played_assumption.assumed_games_played == 70

    # The unmatched report is reachable exactly the way the crosswalk's own
    # report is (identity/report.py) — nothing new to learn to adjudicate it.
    ambiguous, low_confidence, no_candidate = partition(outcome.identity_report)
    assert len(ambiguous) + len(low_confidence) + len(no_candidate) == 1
    summary = render_summary(outcome.identity_report, source_label="manual test")
    assert "manual test" in summary
    csv_report = to_csv([*ambiguous, *low_confidence, *no_candidate])
    assert "Unmatched Player" in csv_report


def test_reimporting_identical_bytes_is_idempotent(seeded_players: Session) -> None:
    session = seeded_players
    csv_text = load("manual_sample.csv")

    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_text=csv_text,
    )
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_text=csv_text,
    )

    assert first.import_created is True
    assert second.import_created is False
    assert first.projection_import.id == second.projection_import.id

    imports = session.query(ProjectionImport).all()
    assert len(imports) == 1
    projections = session.query(Projection).all()
    assert len(projections) == 3  # not duplicated by the second pass


def test_an_updated_file_creates_a_new_versioned_import(seeded_players: Session) -> None:
    session = seeded_players
    original = load("manual_sample.csv")
    updated = original.replace("24.2", "25.0")  # a source publishing a revision

    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_text=original,
    )
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_text=updated,
    )

    assert second.import_created is True
    assert first.projection_import.id != second.projection_import.id

    imports = session.query(ProjectionImport).all()
    assert len(imports) == 2

    sources = session.query(ProjectionSource).all()
    assert len(sources) == 1  # one source registration, two versioned imports

    old_alpha = (
        session.query(Projection)
        .filter_by(projection_import_id=first.projection_import.id)
        .join(Player)
        .filter(Player.full_name == "Player Alpha")
        .one()
    )
    new_alpha = (
        session.query(Projection)
        .filter_by(projection_import_id=second.projection_import.id)
        .join(Player)
        .filter(Player.full_name == "Player Alpha")
        .one()
    )
    assert old_alpha.points_per_game == 24.2  # history is untouched
    assert new_alpha.points_per_game == 25.0


def test_source_games_played_assumption_never_becomes_a_projection_column(
    seeded_players: Session,
) -> None:
    """The ADR-002 separation, proved end to end rather than only in the schema."""
    session = seeded_players
    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_text=load("manual_sample.csv"),
    )
    del outcome

    assumption = (
        session.query(SourceGamesPlayedAssumption)
        .join(Projection)
        .join(Player)
        .filter(Player.full_name == "Player Alpha")
        .one()
    )
    assert assumption.assumed_games_played == 70
    # A projection row and its GP assumption are two tables joined 1:1, never
    # one row carrying both.
    assert assumption.projection.points_per_game == 24.2
    assert not hasattr(assumption.projection, "games_played")
