"""The generic projection CSV importer — ``csv-importer``, Phase 5.

Three layers, tested at their own level:

* **profiles** — pure data, no test needed beyond the parity check below.
* **parser** (``parse_projection_csv``) — pure and offline, so every
  validation rule is exercised without a database.
* **importer** (``import_projection_csv``) — the DB-writing boundary,
  covering identity resolution, versioning and idempotency.

FantasyPros and Hashtag fixtures remain unverified synthetic examples.
Basketball Monster's fixture is a privacy-safe synthetic derivative of a
privately retained paid export: it preserves the proven 2026-27 headers, order
and CSV dialect while containing no paid player rows or private path.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import ExternalSource, FieldEvidence, MatchMethod
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.db.models.projections import (
    Projection,
    ProjectionImport,
    ProjectionProfileVersion,
    ProjectionSource,
    SourceGamesPlayedAssumption,
)
from hoops_gm.db.session import Database
from hoops_gm.identity import IdentityResolver, ResolvableRecord
from hoops_gm.identity.names import normalize_name
from hoops_gm.identity.report import partition, render_summary, to_csv
from hoops_gm.ingest.projections import (
    BASKETBALL_MONSTER_2026_27_HEADERS,
    BASKETBALL_MONSTER_PROFILE,
    CANONICAL_STAT_FIELDS,
    FANTASYPROS_PROFILE,
    HASHTAG_PROFILE,
    MANUAL_PROFILE,
    ColumnProfile,
    DerivedStatColumn,
    ProjectionEncodingError,
    ProjectionProfileError,
    StatColumn,
    ValueShape,
    build_player_targets,
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
        # A seeded position carries the provenance a real import writes.
        # Without this the helper produced a shape no real producer can write,
        # which is one of this project's named defect classes. Note there is
        # **no** database constraint enforcing it: one was implemented and
        # reverted because adding a CHECK on SQLite rebuilds ``players``, whose
        # eight ``ON DELETE CASCADE`` dependants include the crosswalk itself.
        # The rule lives in the importer and in the required
        # ``NbaPlayerPositionRecord.season``, so a fixture that bypasses both
        # has to keep the shape honest by hand.
        primary_position_source="nba:PlayerIndex" if position else None,
        primary_position_season="2026-27" if position else None,
        primary_position_observed_at=(datetime(2026, 8, 20, tzinfo=UTC) if position else None),
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
                "stat_columns": (
                    StatColumn(
                        "points_per_game",
                        ("points_per_game",),
                        ValueShape.PER_GAME,
                    ),
                ),
            },
            "expected_games",
        ),
        (
            {
                "stat_columns": (
                    StatColumn(
                        "points_per_game",
                        ("fantasy_value",),
                        ValueShape.PER_GAME,
                    ),
                ),
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
            profile_id="hostile-custom",
            version="1",
            source=ExternalSource.MANUAL,
            display_name="hostile custom profile",
            name_aliases=("player_name",),
            **profile_kwargs,
        )

    assert terminal_alias in str(exc_info.value)


def test_external_profile_cannot_claim_wildcard_season_verification() -> None:
    with pytest.raises(ValueError, match="wildcard season verification"):
        ColumnProfile(
            profile_id="vendor-wildcard",
            version="1",
            source=ExternalSource.FANTASYPROS,
            display_name="invalid vendor wildcard",
            name_aliases=("Player",),
            stat_columns=(StatColumn("points_per_game", ("PTS",), ValueShape.PER_GAME),),
            verified=True,
            verified_seasons=("*",),
            verification_evidence="one real export cannot verify every season",
        )


def test_manual_wildcard_profile_identity_cannot_be_forged(session: Session) -> None:
    forged = ColumnProfile(
        profile_id="manual-canonical",
        version="1",
        source=ExternalSource.MANUAL,
        display_name="forged manual profile",
        name_aliases=("Player",),
        stat_columns=(StatColumn("points_per_game", ("PTS",), ValueShape.PER_GAME),),
        verified=True,
        verified_seasons=("*",),
        verification_evidence="caller assertion without canonical schema evidence",
    )

    with pytest.raises(ProjectionProfileError, match="not the committed registry profile"):
        import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Forged manual profile",
            season="2026-27",
            csv_bytes=b"Player,PTS\nPlayer Alpha,1694\n",
            profile=forged,
        )

    assert session.query(ProjectionImport).count() == 0
    assert session.query(Projection).count() == 0


def test_verified_profile_requires_nonblank_evidence() -> None:
    with pytest.raises(ValueError, match="without season scope and evidence"):
        ColumnProfile(
            profile_id="blank-evidence",
            version="1",
            source=ExternalSource.MANUAL,
            display_name="blank evidence",
            name_aliases=("player_name",),
            stat_columns=(
                StatColumn("points_per_game", ("points_per_game",), ValueShape.PER_GAME),
            ),
            verified=True,
            verified_seasons=("2026-27",),
            verification_evidence="   ",
        )


def test_identity_anchor_namespace_cannot_be_used_for_projection_csvs() -> None:
    with pytest.raises(ValueError, match="not an isolated projection-provider namespace"):
        ColumnProfile(
            profile_id="forged-nba-projection",
            version="1",
            source=ExternalSource.NBA,
            display_name="invalid NBA projection",
            name_aliases=("player_name",),
            stat_columns=(
                StatColumn("points_per_game", ("points_per_game",), ValueShape.PER_GAME),
            ),
            verified=True,
            verified_seasons=("2026-27",),
            verification_evidence="not relevant because the namespace is forbidden",
        )


def test_projection_source_helper_rejects_identity_anchor_namespace(
    session: Session,
) -> None:
    with pytest.raises(ProjectionProfileError, match="identity-anchor namespace"):
        get_or_create_projection_source(
            session,
            source=ExternalSource.NBA,
            display_name="invalid NBA projection source",
        )


def test_projection_source_database_constraint_rejects_identity_anchor_namespace(
    session: Session,
) -> None:
    session.add(
        ProjectionSource(
            source=ExternalSource.NBA,
            display_name="invalid NBA projection source",
        )
    )
    with pytest.raises(IntegrityError) as exc_info:
        session.flush()
    assert "projection_provider_namespace" in str(exc_info.value)


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
        profile_id="season-total-test",
        version="1",
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


def test_season_total_conversion_rejects_non_finite_result() -> None:
    profile = ColumnProfile(
        profile_id="season-total-test",
        version="1",
        source=MANUAL_PROFILE.source,
        display_name="season-total test profile",
        name_aliases=("player_name",),
        games_played_aliases=("gp",),
        stat_columns=(
            StatColumn("points_per_game", ("points_total",), shape=ValueShape.SEASON_TOTAL),
        ),
    )
    result = parse_projection_csv(
        ("player_name,gp,points_total\nPlayer Alpha,0.1,1e308\nPlayer Beta,80,1600\n"),
        profile,
        season="2026-27",
    )

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert result.rejected_count == 1
    assert any("non-finite per-game value" in issue.message for issue in result.fatal_issues)


def test_non_finite_optional_derivation_rejects_the_row() -> None:
    profile = ColumnProfile(
        profile_id="derived-overflow-test",
        version="1",
        source=ExternalSource.MANUAL,
        display_name="derived overflow test",
        name_aliases=("player_name",),
        stat_columns=(StatColumn("assists_per_game", ("assists",), ValueShape.PER_GAME),),
        derived_stat_columns=(
            DerivedStatColumn(
                "points_per_game",
                (("assists_per_game", 1e308),),
            ),
        ),
    )
    result = parse_projection_csv(
        ("player_name,assists\nPlayer Alpha,1e308\nPlayer Beta,1\n"),
        profile,
        season="2026-27",
    )

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert result.rejected_count == 1
    assert any("derived points" in issue.message for issue in result.fatal_issues)


def test_season_total_without_games_played_is_a_warning_not_a_fabrication() -> None:
    # Give only Beta a usable per-game value through a second recognized field
    # so the parser can return Alpha's row-level rejection instead of rejecting
    # the whole file.
    profile = ColumnProfile(
        profile_id="season-total-test",
        version="1",
        source=MANUAL_PROFILE.source,
        display_name="season-total test profile",
        name_aliases=("player_name",),
        stat_columns=(
            StatColumn("points_per_game", ("points_total",), shape=ValueShape.SEASON_TOTAL),
            StatColumn("assists_per_game", ("assists_per_game",), ValueShape.PER_GAME),
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


def test_extra_csv_fields_reject_row_instead_of_discarding_overflow() -> None:
    result = parse_projection_csv(
        ("player_name,points_per_game\nPlayer Alpha,1,234\nPlayer Beta,18\n"),
        MANUAL_PROFILE,
        season="2026-27",
    )

    assert [row.player_name for row in result.rows] == ["Player Beta"]
    assert result.rejected_count == 1
    assert any("more fields than the CSV header" in issue.message for issue in result.fatal_issues)


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


def test_unverified_vendor_shape_cannot_import_season_totals_as_rates(
    session: Session,
) -> None:
    csv_bytes = b"Player,Team,GP,PTS,REB,AST\nPlayer Alpha,BOS,70,1694,560,350\n"

    with pytest.raises(ProjectionProfileError, match="not verified"):
        import_projection_csv(
            session,
            source=ExternalSource.FANTASYPROS,
            display_name="Unverified FantasyPros example",
            season="2026-27",
            csv_bytes=csv_bytes,
        )

    assert session.query(ProjectionSource).count() == 0
    assert session.query(ProjectionImport).count() == 0
    assert session.query(Projection).count() == 0


def test_self_attested_custom_profile_cannot_enter_production(
    session: Session,
) -> None:
    self_attested = ColumnProfile(
        profile_id="fantasypros-self-attested",
        version="1",
        source=ExternalSource.FANTASYPROS,
        display_name="self-attested FantasyPros",
        name_aliases=("Player",),
        stat_columns=(StatColumn("points_per_game", ("PTS",), ValueShape.PER_GAME),),
        verified=True,
        verified_seasons=("2026-27",),
        verification_evidence="caller says this is real",
    )

    with pytest.raises(ProjectionProfileError, match="not the committed registry profile"):
        import_projection_csv(
            session,
            source=ExternalSource.FANTASYPROS,
            display_name="Self-attested profile",
            season="2026-27",
            csv_bytes=b"Player,PTS\nPlayer Alpha,1694\n",
            profile=self_attested,
        )

    assert session.query(ProjectionImport).count() == 0
    assert session.query(Projection).count() == 0


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


def test_makes_plus_percentage_without_attempts_excludes_the_ratio_field() -> None:
    profile = ColumnProfile(
        profile_id="ratio-decomposition-test",
        version="1",
        source=ExternalSource.MANUAL,
        display_name="ratio decomposition test",
        name_aliases=("player_name",),
        stat_columns=(
            StatColumn("points_per_game", ("pts",), ValueShape.PER_GAME),
            StatColumn("field_goals_made_per_game", ("fgm",), ValueShape.PER_GAME),
            StatColumn("field_goals_attempted_per_game", ("fga",), ValueShape.PER_GAME),
        ),
        percentage_fallback_aliases={"field_goals_made_per_game": ("fg%",)},
    )

    result = parse_projection_csv(
        "player_name,pts,fgm,fg%\nPlayer Alpha,20.0,8.0,50.0\n",
        profile,
        season="2026-27",
    )

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.points_per_game == 20.0
    assert row.field_goals_made_per_game is None
    assert row.field_goals_attempted_per_game is None
    assert any("incomplete field goal volume pair" in issue.message for issue in result.warnings)


def test_percentage_exclusion_is_persisted_in_import_lineage(
    seeded_players: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ColumnProfile(
        profile_id="verified-ratio-evidence",
        version="1",
        source=ExternalSource.MANUAL,
        display_name="verified ratio evidence",
        name_aliases=("player_name",),
        stat_columns=(
            StatColumn("points_per_game", ("pts",), ValueShape.PER_GAME),
            StatColumn("field_goals_made_per_game", ("fgm",), ValueShape.PER_GAME),
            StatColumn("field_goals_attempted_per_game", ("fga",), ValueShape.PER_GAME),
        ),
        percentage_fallback_aliases={"field_goals_made_per_game": ("fg%",)},
        verified=True,
        verified_seasons=("2026-27",),
        verification_evidence="recorded fixture fixture://ratio-evidence-v1",
    )
    monkeypatch.setattr(
        "hoops_gm.ingest.projections.importer.PROFILES_BY_SOURCE",
        {ExternalSource.MANUAL: profile},
    )
    outcome = import_projection_csv(
        seeded_players,
        source=ExternalSource.MANUAL,
        display_name="Verified ratio evidence",
        season="2026-27",
        csv_bytes=b"player_name,pts,fgm,fg%\nPlayer Alpha,20.0,8.0,50.0\n",
        profile=profile,
        raw_payload_ref="fixture://ratio-evidence-v1",
    )

    lineage = outcome.projection_import.profile_lineage
    assert lineage["resolved_percentage_headers"] == {"field_goals_made_per_game": "fg%"}
    field_transforms = lineage["field_transforms"]
    assert isinstance(field_transforms, dict)
    assert field_transforms["field_goals_made_per_game__percentage_observation"] == {
        "source_header": "fg%",
        "source_unit": "percentage",
        "output_unit": None,
        "transform": "not_imported",
        "reason": "percentage categories require explicit makes and attempts",
        "required_volume_fields": [
            "field_goals_made_per_game",
            "field_goals_attempted_per_game",
        ],
    }
    projection = seeded_players.query(Projection).one()
    assert projection.points_per_game == 20.0
    assert projection.field_goals_made_per_game is None
    assert projection.field_goals_attempted_per_game is None


# --------------------------------------------------------------------------
# Parser examples: unverified vendor profiles
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


# --------------------------------------------------------------------------
# Basketball Monster: privacy-safe derivative of proven private contract
# --------------------------------------------------------------------------


@pytest.mark.adapter_contract
class TestBasketballMonsterProjectionContract:
    def test_fixture_is_privacy_safe_and_tied_to_private_evidence_hashes(self) -> None:
        fixture_bytes = load_bytes("basketball_monster_sample.csv")
        metadata = json.loads(
            (FIXTURES / "basketball_monster_sample.metadata.json").read_text(encoding="utf-8")
        )

        canonical_fixture_bytes = fixture_bytes.replace(b"\r\n", b"\n")
        assert (
            hashlib.sha256(canonical_fixture_bytes).hexdigest().upper()
            == metadata["privacy_safe_fixture_sha256"]
        )
        assert metadata["private_export_sha256"] == (
            "FA13AD188E8ACADD410DFEAE7FF296A25078842E22CE17046CF19DFBCA9D3ABD"
        )
        assert metadata["private_semantic_screenshot_sha256"] == (
            "3BA42FD80072E8C35C191C38BA19EB0C8A8BE4182D484FEFD73A31D1ED36C29B"
        )
        serialized_metadata = json.dumps(metadata)
        assert "C:\\" not in serialized_metadata
        assert "/Users/" not in serialized_metadata
        parsed = parse_projection_csv(
            fixture_bytes.decode("utf-8"),
            BASKETBALL_MONSTER_PROFILE,
            season="2026-27",
        )
        assert all(
            row.source_player_id and row.source_player_id.startswith("synthetic-")
            for row in parsed.rows
        )

    def test_exact_headers_and_season_total_transformations(self) -> None:
        csv_text = load("basketball_monster_sample.csv")
        assert tuple(csv_text.splitlines()[0].split(",")) == BASKETBALL_MONSTER_2026_27_HEADERS

        result = parse_projection_csv(
            csv_text,
            BASKETBALL_MONSTER_PROFILE,
            season="2026-27",
        )

        assert result.rejected_count == 0
        assert result.ignored_source_headers == [
            "technicals",
            "double_doubles",
            "triple_doubles",
            "comments",
        ]
        alpha = next(row for row in result.rows if row.player_name == "Player Alpha")
        assert alpha.source_player_id == "synthetic-alpha"
        assert alpha.team is None
        assert alpha.position is None
        assert alpha.assumed_games_played == 70
        assert alpha.minutes_per_game == pytest.approx(34.5)
        assert alpha.field_goals_made_per_game == pytest.approx(8.6)
        assert alpha.field_goals_attempted_per_game == pytest.approx(17.5)
        assert alpha.free_throws_made_per_game == pytest.approx(4.5)
        assert alpha.free_throws_attempted_per_game == pytest.approx(5.3)
        assert alpha.three_pointers_made_per_game == pytest.approx(2.5)
        assert alpha.points_per_game == pytest.approx(24.2)
        assert alpha.offensive_rebounds_per_game == pytest.approx(1.0)
        assert alpha.defensive_rebounds_per_game == pytest.approx(6.1)
        assert alpha.rebounds_per_game == pytest.approx(7.1)

    @pytest.mark.parametrize(
        "header",
        [
            ",".join(BASKETBALL_MONSTER_2026_27_HEADERS[:-1]),
            ",".join(
                (
                    BASKETBALL_MONSTER_2026_27_HEADERS[1],
                    BASKETBALL_MONSTER_2026_27_HEADERS[0],
                    *BASKETBALL_MONSTER_2026_27_HEADERS[2:],
                )
            ),
            ",".join(BASKETBALL_MONSTER_2026_27_HEADERS).replace(
                "field_goals,",
                "field_goals_made,",
                1,
            ),
        ],
    )
    def test_any_header_or_order_drift_fails_loudly(self, header: str) -> None:
        row = load("basketball_monster_sample.csv").splitlines()[1]
        with pytest.raises(ProjectionProfileError, match="header names/order drifted"):
            parse_projection_csv(
                f"{header}\n{row}\n",
                BASKETBALL_MONSTER_PROFILE,
                season="2026-27",
            )

    def test_verified_import_uses_vendor_id_and_persists_derivation_lineage(
        self,
        seeded_players: Session,
    ) -> None:
        outcome = import_projection_csv(
            seeded_players,
            source=ExternalSource.BASKETBALL_MONSTER,
            display_name="Basketball Monster",
            season="2026-27",
            csv_bytes=load_bytes("basketball_monster_sample.csv"),
            original_filename="basketball_monster_sample.csv",
        )

        assert outcome.projection_import.profile_verified is True
        assert outcome.projection_import.row_count == 2
        assert outcome.projection_import.matched_count == 2
        links = list(
            seeded_players.scalars(
                select(PlayerExternalId).where(
                    PlayerExternalId.source == ExternalSource.BASKETBALL_MONSTER
                )
            )
        )
        assert {link.external_id for link in links} == {
            "synthetic-alpha",
            "synthetic-gamma",
        }

        alpha = (
            seeded_players.query(Projection)
            .join(Player)
            .filter(Player.full_name == "Player Alpha")
            .one()
        )
        assert alpha.points_per_game == pytest.approx(24.2)
        assert not hasattr(alpha, "comments")
        assumption = (
            seeded_players.query(SourceGamesPlayedAssumption)
            .filter(SourceGamesPlayedAssumption.projection_id == alpha.id)
            .one()
        )
        assert assumption.assumed_games_played == 70

        lineage = outcome.projection_import.profile_lineage
        assert lineage["ignored_source_headers"] == [
            "technicals",
            "double_doubles",
            "triple_doubles",
            "comments",
        ]
        field_transforms = lineage["field_transforms"]
        assert isinstance(field_transforms, dict)
        assert field_transforms["points_per_game"] == {
            "terms": [
                {
                    "input_field": "field_goals_made_per_game",
                    "coefficient": 2.0,
                    "source_header": "field_goals",
                    "source_unit": "season_total",
                    "normalization": "divide_by_assumed_games_played",
                },
                {
                    "input_field": "three_pointers_made_per_game",
                    "coefficient": 1.0,
                    "source_header": "threes",
                    "source_unit": "season_total",
                    "normalization": "divide_by_assumed_games_played",
                },
                {
                    "input_field": "free_throws_made_per_game",
                    "coefficient": 1.0,
                    "source_header": "free_throws",
                    "source_unit": "season_total",
                    "normalization": "divide_by_assumed_games_played",
                },
            ],
            "output_unit": "per_game",
            "transform": "linear_combination_of_normalized_fields",
        }

    def test_profile_is_not_verified_for_another_season(self, session: Session) -> None:
        with pytest.raises(ProjectionProfileError, match="not verified"):
            import_projection_csv(
                session,
                source=ExternalSource.BASKETBALL_MONSTER,
                display_name="Basketball Monster",
                season="2027-28",
                csv_bytes=load_bytes("basketball_monster_sample.csv"),
            )

    def test_zero_game_season_total_row_is_rejected_not_fabricated(self) -> None:
        lines = load("basketball_monster_sample.csv").splitlines()
        zero_game_row = lines[1].replace(",70,2415,", ",0,2415,", 1)
        result = parse_projection_csv(
            "\n".join((lines[0], zero_game_row, lines[2], "")),
            BASKETBALL_MONSTER_PROFILE,
            season="2026-27",
        )

        assert [row.player_name for row in result.rows] == ["Player Gamma"]
        assert result.rejected_count == 1
        assert any(
            "season total but no valid games-played figure" in issue.message
            for issue in result.warnings
        )

    def test_duplicate_vendor_ids_are_rejected(self) -> None:
        lines = load("basketball_monster_sample.csv").splitlines()
        second = lines[2].replace("synthetic-gamma", "synthetic-alpha", 1)
        with pytest.raises(ProjectionProfileError, match="duplicate source player id"):
            parse_projection_csv(
                "\n".join((lines[0], lines[1], second, "")),
                BASKETBALL_MONSTER_PROFILE,
                season="2026-27",
            )


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


def test_conflicting_manual_crosswalk_never_redirects_an_accepted_target(
    session: Session,
) -> None:
    accepted_player = seed_player(
        session,
        nba_id=12,
        name="Manual Conflict",
        team_abbreviation="BOS",
        position="G",
    )
    manual_player = seed_player(
        session,
        nba_id=13,
        name="Different Manual Player",
        team_abbreviation="LAL",
        position="F",
    )
    external_id = normalize_name("Manual Conflict").key
    session.add(
        PlayerExternalId(
            player_id=manual_player.id,
            source=ExternalSource.MANUAL,
            current_for_source=ExternalSource.MANUAL.value,
            external_id=external_id,
            external_name="Manual Conflict",
            normalized_name=external_id,
            confidence=1.0,
            match_method=MatchMethod.MANUAL_OVERRIDE,
            is_manual_override=True,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()

    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=(b"player_name,team,position,points_per_game\nManual Conflict,BOS,G,20.0\n"),
    )

    assert outcome.identity_report.accepted == []
    assert len(outcome.identity_report.needs_review) == 1
    assert "manual crosswalk conflict" in outcome.identity_report.needs_review[0].reason
    assert session.query(Projection).count() == 0
    manual_link = session.scalar(
        select(PlayerExternalId).where(
            PlayerExternalId.source == ExternalSource.MANUAL,
            PlayerExternalId.external_id == external_id,
        )
    )
    assert manual_link is not None
    assert manual_link.player_id == manual_player.id
    assert manual_link.player_id != accepted_player.id


def test_manual_alias_incumbent_does_not_block_the_accepted_projection(
    session: Session,
) -> None:
    accepted_player = seed_player(
        session,
        nba_id=14,
        name="Accepted Player",
        team_abbreviation="BOS",
        position="G",
    )
    session.add(
        PlayerExternalId(
            player_id=accepted_player.id,
            source=ExternalSource.MANUAL,
            current_for_source=ExternalSource.MANUAL.value,
            external_id="legacy-alias",
            external_name="Legacy Alias",
            normalized_name=normalize_name("Legacy Alias").key,
            confidence=1.0,
            match_method=MatchMethod.MANUAL_OVERRIDE,
            is_manual_override=True,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()

    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=(b"player_name,team,position,points_per_game\nAccepted Player,BOS,G,20.0\n"),
    )

    assert len(outcome.identity_report.accepted) == 1
    assert outcome.identity_report.needs_review == []
    projection = session.query(Projection).one()
    assert projection.player_id == accepted_player.id
    manual_links = (
        session.query(PlayerExternalId)
        .filter(PlayerExternalId.source == ExternalSource.MANUAL)
        .all()
    )
    assert len(manual_links) == 1
    assert manual_links[0].external_id == "legacy-alias"
    assert manual_links[0].is_manual_override is True


def test_manual_alias_promotes_an_otherwise_unmatched_player(
    session: Session,
) -> None:
    player = seed_player(
        session,
        nba_id=15,
        name="Robert Williams III",
        team_abbreviation="POR",
        position="C",
    )
    alias_key = normalize_name("The Timelord").key
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.MANUAL,
            current_for_source=ExternalSource.MANUAL.value,
            external_id=alias_key,
            external_name="The Timelord",
            normalized_name=alias_key,
            confidence=1.0,
            match_method=MatchMethod.MANUAL_OVERRIDE,
            is_manual_override=True,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()

    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=b"player_name,points_per_game\nThe Timelord,10.0\n",
    )

    assert len(outcome.identity_report.accepted) == 1
    assert outcome.identity_report.accepted[0].reason == "manual crosswalk override"
    assert outcome.identity_report.unmatched == []
    projection = session.query(Projection).one()
    assert projection.player_id == player.id


def test_manual_alias_and_canonical_name_collision_requires_review(
    session: Session,
) -> None:
    player = seed_player(
        session,
        nba_id=16,
        name="Robert Williams III",
        team_abbreviation="POR",
        position="C",
    )
    alias_key = normalize_name("The Timelord").key
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.MANUAL,
            current_for_source=ExternalSource.MANUAL.value,
            external_id=alias_key,
            external_name="The Timelord",
            normalized_name=alias_key,
            confidence=1.0,
            match_method=MatchMethod.MANUAL_OVERRIDE,
            is_manual_override=True,
            name_evidence=FieldEvidence.AGREE,
        )
    )
    session.flush()

    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=(b"player_name,points_per_game\nRobert Williams III,10.0\nThe Timelord,10.0\n"),
    )

    assert outcome.identity_report.accepted == []
    assert len(outcome.identity_report.needs_review) == 2
    assert all(
        resolution.reason.startswith("collision:")
        for resolution in outcome.identity_report.needs_review
    )
    assert session.query(Projection).count() == 0


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


def test_replaying_older_file_does_not_rewind_current_vendor_id(
    seeded_players: Session,
) -> None:
    lines = load("basketball_monster_sample.csv").splitlines()
    old_bytes = "\n".join((lines[0], lines[1], "")).encode()
    new_bytes = old_bytes.replace(b"synthetic-alpha", b"synthetic-alpha-v2", 1)

    old_outcome = import_projection_csv(
        seeded_players,
        source=ExternalSource.BASKETBALL_MONSTER,
        display_name="Basketball Monster",
        season="2026-27",
        csv_bytes=old_bytes,
    )
    old_outcome.projection_import.imported_at = datetime(2026, 8, 1, tzinfo=UTC)
    new_outcome = import_projection_csv(
        seeded_players,
        source=ExternalSource.BASKETBALL_MONSTER,
        display_name="Basketball Monster",
        season="2026-27",
        csv_bytes=new_bytes,
    )
    new_outcome.projection_import.imported_at = datetime(2026, 8, 2, tzinfo=UTC)
    seeded_players.flush()
    import_projection_csv(
        seeded_players,
        source=ExternalSource.BASKETBALL_MONSTER,
        display_name="Basketball Monster",
        season="2026-27",
        csv_bytes=old_bytes,
    )

    alpha = seeded_players.scalar(select(Player).where(Player.full_name == "Player Alpha"))
    assert alpha is not None
    current = seeded_players.scalar(
        select(PlayerExternalId).where(
            PlayerExternalId.player_id == alpha.id,
            PlayerExternalId.source == ExternalSource.BASKETBALL_MONSTER,
            PlayerExternalId.current_for_source == ExternalSource.BASKETBALL_MONSTER.value,
        )
    )
    assert current is not None
    assert current.external_id == "synthetic-alpha-v2"


def test_replaying_older_season_does_not_rewind_current_crosswalk(
    seeded_players: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = ColumnProfile(
        profile_id="manual-source-id-test",
        version="1",
        source=ExternalSource.MANUAL,
        display_name="manual source id test",
        name_aliases=("player_name",),
        external_id_aliases=("source_id",),
        stat_columns=(StatColumn("points_per_game", ("points_per_game",), ValueShape.PER_GAME),),
        verified=True,
        verified_seasons=("2025-26", "2026-27"),
        verification_evidence="test-only exact source-id fixture",
    )
    monkeypatch.setattr(
        "hoops_gm.ingest.projections.importer.PROFILES_BY_SOURCE",
        {ExternalSource.MANUAL: profile},
    )
    old_bytes = b"source_id,player_name,points_per_game\nold-alpha,Player Alpha,20\n"
    new_bytes = b"source_id,player_name,points_per_game\nnew-alpha,Player Alpha,21\n"

    old_outcome = import_projection_csv(
        seeded_players,
        source=ExternalSource.MANUAL,
        display_name="Manual source-id test",
        season="2025-26",
        csv_bytes=old_bytes,
        profile=profile,
    )
    old_outcome.projection_import.imported_at = datetime(2026, 8, 1, tzinfo=UTC)
    new_outcome = import_projection_csv(
        seeded_players,
        source=ExternalSource.MANUAL,
        display_name="Manual source-id test",
        season="2026-27",
        csv_bytes=new_bytes,
        profile=profile,
    )
    new_outcome.projection_import.imported_at = datetime(2026, 8, 2, tzinfo=UTC)
    seeded_players.flush()
    import_projection_csv(
        seeded_players,
        source=ExternalSource.MANUAL,
        display_name="Manual source-id test",
        season="2025-26",
        csv_bytes=old_bytes,
        profile=profile,
    )

    alpha = seeded_players.scalar(select(Player).where(Player.full_name == "Player Alpha"))
    assert alpha is not None
    current = seeded_players.scalar(
        select(PlayerExternalId).where(
            PlayerExternalId.player_id == alpha.id,
            PlayerExternalId.source == ExternalSource.MANUAL,
            PlayerExternalId.current_for_source == ExternalSource.MANUAL.value,
        )
    )
    assert current is not None
    assert current.external_id == "new-alpha"


def test_profile_lineage_is_immutable_and_versioned(
    seeded_players: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = seeded_players
    csv_bytes = b"player_name,GP,PTS\nPlayer Alpha,70,1694\n"

    def profile(version: str, aliases: tuple[str, ...]) -> ColumnProfile:
        return ColumnProfile(
            profile_id="manual-season-total-evidence",
            version=version,
            source=ExternalSource.MANUAL,
            display_name="verified season-total fixture",
            name_aliases=("player_name",),
            games_played_aliases=("GP",),
            stat_columns=(StatColumn("points_per_game", aliases, ValueShape.SEASON_TOTAL),),
            verified=True,
            verified_seasons=("2026-27",),
            verification_evidence="recorded fixture fixture://season-total-v1",
        )

    profile_v1 = profile("1", ("PTS",))
    monkeypatch.setattr(
        "hoops_gm.ingest.projections.importer.PROFILES_BY_SOURCE",
        {ExternalSource.MANUAL: profile_v1},
    )
    first = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Verified custom source",
        season="2026-27",
        csv_bytes=csv_bytes,
        profile=profile_v1,
        raw_payload_ref="fixture://season-total-v1",
    )
    original_lineage = dict(first.projection_import.profile_lineage)
    field_transforms = original_lineage["field_transforms"]
    assert isinstance(field_transforms, dict)
    transform = field_transforms["points_per_game"]
    assert transform == {
        "source_header": "PTS",
        "source_unit": "season_total",
        "output_unit": "per_game",
        "transform": "divide_by_assumed_games_played",
    }
    assert session.query(Projection).one().points_per_game == pytest.approx(24.2)

    changed_bytes = csv_bytes.replace(b"1694", b"1700")
    changed_v1 = profile("1", ("PTS", "Points"))
    monkeypatch.setattr(
        "hoops_gm.ingest.projections.importer.PROFILES_BY_SOURCE",
        {ExternalSource.MANUAL: changed_v1},
    )
    with pytest.raises(ProjectionProfileError, match="changed without a version bump"):
        import_projection_csv(
            session,
            source=ExternalSource.MANUAL,
            display_name="Verified custom source",
            season="2026-27",
            csv_bytes=changed_bytes,
            profile=changed_v1,
        )

    profile_v2 = profile("2", ("PTS", "Points"))
    monkeypatch.setattr(
        "hoops_gm.ingest.projections.importer.PROFILES_BY_SOURCE",
        {ExternalSource.MANUAL: profile_v2},
    )
    second = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Verified custom source",
        season="2026-27",
        csv_bytes=csv_bytes,
        profile=profile_v2,
    )

    assert second.import_created is True
    assert second.projection_import.id != first.projection_import.id
    assert first.projection_import.profile_lineage == original_lineage
    assert first.projection_import.profile_version == "1"
    assert second.projection_import.profile_version == "2"
    assert first.projection_import.profile_definition_sha256 != (
        second.projection_import.profile_definition_sha256
    )
    assert session.query(ProjectionImport).count() == 2
    assert session.query(ProjectionProfileVersion).count() == 2


def test_database_rejects_incomplete_percentage_volume_pair(
    session: Session,
) -> None:
    seed_player(session, nba_id=19, name="Pair Violation")
    incomplete_player = seed_player(session, nba_id=20, name="Incomplete Pair")
    outcome = import_projection_csv(
        session,
        source=ExternalSource.MANUAL,
        display_name="Manual test source",
        season="2026-27",
        csv_bytes=b"player_name,points_per_game\nPair Violation,20.0\n",
    )
    session.add(
        Projection(
            projection_import_id=outcome.projection_import.id,
            player_id=incomplete_player.id,
            season="2026-27",
            field_goals_made_per_game=8.0,
        )
    )

    with pytest.raises(IntegrityError) as exc_info:
        session.flush()
    assert "fg_volume_pair_complete" in str(exc_info.value)


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


def test_concurrent_identical_imports_converge_without_duplicate_outputs(
    database: Database,
) -> None:
    setup = database.session_factory()
    seed_player(setup, nba_id=50, name="Concurrent Player", team_abbreviation="BOS")
    setup.commit()
    setup.close()

    barrier = Barrier(2)
    csv_bytes = b"player_name,team,points_per_game\nConcurrent Player,BOS,20.0\n"

    def run_import() -> tuple[int, int]:
        worker_session = database.session_factory()
        try:
            barrier.wait()
            outcome = import_projection_csv(
                worker_session,
                source=ExternalSource.MANUAL,
                display_name="Manual test source",
                season="2026-27",
                csv_bytes=csv_bytes,
            )
            worker_session.commit()
            return outcome.projection_import.id, outcome.counts.created
        finally:
            worker_session.rollback()
            worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_import(), range(2)))

    verification = database.session_factory()
    try:
        assert len({import_id for import_id, _ in results}) == 1
        assert sorted(created for _, created in results) == [0, 1]
        assert verification.query(ProjectionImport).count() == 1
        assert verification.query(Projection).count() == 1
        assert verification.query(ProjectionProfileVersion).count() == 1
    finally:
        verification.close()


def test_concurrent_distinct_files_serialize_shared_crosswalk_writes(
    database: Database,
) -> None:
    setup = database.session_factory()
    seed_player(setup, nba_id=51, name="Concurrent Revision", team_abbreviation="BOS")
    setup.commit()
    setup.close()

    barrier = Barrier(2)
    csv_files = (
        b"player_name,team,points_per_game\nConcurrent Revision,BOS,20.0\n",
        b"player_name,team,points_per_game\nConcurrent Revision,BOS,21.0\n",
    )

    def run_import(csv_bytes: bytes) -> int:
        worker_session = database.session_factory()
        try:
            barrier.wait()
            outcome = import_projection_csv(
                worker_session,
                source=ExternalSource.MANUAL,
                display_name="Manual test source",
                season="2026-27",
                csv_bytes=csv_bytes,
            )
            worker_session.commit()
            return outcome.projection_import.id
        finally:
            worker_session.rollback()
            worker_session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        import_ids = list(executor.map(run_import, csv_files))

    verification = database.session_factory()
    try:
        assert len(set(import_ids)) == 2
        assert verification.query(ProjectionImport).count() == 2
        assert verification.query(Projection).count() == 2
        source_links = (
            verification.query(PlayerExternalId)
            .filter(PlayerExternalId.source == ExternalSource.MANUAL)
            .all()
        )
        assert len(source_links) == 1
        assert source_links[0].current_for_source == ExternalSource.MANUAL.value
    finally:
        verification.close()


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


class TestProjectionTargetsAreNowPositionAware:
    """One of three consumers of ``players.primary_position``.

    ``build_player_targets`` has always passed ``position=player.primary_position``
    into ``ResolvableRecord.build``. That column was never written by anything
    until the ``PlayerIndex`` lane landed, so this resolver has been silently
    position-blind for its whole life and flips to position-aware the first
    time ``build_crosswalk`` runs.

    The other two: ``api/routes/projections.py`` serves the column as a
    response field, which likewise goes from always-``null`` to populated with
    no diff; and ``build_crosswalk`` **writes** it but does not read it — it
    feeds the resolver from the parsed records directly, so the crosswalk
    evidence the position lane published is a property of the parse path, not
    of anything persisted.

    Pinned here so the reader set is a recorded fact rather than a surprise,
    and so the identity lane re-tuning ``_DISAGREEMENT_PENALTY["position"]``
    knows which paths move with it.
    """

    def test_targets_carry_a_position_once_players_have_one(self, session: Session) -> None:
        seed_player(session, nba_id=1, name="Alpha Example", team_abbreviation="BOS")
        seed_player(session, nba_id=2, name="Beta Example", team_abbreviation="BOS", position="C")

        by_key = {t.key: t for t in build_player_targets(session)}

        assert by_key["1"].position is None, "a player with no listed position stays blind"
        assert by_key["2"].position == "C", (
            "once primary_position is populated this resolver compares on it; before the "
            "PlayerIndex lane it was None for every player and every comparison was UNKNOWN"
        )

    def test_a_coarse_mismatch_with_no_team_costs_a_correct_match(self, session: Session) -> None:
        """The Tillman shape, on the projections path.

        A vendor calling a borderline big ``C`` where the NBA lists ``F`` is
        the same human, but with no team to offset it the 0.12 position penalty
        drops the match under the accept floor. Identical to the regression the
        position lane recorded for the Fantrax crosswalk — same weights, same
        cause, different consumer.
        """
        seed_player(session, nba_id=3, name="Gamma Example", position="F")
        targets = build_player_targets(session)

        blind = IdentityResolver(
            [ResolvableRecord.build(key=t.key, name=t.raw_name, team=t.team) for t in targets]
        ).resolve([ResolvableRecord.build(key="v1", name="Gamma Example", position="C")])
        sighted = IdentityResolver(targets).resolve(
            [ResolvableRecord.build(key="v1", name="Gamma Example", position="C")]
        )

        blind_only = next(iter(blind.all_resolutions()))
        sighted_only = next(iter(sighted.all_resolutions()))

        assert blind_only.accepted is True
        assert blind_only.best is not None
        assert blind_only.best.evidence.position is FieldEvidence.UNKNOWN

        assert sighted_only.best is not None
        assert sighted_only.best.evidence.position is FieldEvidence.DISAGREE
        assert sighted_only.best.confidence < blind_only.best.confidence
        assert sighted_only.accepted is False
