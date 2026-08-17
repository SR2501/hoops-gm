"""Schema guarantees.

These tests exist because the failure mode they guard against is silent. A
mis-modelled identity row or a discarded shooting denominator does not raise;
it produces a confident, wrong number several phases later.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from hoops_gm.db.models import (
    CategoryKind,
    ExternalSource,
    FantasyTeam,
    League,
    LeagueScoringCategory,
    LeagueScoringProfile,
    MatchMethod,
    NbaGame,
    NbaTeam,
    Player,
    PlayerExternalId,
    PlayerGameLog,
    PlayerSeasonStat,
    RosterEntry,
    ScoringPeriod,
    StatScope,
)


def _team(session: Session, abbrev: str = "BOS", nba_id: int = 1610612738) -> NbaTeam:
    team = NbaTeam(nba_team_id=nba_id, abbreviation=abbrev, name=f"{abbrev} team")
    session.add(team)
    session.flush()
    return team


def _player(session: Session, name: str = "Jayson Tatum") -> Player:
    player = Player(full_name=name, normalized_name=name.lower().replace(" ", ""))
    session.add(player)
    session.flush()
    return player


# --- Identity: risk R7 --------------------------------------------------------


def test_one_external_id_maps_to_one_player(session: Session) -> None:
    """The same upstream identifier may not point at two people."""
    first = _player(session, "Marcus Smart")
    second = _player(session, "Marcus Morris")

    session.add(
        PlayerExternalId(player_id=first.id, source=ExternalSource.FANTRAX, external_id="*04abc*")
    )
    session.flush()

    session.add(
        PlayerExternalId(player_id=second.id, source=ExternalSource.FANTRAX, external_id="*04abc*")
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_the_same_identifier_may_recur_across_sources(session: Session) -> None:
    """Fantrax and NBA identifier spaces are unrelated and may collide."""
    player = _player(session)

    session.add_all(
        [
            PlayerExternalId(player_id=player.id, source=ExternalSource.FANTRAX, external_id="123"),
            PlayerExternalId(player_id=player.id, source=ExternalSource.NBA, external_id="123"),
        ]
    )
    session.flush()

    assert len(player.external_ids) == 2


def test_a_player_carries_identifiers_from_every_source(session: Session) -> None:
    player = _player(session)
    session.add_all(
        [
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                external_id="1628369",
                match_method=MatchMethod.ANCHOR_ID,
                confidence=1.0,
            ),
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.FANTRAX,
                external_id="*04qm5*",
                match_method=MatchMethod.ANCHOR_ID,
                confidence=1.0,
            ),
            # A projection CSV has no identifier at all — the raw name string is
            # the evidence, and it has to survive for a disputed match.
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.FANTASYPROS,
                external_id="fantasypros:jayson-tatum",
                external_name="Jayson Tatum",
                normalized_name="jaysontatum",
                external_team="BOS",
                external_position="SF",
                match_method=MatchMethod.NAME_TEAM_POSITION,
                confidence=0.82,
            ),
        ]
    )
    session.flush()

    sources = {row.source for row in player.external_ids}
    assert sources == {
        ExternalSource.NBA,
        ExternalSource.FANTRAX,
        ExternalSource.FANTASYPROS,
    }


def test_confidence_must_be_a_probability(session: Session) -> None:
    player = _player(session)

    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.DARKO,
            external_id="x",
            confidence=1.4,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_low_confidence_matches_are_queryable(session: Session) -> None:
    """Phase 2 needs the unmatched report to be a query, not a re-derivation."""
    player = _player(session)
    session.add_all(
        [
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                external_id="1",
                confidence=1.0,
            ),
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.HASHTAG,
                external_id="2",
                confidence=0.41,
                match_method=MatchMethod.FUZZY,
            ),
        ]
    )
    session.flush()

    suspect = session.query(PlayerExternalId).filter(PlayerExternalId.confidence < 0.9).all()
    assert [row.source for row in suspect] == [ExternalSource.HASHTAG]


def test_a_manual_override_is_representable_and_flagged(session: Session) -> None:
    """The resolver must be able to see that a human decided this one."""
    player = _player(session)
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source=ExternalSource.BASKETBALL_MONSTER,
            external_id="bbm-4412",
            external_name="J. Tatum",
            confidence=1.0,
            match_method=MatchMethod.MANUAL_OVERRIDE,
            is_manual_override=True,
            reviewed_at=date(2026, 8, 17),
            notes="Initials-only name string; confirmed by hand.",
        )
    )
    session.flush()

    protected = (
        session.query(PlayerExternalId).filter(PlayerExternalId.is_manual_override.is_(True)).one()
    )
    assert protected.match_method is MatchMethod.MANUAL_OVERRIDE
    assert protected.reviewed_at == date(2026, 8, 17)


def test_unknown_enum_values_are_rejected(session: Session) -> None:
    player = _player(session)
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source="espn",
            external_id="1",
        )
    )
    with pytest.raises((StatementError, LookupError, IntegrityError)):
        session.flush()


# --- Referential integrity ----------------------------------------------------


def test_foreign_keys_are_enforced_on_sqlite(session: Session) -> None:
    """Without PRAGMA foreign_keys=ON, SQLite accepts this and Postgres does not."""
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()
    team = FantasyTeam(league_id=league.id, name="My Team")
    session.add(team)
    session.flush()

    session.add(RosterEntry(fantasy_team_id=team.id, player_id=999_999))
    with pytest.raises(IntegrityError):
        session.flush()


# --- Stats: risk R9 -----------------------------------------------------------


@pytest.mark.parametrize("model", [PlayerGameLog, PlayerSeasonStat])
def test_box_scores_store_attempts_not_percentages(
    model: type[PlayerGameLog] | type[PlayerSeasonStat],
) -> None:
    """A stored percentage has thrown the denominator away.

    Volume-weighted FG%/FT% impact cannot be reconstructed from a percentage,
    and that reconstruction is exactly what separates a 90%-on-one-attempt
    shooter from a real contributor.
    """
    columns = set(model.__table__.columns.keys())

    assert {"field_goals_made", "field_goals_attempted"} <= columns
    assert {"free_throws_made", "free_throws_attempted"} <= columns
    assert {"three_pointers_made", "three_pointers_attempted"} <= columns
    assert not [name for name in columns if "pct" in name or "percent" in name]


def test_minutes_are_stored_as_whole_seconds() -> None:
    assert "seconds_played" in PlayerGameLog.__table__.columns
    assert "minutes" not in PlayerGameLog.__table__.columns


def test_a_player_has_one_log_per_game(session: Session) -> None:
    team = _team(session)
    opponent = _team(session, "NYK", 1610612752)
    player = _player(session)
    game = NbaGame(
        season="2026-27",
        nba_game_id="0022600001",
        game_date=date(2026, 10, 21),
        home_team_id=team.id,
        away_team_id=opponent.id,
    )
    session.add(game)
    session.flush()

    session.add(PlayerGameLog(player_id=player.id, game_id=game.id, team_id=team.id, points=30))
    session.flush()

    session.add(PlayerGameLog(player_id=player.id, game_id=game.id, team_id=team.id, points=31))
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_traded_player_has_one_row_per_team_and_one_total(session: Session) -> None:
    boston = _team(session)
    knicks = _team(session, "NYK", 1610612752)
    player = _player(session)

    session.add_all(
        [
            PlayerSeasonStat(
                player_id=player.id,
                season="2026-27",
                scope=StatScope.TEAM,
                team_key="BOS",
                team_id=boston.id,
                games_played=40,
            ),
            PlayerSeasonStat(
                player_id=player.id,
                season="2026-27",
                scope=StatScope.TEAM,
                team_key="NYK",
                team_id=knicks.id,
                games_played=30,
            ),
            PlayerSeasonStat(
                player_id=player.id,
                season="2026-27",
                scope=StatScope.TOTAL,
                team_key="TOT",
                team_id=None,
                games_played=70,
            ),
        ]
    )
    session.flush()

    assert session.query(PlayerSeasonStat).count() == 3


def test_duplicate_season_totals_are_rejected(session: Session) -> None:
    """A nullable team_id in the unique key would not catch this on any dialect."""
    player = _player(session)
    session.add(
        PlayerSeasonStat(
            player_id=player.id, season="2026-27", scope=StatScope.TOTAL, games_played=70
        )
    )
    session.flush()

    session.add(
        PlayerSeasonStat(
            player_id=player.id, season="2026-27", scope=StatScope.TOTAL, games_played=71
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_team_scoped_season_row_requires_a_team(session: Session) -> None:
    player = _player(session)
    session.add(
        PlayerSeasonStat(
            player_id=player.id,
            season="2026-27",
            scope=StatScope.TEAM,
            team_key="BOS",
            team_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_total_row_may_not_claim_a_team(session: Session) -> None:
    boston = _team(session)
    player = _player(session)
    session.add(
        PlayerSeasonStat(
            player_id=player.id,
            season="2026-27",
            scope=StatScope.TOTAL,
            team_key="TOT",
            team_id=boston.id,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


# --- League: versioning seam and ratio categories -----------------------------


def test_scoring_profiles_are_versioned(session: Session) -> None:
    """The seam every stored valuation will hang off.

    A valuation records the profile row that produced it. That only means
    something if a profile is immutable and a change is a new version.
    """
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()

    session.add(LeagueScoringProfile(league_id=league.id, name="default", version=1))
    session.flush()

    session.add(LeagueScoringProfile(league_id=league.id, name="default", version=2))
    session.flush()

    assert {profile.version for profile in league.scoring_profiles} == {1, 2}

    session.add(LeagueScoringProfile(league_id=league.id, name="default", version=2))
    with pytest.raises(IntegrityError):
        session.flush()


def test_ratio_categories_must_carry_their_components(session: Session) -> None:
    """FG% without makes and attempts cannot be volume-weighted."""
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()
    profile = LeagueScoringProfile(league_id=league.id)
    session.add(profile)
    session.flush()

    session.add(
        LeagueScoringCategory(
            profile_id=profile.id, key="fg_pct", label="FG%", kind=CategoryKind.RATIO
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_nine_category_profile_is_expressible(session: Session) -> None:
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()
    profile = LeagueScoringProfile(league_id=league.id)
    session.add(profile)
    session.flush()

    session.add_all(
        [
            LeagueScoringCategory(
                profile_id=profile.id,
                key="fg_pct",
                label="FG%",
                kind=CategoryKind.RATIO,
                numerator_stat="field_goals_made",
                denominator_stat="field_goals_attempted",
                display_order=1,
            ),
            LeagueScoringCategory(
                profile_id=profile.id,
                key="ft_pct",
                label="FT%",
                kind=CategoryKind.RATIO,
                numerator_stat="free_throws_made",
                denominator_stat="free_throws_attempted",
                display_order=2,
            ),
            *[
                LeagueScoringCategory(
                    profile_id=profile.id,
                    key=key,
                    label=key.upper(),
                    kind=CategoryKind.COUNTING,
                    display_order=order,
                )
                for order, key in enumerate(["fg3m", "pts", "reb", "ast", "stl", "blk"], start=3)
            ],
            # Turnovers score in the opposite direction. The sign lives in the
            # data so the engine never special-cases a category name.
            LeagueScoringCategory(
                profile_id=profile.id,
                key="to",
                label="TO",
                kind=CategoryKind.COUNTING,
                direction=-1,
                display_order=9,
            ),
        ]
    )
    session.flush()

    assert len(profile.categories) == 9
    negatives = [c.key for c in profile.categories if c.direction == -1]
    assert negatives == ["to"]


def test_category_direction_must_be_a_sign(session: Session) -> None:
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()
    profile = LeagueScoringProfile(league_id=league.id)
    session.add(profile)
    session.flush()

    session.add(LeagueScoringCategory(profile_id=profile.id, key="pts", label="PTS", direction=0))
    with pytest.raises(IntegrityError):
        session.flush()


def test_playoff_scoring_periods_are_flagged(session: Session) -> None:
    """Playoff-week schedule strength must be answerable during the draft."""
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()

    session.add_all(
        [
            ScoringPeriod(
                league_id=league.id,
                period_number=n,
                start_date=date(2026, 10, 19),
                end_date=date(2026, 10, 25),
                is_playoff=n >= 21,
            )
            for n in (1, 21, 22)
        ]
    )
    session.flush()

    playoff_weeks = session.query(ScoringPeriod).filter(ScoringPeriod.is_playoff.is_(True)).count()
    assert playoff_weeks == 2


def test_scoring_period_dates_must_be_ordered(session: Session) -> None:
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()

    session.add(
        ScoringPeriod(
            league_id=league.id,
            period_number=1,
            start_date=date(2026, 10, 25),
            end_date=date(2026, 10, 19),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
