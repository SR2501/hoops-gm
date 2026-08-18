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

import hashlib
from pathlib import Path
from typing import Any

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
    ProjectionEncodingError,
    ProjectionProfileError,
    StatColumn,
    ValueShape,
    get_or_create_projection_import,
    get_or_create_projection_source,
    import_projection_csv,
    parse_projection_csv,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "projections"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


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
    """ADR-002/ADR-008, enforced by absence rather than merely documented."""
    columns = set(Projection.__table__.columns.keys())
    assert "games_played" not in columns
    assert "expected_games" not in columns
    assert "assumed_games_played" not in columns
    assert {
        "raw_row",
        "rank",
        "aav",
        "composite_value",
    }.isdisjoint(columns)


@pytest.mark.parametrize(
    ("profile_kwargs", "terminal_alias"),
    [
        (
            {
                "games_played_aliases": ("expected_games",),
                "stat_columns": (StatColumn("points_per_game", ("points_per_game",)),),
            },
            "expected_games",
        ),
        (
            {
                "stat_columns": (StatColumn("points_per_game", ("fantasy_value",)),),
            },
            "fantasy_value",
        ),
        (
            {
                "stat_columns": (
                    StatColumn(
                        "assists_per_game",
                        ("composite_value",),
                        shape=ValueShape.SEASON_TOTAL,
                    ),
                ),
            },
            "composite_value",
        ),
    ],
)
def test_custom_profile_cannot_map_terminal_columns_into_earlier_layers(
    profile_kwargs: dict[str, Any],
    terminal_alias: str,
) -> None:
    with pytest.raises(ValueError, match="ADR-008") as exc_info:
        ColumnProfile(
            source=ExternalSource.MANUAL,
            display_name="hostile custom profile",
            name_aliases=("player_name",),
            **profile_kwargs,
        )

    assert terminal_alias in str(exc_info.value)


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
    # Give only Beta a usable per-game value through a second recognized field
    # so the parser can return Alpha's row-level rejection instead of rejecting
    # the whole file.
    profile = ColumnProfile(
        source=MANUAL_PROFILE.source,
        display_name="season-total test profile",
        name_aliases=("player_name",),
        stat_columns=(
            StatColumn("points_per_game", ("points_total",), shape=ValueShape.SEASON_TOTAL),
            StatColumn("assists_per_game", ("assists_per_game",)),
        ),
    )
    csv_text = "player_name,points_total,assists_per_game\nPlayer Alpha,1600,\nPlayer Beta,,5.0\n"
    result = parse_projection_csv(csv_text, profile, season="2026-27")

    assert result.rejected_count == 1
    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert any("season total" in issue.message for issue in result.warnings)
    assert any("no usable production" in issue.message for issue in result.fatal_issues)


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
    csv_text = "player_name,games_played,points_per_game\nPlayer Alpha,250,20\nPlayer Beta,70,18\n"
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.rejected_count == 1
    assert [row.player_name for row in result.rows] == ["Player Beta"]


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
        "Player Beta,6.0,12.0\n"
    )
    result = parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")

    assert result.rejected_count == 1
    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert any("exceed" in issue.message for issue in result.issues)


def test_missing_name_column_raises_a_profile_error() -> None:
    """A header mismatch this total is not a per-row problem — the whole
    file cannot be read under this profile."""
    csv_text = "totally_unrelated_column\nsomething\n"
    with pytest.raises(ProjectionProfileError):
        parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")


def test_duplicate_normalized_headers_fail_the_whole_file() -> None:
    csv_text = "player_name,points_per_game,Points Per Game\nPlayer Alpha,20.0,21.0\n"
    with pytest.raises(ProjectionProfileError, match="duplicate CSV headers"):
        parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")


def test_vendor_profile_requires_its_production_signature() -> None:
    csv_text = "Player,Team,PTS,REB\nPlayer Alpha,BOS,20.0,5.0\n"
    with pytest.raises(ProjectionProfileError, match="assists_per_game"):
        parse_projection_csv(csv_text, FANTASYPROS_PROFILE, season="2026-27")


def test_file_with_no_production_headers_is_rejected() -> None:
    csv_text = "player_name,rank,aav\nPlayer Alpha,1,55\n"
    with pytest.raises(ProjectionProfileError, match="no recognized production columns"):
        parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")


def test_row_with_no_usable_production_rate_is_rejected() -> None:
    csv_text = "player_name,points_per_game\nPlayer Alpha,\n"
    with pytest.raises(ProjectionProfileError, match="no usable production"):
        parse_projection_csv(csv_text, MANUAL_PROFILE, season="2026-27")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_games_played_is_rejected(value: str) -> None:
    result = parse_projection_csv(
        (f"player_name,games_played,points_per_game\nPlayer Alpha,{value},20\nPlayer Beta,70,18\n"),
        MANUAL_PROFILE,
        season="2026-27",
    )

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert result.rejected_count == 1


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_production_stat_is_rejected(value: str) -> None:
    result = parse_projection_csv(
        (f"player_name,points_per_game\nPlayer Alpha,{value}\nPlayer Beta,18\n"),
        MANUAL_PROFILE,
        season="2026-27",
    )

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert result.rejected_count == 1


