"""Schema guarantees.

These tests exist because the failure mode they guard against is silent. A
mis-modelled identity row or a discarded shooting denominator does not raise;
it produces a confident, wrong number several phases later.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from hoops_gm.db.base import Base
from hoops_gm.db.models import (
    CategoryKind,
    ExternalSource,
    FantasyTeam,
    League,
    LeagueScoringCategory,
    LeagueScoringProfile,
    MatchMethod,
    Matchup,
    MatchupCategoryResult,
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
from hoops_gm.db.models.stats import BOX_SCORE_STAT_KEYS


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


def _profile(session: Session) -> LeagueScoringProfile:
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()
    profile = LeagueScoringProfile(league_id=league.id)
    session.add(profile)
    session.flush()
    return profile


def _external_id(player_id: int, **overrides: object) -> PlayerExternalId:
    """Build a row with the fields the schema now requires stated explicitly."""
    values: dict[str, object] = {
        "player_id": player_id,
        "source": ExternalSource.FANTRAX,
        "external_id": "*04abc*",
        "match_method": MatchMethod.NAME_TEAM_POSITION,
        "confidence": 0.9,
    }
    values.update(overrides)
    return PlayerExternalId(**values)


# --- Identity: risk R7 --------------------------------------------------------


def test_one_external_id_maps_to_one_player(session: Session) -> None:
    """The same upstream identifier may not point at two people."""
    first = _player(session, "Marcus Smart")
    second = _player(session, "Marcus Morris")

    session.add(_external_id(first.id))
    session.flush()

    session.add(_external_id(second.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_the_same_identifier_may_recur_across_sources(session: Session) -> None:
    """Fantrax and NBA identifier spaces are unrelated and may collide."""
    player = _player(session)

    session.add_all(
        [
            _external_id(player.id, source=ExternalSource.FANTRAX, external_id="123"),
            _external_id(player.id, source=ExternalSource.NBA, external_id="123"),
        ]
    )
    session.flush()

    assert len(player.external_ids) == 2


def test_match_method_has_no_default(session: Session) -> None:
    """A forgotten field must not assert the strongest possible provenance.

    It used to default to ``ANCHOR_ID`` with ``confidence=1.0`` — "matched on
    a shared identifier, fully confident" — for a crosswalk where no shared
    identifier exists at all. On the project's highest-severity risk the silent
    default has to be the pessimistic one.
    """
    player = _player(session)
    session.add(
        PlayerExternalId(
            player_id=player.id, source=ExternalSource.FANTRAX, external_id="no-method"
        )
    )

    with pytest.raises((IntegrityError, StatementError)):
        session.flush()


def test_confidence_defaults_to_zero(session: Session) -> None:
    player = _player(session)
    row = PlayerExternalId(
        player_id=player.id,
        source=ExternalSource.FANTRAX,
        external_id="unstated",
        match_method=MatchMethod.FUZZY,
    )
    session.add(row)
    session.flush()

    assert row.confidence == 0.0


def test_a_player_carries_identifiers_from_every_source(session: Session) -> None:
    player = _player(session)
    session.add_all(
        [
            _external_id(
                player.id,
                source=ExternalSource.NBA,
                external_id="1628369",
                match_method=MatchMethod.NORMALIZED_NAME,
                confidence=0.95,
            ),
            _external_id(
                player.id,
                source=ExternalSource.FANTRAX,
                external_id="*04qm5*",
                match_method=MatchMethod.NORMALIZED_NAME,
                confidence=0.95,
            ),
            # A projection CSV has no identifier at all — the raw name string is
            # the evidence, and it has to survive for a disputed match.
            _external_id(
                player.id,
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


def test_only_one_identifier_per_source_may_be_current(session: Session) -> None:
    """Review finding 7: two current Fantrax rows fan out every crosswalk join."""
    player = _player(session)
    session.add(_external_id(player.id, external_id="*old*", current_for_source="fantrax"))
    session.flush()

    session.add(_external_id(player.id, external_id="*new*", current_for_source="fantrax"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_superseded_identifier_is_retained_alongside_the_current_one(
    session: Session,
) -> None:
    """History must survive without competing for the join."""
    player = _player(session)
    session.add_all(
        [
            _external_id(player.id, external_id="*2025*", current_for_source=None),
            _external_id(player.id, external_id="*2026*", current_for_source="fantrax"),
        ]
    )
    session.flush()

    assert len(player.external_ids) == 2
    current = (
        session.query(PlayerExternalId)
        .filter(
            PlayerExternalId.player_id == player.id,
            PlayerExternalId.current_for_source == "fantrax",
        )
        .one()
    )
    assert current.external_id == "*2026*"


def test_sibling_identifiers_across_sources_may_all_be_current(
    session: Session,
) -> None:
    """The other half of finding 7, reconciled deliberately.

    Fantrax exposes ``statsIncId``, ``rotowireId`` and ``sportRadarId``. Those
    are separate sources and every one of them is current at the same time.
    The constraint is one current row *per source*, not per player.
    """
    player = _player(session)
    session.add_all(
        [
            _external_id(
                player.id,
                source=ExternalSource.FANTRAX,
                external_id="*04qm5*",
                current_for_source="fantrax",
            ),
            _external_id(
                player.id,
                source=ExternalSource.NBA,
                external_id="1628369",
                current_for_source="nba",
            ),
            _external_id(
                player.id,
                source=ExternalSource.DARKO,
                external_id="darko-9",
                current_for_source="darko",
            ),
        ]
    )
    session.flush()

    assert len(player.external_ids) == 3


def test_the_current_marker_must_match_its_source(session: Session) -> None:
    """The marker is a sentinel, not a free-text field."""
    player = _player(session)
    session.add(_external_id(player.id, source=ExternalSource.FANTRAX, current_for_source="nba"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_confidence_must_be_a_probability(session: Session) -> None:
    player = _player(session)

    session.add(_external_id(player.id, source=ExternalSource.DARKO, confidence=1.4))
    with pytest.raises(IntegrityError):
        session.flush()


def test_low_confidence_matches_are_queryable(session: Session) -> None:
    """Phase 2 needs the unmatched report to be a query, not a re-derivation."""
    player = _player(session)
    session.add_all(
        [
            _external_id(player.id, source=ExternalSource.NBA, external_id="1", confidence=0.99),
            _external_id(
                player.id,
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
        _external_id(
            player.id,
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


def test_unknown_enum_values_are_rejected_by_the_orm(session: Session) -> None:
    """The ORM half of the enum guarantee.

    This test used to be the *only* enforcement, and it passed against a schema
    with no CHECK constraint at all — SQLAlchemy rejected the value in Python
    before it ever reached the database. The database half now lives in
    ``test_database_guarantees.py`` and goes through raw SQL.
    """
    player = _player(session)
    session.add(
        PlayerExternalId(
            player_id=player.id,
            source="espn",
            external_id="1",
            match_method=MatchMethod.FUZZY,
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


#: Tables permitted to hold a column whose name looks like a percentage.
#: Deliberately empty. If a future phase needs one, adding it here forces the
#: person to justify it in a diff rather than discover the problem in a
#: valuation six months later.
PERCENTAGE_COLUMN_ALLOWLIST: dict[str, set[str]] = {}


def test_no_table_anywhere_stores_a_percentage() -> None:
    """R9, as a rule rather than a snapshot.

    The earlier version of this test parametrised over a hardcoded
    ``[PlayerGameLog, PlayerSeasonStat]``. That is exactly the wrong shape: the
    tables where the R9 bug actually lives — ``projections``,
    ``blended_projections``, ``valuations``, ``risk_adjusted_valuations`` —
    arrive in Phases 3 to 5, and a hardcoded list would never have seen them.

    A stored percentage has discarded its denominator, and volume-weighted
    impact cannot be reconstructed from it. A 90% free-throw shooter on one
    attempt is worthless, and no amount of downstream care recovers the
    attempts once they are gone.
    """
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if ("pct" in column.name or "percent" in column.name)
        and column.name not in PERCENTAGE_COLUMN_ALLOWLIST.get(table.name, set())
    ]

    assert offenders == [], (
        "store makes and attempts, not a percentage — see risk R9. If a column "
        "here is genuinely not a fantasy ratio, add it to "
        "PERCENTAGE_COLUMN_ALLOWLIST with a comment saying why."
    )


@pytest.mark.parametrize("model", [PlayerGameLog, PlayerSeasonStat])
def test_box_scores_store_attempts(
    model: type[PlayerGameLog] | type[PlayerSeasonStat],
) -> None:
    """The positive half: the components must actually be present."""
    columns = set(model.__table__.columns.keys())

    assert {"field_goals_made", "field_goals_attempted"} <= columns
    assert {"free_throws_made", "free_throws_attempted"} <= columns
    assert {"three_pointers_made", "three_pointers_attempted"} <= columns


def test_the_stat_vocabulary_matches_the_box_score_columns() -> None:
    """``BOX_SCORE_STAT_KEYS`` is written out by hand; this stops it drifting.

    It is written out rather than derived because its contents end up inside a
    CHECK constraint in a migration.
    """
    structural = {"id", "player_id", "game_id", "team_id", "started", "created_at", "updated_at"}
    actual = set(PlayerGameLog.__table__.columns.keys()) - structural

    assert set(BOX_SCORE_STAT_KEYS) == actual


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
    profile = _profile(session)

    session.add(
        LeagueScoringCategory(
            profile_id=profile.id, key="fg_pct", label="FG%", kind=CategoryKind.RATIO
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_percentage_key_may_not_be_declared_a_counting_category(
    session: Session,
) -> None:
    """R9 stated outright: ``fg_pct`` as COUNTING inserted cleanly before."""
    profile = _profile(session)

    session.add(
        LeagueScoringCategory(
            profile_id=profile.id, key="fg_pct", label="FG%", kind=CategoryKind.COUNTING
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_ratio_components_must_name_real_box_score_columns(session: Session) -> None:
    """A typo makes the category unweightable, silently."""
    profile = _profile(session)

    session.add(
        LeagueScoringCategory(
            profile_id=profile.id,
            key="ft_pct",
            label="FT%",
            kind=CategoryKind.RATIO,
            numerator_stat="ftm_typo",
            denominator_stat="not_a_column",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_valid_ratio_components_are_accepted(session: Session) -> None:
    profile = _profile(session)

    session.add(
        LeagueScoringCategory(
            profile_id=profile.id,
            key="ft_pct",
            label="FT%",
            kind=CategoryKind.RATIO,
            numerator_stat="free_throws_made",
            denominator_stat="free_throws_attempted",
        )
    )
    session.flush()

    assert len(profile.categories) == 1


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
    profile = _profile(session)

    session.add(LeagueScoringCategory(profile_id=profile.id, key="pts", label="PTS", direction=0))
    with pytest.raises(IntegrityError):
        session.flush()


def _matchup(session: Session) -> Matchup:
    league = League(name="Test League", season="2026-27")
    session.add(league)
    session.flush()
    home = FantasyTeam(league_id=league.id, name="Home")
    away = FantasyTeam(league_id=league.id, name="Away")
    period = ScoringPeriod(
        league_id=league.id,
        period_number=1,
        start_date=date(2026, 10, 19),
        end_date=date(2026, 10, 25),
    )
    session.add_all([home, away, period])
    session.flush()
    matchup = Matchup(scoring_period_id=period.id, home_team_id=home.id, away_team_id=away.id)
    session.add(matchup)
    session.flush()
    return matchup


def test_a_matchup_ratio_result_may_not_store_a_bare_percentage(
    session: Session,
) -> None:
    """Fantrax's matchup feed supplies ``.478`` directly.

    Storing it without the components is the path of least resistance in Phase 2
    ingest, and it is exactly risk R9. It used to insert cleanly.
    """
    matchup = _matchup(session)

    session.add(
        MatchupCategoryResult(
            matchup_id=matchup.id,
            category_key="fg_pct",
            kind=CategoryKind.RATIO,
            home_value=Decimal("0.478"),
            away_value=Decimal("0.455"),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_matchup_percentage_key_may_not_be_counting(session: Session) -> None:
    matchup = _matchup(session)

    session.add(
        MatchupCategoryResult(
            matchup_id=matchup.id,
            category_key="fg_pct",
            kind=CategoryKind.COUNTING,
            home_value=Decimal("0.478"),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_matchup_ratio_result_with_components_is_accepted(session: Session) -> None:
    """ "How many makes from how many attempts do I still need" must be answerable."""
    matchup = _matchup(session)

    session.add(
        MatchupCategoryResult(
            matchup_id=matchup.id,
            category_key="fg_pct",
            kind=CategoryKind.RATIO,
            home_value=Decimal("0.478"),
            home_numerator=Decimal("196"),
            home_denominator=Decimal("410"),
            away_value=Decimal("0.455"),
            away_numerator=Decimal("182"),
            away_denominator=Decimal("400"),
        )
    )
    session.flush()

    assert len(matchup.category_results) == 1


def test_a_matchup_counting_result_needs_no_components(session: Session) -> None:
    matchup = _matchup(session)

    session.add(
        MatchupCategoryResult(
            matchup_id=matchup.id,
            category_key="pts",
            kind=CategoryKind.COUNTING,
            home_value=Decimal("612"),
            away_value=Decimal("598"),
        )
    )
    session.flush()

    assert len(matchup.category_results) == 1


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