# --------------------------------------------------------------------------
# Parser examples: vendor profiles (synthetic, not Adapter-gate fixtures)
# --------------------------------------------------------------------------


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


def test_hashtag_profile_resolves_full_shooting_volume() -> None:
    result = parse_projection_csv(load("hashtag_sample.csv"), HASHTAG_PROFILE, season="2026-27")

    assert result.rejected_count == 0
    beta = next(row for row in result.rows if row.player_name == "Player Beta")
    assert beta.field_goals_made_per_game == 6.1
    assert beta.field_goals_attempted_per_game == 13.2
    assert beta.offensive_rebounds_per_game == 1.0
    assert beta.defensive_rebounds_per_game == 3.5


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
        csv_bytes=load_bytes("manual_sample.csv"),
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


def test_ambiguous_player_is_reported_and_never_imported(session: Session) -> None:
    seed_player(session, nba_id=10, name="Jordan Example", team_abbreviation="BOS", position="G")
    seed_player(session, nba_id=11, name="Jordan Example", team_abbreviation="LAL", position="G")

    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=b"player_name,points_per_game\nJordan Example,20.0\n",
    )

    assert outcome.identity_report.accepted == []
    assert len(outcome.identity_report.needs_review) == 1
    assert outcome.identity_report.needs_review[0].reason.startswith("ambiguous:")
    assert outcome.projection_import.needs_review_count == 1
    assert session.query(Projection).count() == 0
    assert (
        session.query(PlayerExternalId)
        .filter(PlayerExternalId.source == ExternalSource.MANUAL)
        .count()
        == 0
    )


def test_reimporting_identical_bytes_is_idempotent(seeded_players: Session) -> None:
    session = seeded_players
    csv_bytes = load_bytes("manual_sample.csv")

    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )

    assert first.import_created is True
    assert second.import_created is False
    assert first.projection_import.id == second.projection_import.id

    imports = session.query(ProjectionImport).all()
    assert len(imports) == 1
    projections = session.query(Projection).all()
    assert len(projections) == 3  # not duplicated by the second pass


def test_identical_bytes_for_a_new_season_create_a_distinct_import(
    seeded_players: Session,
) -> None:
    session = seeded_players
    csv_bytes = load_bytes("manual_sample.csv")

    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2027-28",
        csv_bytes=csv_bytes,
    )

    assert second.import_created is True
    assert first.projection_import.id != second.projection_import.id
    assert second.projection_import.season == "2027-28"
    assert {
        projection.season
        for projection in session.query(Projection).filter_by(
            projection_import_id=second.projection_import.id
        )
    } == {"2027-28"}


def test_an_updated_file_creates_a_new_versioned_import(seeded_players: Session) -> None:
    session = seeded_players
    original = load_bytes("manual_sample.csv")
    updated = original.replace(b"24.2", b"25.0")  # a source publishing a revision

    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=original,
    )
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=updated,
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


def test_reprocessing_accepted_to_ambiguous_removes_all_owned_output(session: Session) -> None:
    seed_player(session, nba_id=20, name="Casey Example", team_abbreviation="BOS", position="G")
    csv_bytes = (
        b"player_name,team,position,games_played,points_per_game\nCasey Example,BOS,G,70,20.0\n"
    )
    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )
    assert first.projection_import.matched_count == 1
    assert session.query(Projection).count() == 1
    assert session.query(SourceGamesPlayedAssumption).count() == 1

    seed_player(session, nba_id=21, name="Casey Example", team_abbreviation="BOS", position="G")
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )

    assert second.import_created is False
    assert second.identity_report.accepted == []
    assert len(second.identity_report.needs_review) == 1
    assert session.query(Projection).count() == 0
    assert session.query(SourceGamesPlayedAssumption).count() == 0
    link = (
        session.query(PlayerExternalId)
        .filter(PlayerExternalId.source == ExternalSource.MANUAL)
        .one()
    )
    assert link.current_for_source is None


def test_reprocessing_accepted_to_unmatched_removes_all_owned_output(session: Session) -> None:
    player = seed_player(
        session,
        nba_id=30,
        name="Taylor Example",
        team_abbreviation="BOS",
        position="F",
    )
    csv_bytes = (
        b"player_name,team,position,games_played,points_per_game\nTaylor Example,BOS,F,68,18.0\n"
    )
    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )
    assert first.projection_import.matched_count == 1

    player.full_name = "Different Person"
    player.normalized_name = normalize_name(player.full_name).key
    session.flush()
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )

    assert second.import_created is False
    assert second.identity_report.accepted == []
    assert len(second.identity_report.unmatched) == 1
    assert session.query(Projection).count() == 0
    assert session.query(SourceGamesPlayedAssumption).count() == 0
    link = (
        session.query(PlayerExternalId)
        .filter(PlayerExternalId.source == ExternalSource.MANUAL)
        .one()
    )
    assert link.current_for_source is None


def test_reprocessing_player_a_to_player_b_replaces_output_exactly(session: Session) -> None:
    player_a = seed_player(
        session,
        nba_id=40,
        name="Morgan Example",
        team_abbreviation="BOS",
        position="F",
    )
    csv_bytes = (
        b"player_name,team,position,games_played,points_per_game\nMorgan Example,BOS,F,66,17.0\n"
    )
    import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )
    assert session.query(Projection).one().player_id == player_a.id

    player_a.full_name = "Corrected Player A"
    player_a.normalized_name = normalize_name(player_a.full_name).key
    player_b = seed_player(
        session,
        nba_id=41,
        name="Morgan Example",
        team_abbreviation="BOS",
        position="F",
    )
    session.flush()
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=csv_bytes,
    )

    assert second.import_created is False
    projection = session.query(Projection).one()
    assert projection.player_id == player_b.id
    assert projection.player_id != player_a.id
    assert session.query(SourceGamesPlayedAssumption).count() == 1
    link = (
        session.query(PlayerExternalId)
        .filter(
            PlayerExternalId.source == ExternalSource.MANUAL,
            PlayerExternalId.current_for_source == ExternalSource.MANUAL.value,
        )
        .one()
    )
    assert link.player_id == player_b.id


def test_raw_byte_identity_distinguishes_bom_and_newlines(seeded_players: Session) -> None:
    session = seeded_players
    lf = b"player_name,points_per_game\nPlayer Alpha,20.0\n"
    crlf = lf.replace(b"\n", b"\r\n")
    bom = b"\xef\xbb\xbf" + lf

    outcomes = [
        import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Manual test source",
            season="2026-27",
            csv_bytes=content,
        )
        for content in (lf, crlf, bom)
    ]

    assert all(outcome.import_created for outcome in outcomes)
    assert len({outcome.projection_import.id for outcome in outcomes}) == 3
    assert {outcome.projection_import.content_sha256 for outcome in outcomes} == {
        hashlib.sha256(content).hexdigest() for content in (lf, crlf, bom)
    }


def test_non_utf8_bytes_fail_before_an_import_row_is_created(session: Session) -> None:
    with pytest.raises(ProjectionEncodingError, match="must be UTF-8"):
        import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Manual test source",
            season="2026-27",
            csv_bytes=b"player_name,points_per_game\nJos\xe9,20.0\n",
        )

    assert session.query(ProjectionImport).count() == 0
    assert session.query(ProjectionSource).count() == 0


def test_profile_source_must_match_declared_source(session: Session) -> None:
    with pytest.raises(ValueError, match="does not match declared import source"):
        import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Misattributed source",
            season="2026-27",
            csv_bytes=b"player_name,points_per_game\nPlayer Alpha,20.0\n",
            profile=FANTASYPROS_PROFILE,
        )

    assert session.query(ProjectionSource).count() == 0


def test_duplicate_conflict_reselects_the_winning_import(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = get_or_create_projection_source(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
    )
    content_sha256 = hashlib.sha256(b"same bytes").hexdigest()
    winner, created = get_or_create_projection_import(
        session,
        source=source,
        season="2026-27",
        content_sha256=content_sha256,
    )
    assert created is True

    real_scalar = session.scalar
    calls = 0

    def stale_once(statement: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return real_scalar(statement)

    monkeypatch.setattr(session, "scalar", stale_once)
    converged, created = get_or_create_projection_import(
        session,
        source=source,
        season="2026-27",
        content_sha256=content_sha256,
    )

    assert created is False
    assert converged.id == winner.id
    assert session.query(ProjectionImport).count() == 1


def test_terminal_columns_are_ignored_and_never_persisted(
    seeded_players: Session,
) -> None:
    session = seeded_players
    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=(
            b"player_name,rank,AAV,composite_value,expected_games,points_per_game\n"
            b"Player Alpha,1,55,99.9,82,20.0\n"
        ),
        raw_payload_ref="raw://projection-import/fixture",
    )

    assert set(outcome.parse_result.ignored_terminal_headers) == {
        "rank",
        "AAV",
        "composite_value",
        "expected_games",
    }
    projection = session.query(Projection).one()
    assert projection.points_per_game == 20.0
    assert outcome.projection_import.raw_payload_ref == "raw://projection-import/fixture"
    projection_columns = set(Projection.__table__.columns)
    assert {
        "raw_row",
        "rank",
        "aav",
        "composite_value",
        "expected_games",
    }.isdisjoint(projection_columns)


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
        csv_bytes=load_bytes("manual_sample.csv"),
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
