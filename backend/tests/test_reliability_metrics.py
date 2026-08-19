"""Descriptive reliability scorecards and their fail-closed R35 boundary."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from hoops_gm.availability import (
    OBSERVED_COVERAGE_STATUS,
    CategoryConsistency,
    PlayerReliabilityScorecard,
    ReliabilityConfig,
    ReliabilityInputError,
    StaleReliabilityCohortError,
    compute_reliability_scorecards,
    publish_reliability_cohorts,
)
from hoops_gm.db.lineage import record_refresh
from hoops_gm.db.models import (
    DnpReason,
    ExternalSource,
    GameStatus,
    NbaGame,
    NbaTeam,
    ParticipationOutcome,
    Player,
    PlayerGameLog,
    PlayerParticipation,
    RefreshArtifactType,
    SeasonType,
    TeamScheduleEntry,
)

SEASON = "2025-26"


def _teams(session: Session) -> tuple[NbaTeam, NbaTeam]:
    home = NbaTeam(nba_team_id=1, abbreviation="HOM", name="Home")
    away = NbaTeam(nba_team_id=2, abbreviation="AWY", name="Away")
    session.add_all([home, away])
    session.flush()
    return home, away


def _player(session: Session, name: str) -> Player:
    player = Player(full_name=name, normalized_name=name.lower().replace(" ", ""))
    session.add(player)
    session.flush()
    return player


def _game(
    session: Session,
    *,
    number: int,
    game_date: date,
    home: NbaTeam,
    away: NbaTeam,
) -> NbaGame:
    game = NbaGame(
        season=SEASON,
        season_type=SeasonType.REGULAR,
        nba_game_id=f"00225{number:05d}",
        game_date=game_date,
        status=GameStatus.FINAL,
        home_team_id=home.id,
        away_team_id=away.id,
        home_score=110,
        away_score=100,
    )
    session.add(game)
    session.flush()
    session.add_all(
        [
            TeamScheduleEntry(
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=home.id,
                opponent_team_id=away.id,
                game_date=game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=away.id,
                opponent_team_id=home.id,
                game_date=game_date,
                is_home=False,
            ),
        ]
    )
    session.flush()
    return game


def _log(
    session: Session,
    *,
    player: Player,
    game: NbaGame,
    team: NbaTeam,
    seconds: int = 1800,
    points: int = 20,
    field_goals_made: int = 5,
    field_goals_attempted: int = 10,
    free_throws_made: int = 4,
    free_throws_attempted: int = 5,
) -> PlayerGameLog:
    row = PlayerGameLog(
        player_id=player.id,
        game_id=game.id,
        team_id=team.id,
        seconds_played=seconds,
        field_goals_made=field_goals_made,
        field_goals_attempted=field_goals_attempted,
        three_pointers_made=2,
        three_pointers_attempted=5,
        free_throws_made=free_throws_made,
        free_throws_attempted=free_throws_attempted,
        points=points,
        offensive_rebounds=1,
        defensive_rebounds=4,
        rebounds=5,
        assists=4,
        steals=1,
        blocks=1,
        turnovers=2,
        personal_fouls=2,
        plus_minus=0,
    )
    session.add(row)
    session.flush()
    return row


def _participation(
    session: Session,
    *,
    player: Player,
    game: NbaGame,
    team: NbaTeam,
    outcome: ParticipationOutcome,
) -> PlayerParticipation:
    row = PlayerParticipation(
        player_id=player.id,
        game_id=game.id,
        team_id=team.id,
        outcome=outcome,
        reason=DnpReason.NONE_GIVEN,
        raw_comment="",
        source=ExternalSource.NBA,
        inactive_list_available=True,
    )
    session.add(row)
    session.flush()
    return row


def _register_schedule(session: Session, version: str = "schedule-v1") -> None:
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        version=version,
        source="test",
        season=SEASON,
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def _scorecard(
    session: Session,
    player: Player,
    *,
    as_of: date,
    start: date | None = None,
) -> PlayerReliabilityScorecard:
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=as_of,
        window_start=start,
    )
    run = compute_reliability_scorecards(session, claim=claim)
    return next(row for row in run.scorecards if row.player_id == player.id)


def _category(scorecard: PlayerReliabilityScorecard, name: str) -> CategoryConsistency:
    return next(row for row in scorecard.production.categories if row.category == name)


def test_observed_rates_exclude_unknown_and_missing_rows(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Direct Evidence")
    games = [
        _game(session, number=1, game_date=date(2026, 1, 30), home=home, away=away),
        _game(session, number=2, game_date=date(2026, 1, 31), home=home, away=away),
        _game(session, number=3, game_date=date(2026, 2, 1), home=home, away=away),
        _game(session, number=4, game_date=date(2026, 2, 4), home=home, away=away),
    ]
    _register_schedule(session)
    played = _log(session, player=player, game=games[0], team=home)
    non_play = _participation(
        session,
        player=player,
        game=games[1],
        team=home,
        outcome=ParticipationOutcome.INACTIVE,
    )
    unknown = _participation(
        session,
        player=player,
        game=games[2],
        team=home,
        outcome=ParticipationOutcome.UNKNOWN,
    )
    # games[3] deliberately has no player row. R35 forbids inventing an outcome.

    scorecard = _scorecard(session, player, as_of=date(2026, 2, 4))
    overall = scorecard.availability.overall

    assert overall.direct_play == 1
    assert overall.direct_non_play == 1
    assert overall.explicit_unknown == 1
    assert overall.observed_opportunities == 2
    assert overall.observed_play_rate == 0.5
    assert overall.observed_non_play_rate == 0.5
    assert overall.coverage_status == OBSERVED_COVERAGE_STATUS
    assert overall.opportunity_coverage is None
    assert overall.game_log_ids == (played.id,)
    assert overall.participation_ids == (non_play.id, unknown.id)
    assert [row.month for row in scorecard.availability.monthly_trend] == [
        date(2026, 1, 1),
        date(2026, 2, 1),
    ]
    assert scorecard.availability.monthly_trend[1].evidence.observed_play_rate is None

    back_to_back = scorecard.availability.back_to_back
    assert back_to_back.direct_non_play == 1
    assert back_to_back.explicit_unknown == 1
    assert back_to_back.observed_non_play_rate == 1.0

    assert scorecard.production.played_games == 1
    assert scorecard.production.minutes.distribution_minutes.mean == 30.0
    assert not hasattr(scorecard, "grade")
    assert not hasattr(scorecard, "blowout_suppression")


def test_window_keeps_prior_schedule_needed_to_identify_first_game_b2b(
    session: Session,
) -> None:
    home, away = _teams(session)
    player = _player(session, "Windowed")
    current_team = NbaTeam(nba_team_id=3, abbreviation="NEW", name="New Team")
    session.add(current_team)
    session.flush()
    player.current_team_id = current_team.id
    _game(session, number=10, game_date=date(2026, 1, 1), home=home, away=away)
    second = _game(session, number=11, game_date=date(2026, 1, 2), home=home, away=away)
    _register_schedule(session)
    _participation(
        session,
        player=player,
        game=second,
        team=home,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
    )
    # At least one production row is required for a coherent source snapshot.
    other = _player(session, "Other")
    _log(session, player=other, game=second, team=home)

    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=date(2026, 1, 2),
        window_start=date(2026, 1, 2),
    )
    run = compute_reliability_scorecards(session, claim=claim)
    scorecard = next(row for row in run.scorecards if row.player_id == player.id)

    assert scorecard.availability.back_to_back.direct_non_play == 1
    assert scorecard.availability.back_to_back.observed_non_play_rate == 1.0
    # The player changed teams after this game; density still follows the team
    # stored on the historical participation row.
    assert current_team.id != home.id
    assert run.schedule_context_team_games == 4
    assert run.scheduled_team_games == 2


def test_final_game_without_exact_schedule_coverage_fails_loudly(
    session: Session,
) -> None:
    home, away = _teams(session)
    scheduled = _game(
        session,
        number=12,
        game_date=date(2026, 1, 3),
        home=home,
        away=away,
    )
    player = _player(session, "Missing Schedule")
    _log(session, player=player, game=scheduled, team=home)
    missing = NbaGame(
        season=SEASON,
        season_type=SeasonType.REGULAR,
        nba_game_id="0022500013",
        game_date=date(2026, 1, 4),
        status=GameStatus.FINAL,
        home_team_id=home.id,
        away_team_id=away.id,
        home_score=100,
        away_score=90,
    )
    session.add(missing)
    session.flush()
    _log(session, player=player, game=missing, team=home)
    _register_schedule(session)

    with pytest.raises(ReliabilityInputError, match="team_schedule coverage"):
        publish_reliability_cohorts(
            session,
            season=SEASON,
            as_of_date=missing.game_date,
        )


def test_unknown_participation_does_not_override_game_log_play(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Observed Player")
    game = _game(session, number=20, game_date=date(2026, 2, 10), home=home, away=away)
    _register_schedule(session)
    _log(session, player=player, game=game, team=home)
    _participation(
        session,
        player=player,
        game=game,
        team=home,
        outcome=ParticipationOutcome.UNKNOWN,
    )

    scorecard = _scorecard(session, player, as_of=game.game_date)

    assert scorecard.availability.overall.direct_play == 1
    assert scorecard.availability.overall.explicit_unknown == 0


def test_play_and_non_play_contradiction_fails_loudly(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Contradiction")
    game = _game(session, number=30, game_date=date(2026, 2, 20), home=home, away=away)
    _register_schedule(session)
    _log(session, player=player, game=game, team=home)
    _participation(
        session,
        player=player,
        game=game,
        team=home,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
    )
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )

    with pytest.raises(ReliabilityInputError, match="game log"):
        compute_reliability_scorecards(session, claim=claim)


def test_minutes_and_category_dispersion_use_played_games_only(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Variable")
    games = [
        _game(
            session,
            number=40 + index,
            game_date=date(2026, 3, 1 + index),
            home=home,
            away=away,
        )
        for index in range(6)
    ]
    _register_schedule(session)
    for game, minute_count, point_count in zip(
        games[:5],
        (10, 20, 30, 40, 50),
        (10, 20, 30, 40, 50),
        strict=True,
    ):
        _log(
            session,
            player=player,
            game=game,
            team=home,
            seconds=minute_count * 60,
            points=point_count,
        )
    _participation(
        session,
        player=player,
        game=games[5],
        team=home,
        outcome=ParticipationOutcome.INACTIVE,
    )

    scorecard = _scorecard(session, player, as_of=games[-1].game_date)
    minutes = scorecard.production.minutes
    points = _category(scorecard, "pts").distribution

    assert scorecard.production.played_games == 5
    assert minutes.distribution_minutes.mean == 30.0
    assert minutes.distribution_minutes.sample_standard_deviation == pytest.approx(math.sqrt(250))
    assert minutes.coefficient_of_variation == pytest.approx(math.sqrt(250) / 30)
    assert minutes.distribution_minutes.lower_percentile_probability == 0.2
    assert minutes.distribution_minutes.upper_percentile_probability == 0.8
    assert minutes.distribution_minutes.lower_percentile == 18.0
    assert minutes.distribution_minutes.upper_percentile == 42.0
    assert points.observed_games == 5
    assert points.sample_standard_deviation == pytest.approx(math.sqrt(250))


def test_sparse_zero_mean_minutes_do_not_manufacture_cv_or_variance(
    session: Session,
) -> None:
    home, away = _teams(session)
    player = _player(session, "Sparse")
    game = _game(session, number=55, game_date=date(2026, 3, 20), home=home, away=away)
    _register_schedule(session)
    _log(session, player=player, game=game, team=home, seconds=0, points=0)

    scorecard = _scorecard(session, player, as_of=game.game_date)
    minutes = scorecard.production.minutes
    points = _category(scorecard, "pts").distribution

    assert minutes.distribution_minutes.observed_games == 1
    assert minutes.distribution_minutes.mean == 0
    assert minutes.distribution_minutes.sample_standard_deviation is None
    assert minutes.coefficient_of_variation is None
    assert points.sample_standard_deviation is None
    assert points.lower_percentile == points.upper_percentile == 0


def test_ratio_variability_is_volume_weighted_impact_not_raw_percentage(
    session: Session,
) -> None:
    home, away = _teams(session)
    low_volume = _player(session, "Low Volume")
    high_volume = _player(session, "High Volume")
    baseline_anchor = _player(session, "Baseline Anchor")
    game = _game(session, number=60, game_date=date(2026, 4, 1), home=home, away=away)
    _register_schedule(session)
    _log(
        session,
        player=low_volume,
        game=game,
        team=home,
        field_goals_made=1,
        field_goals_attempted=1,
    )
    _log(
        session,
        player=high_volume,
        game=game,
        team=home,
        field_goals_made=9,
        field_goals_attempted=10,
    )
    _log(
        session,
        player=baseline_anchor,
        game=game,
        team=away,
        field_goals_made=0,
        field_goals_attempted=9,
    )

    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )
    run = compute_reliability_scorecards(session, claim=claim)
    by_player = {row.player_id: row for row in run.scorecards}
    low = _category(by_player[low_volume.id], "fg_pct")
    high = _category(by_player[high_volume.id], "fg_pct")

    assert low.ratio_baseline is not None
    assert low.ratio_baseline.rate == 0.5
    assert low.distribution.mean == 0.5
    assert high.distribution.mean == 4.0
    assert high.distribution.mean > low.distribution.mean


def test_invalid_shooting_components_fail_before_a_scorecard_is_returned(
    session: Session,
) -> None:
    home, away = _teams(session)
    player = _player(session, "Invalid Shooter")
    game = _game(session, number=70, game_date=date(2026, 4, 10), home=home, away=away)
    _register_schedule(session)
    _log(
        session,
        player=player,
        game=game,
        team=home,
        field_goals_made=2,
        field_goals_attempted=1,
    )
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )

    with pytest.raises(ReliabilityInputError, match="invalid shooting components"):
        compute_reliability_scorecards(session, claim=claim)


def test_negative_counting_stat_fails_before_a_scorecard_is_returned(
    session: Session,
) -> None:
    home, away = _teams(session)
    player = _player(session, "Invalid Counter")
    game = _game(session, number=71, game_date=date(2026, 4, 11), home=home, away=away)
    _register_schedule(session)
    _log(session, player=player, game=game, team=home, points=-1)
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )

    with pytest.raises(ReliabilityInputError, match="negative points"):
        compute_reliability_scorecards(session, claim=claim)


def test_changed_source_after_publication_is_rejected(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Changed Source")
    game = _game(session, number=80, game_date=date(2026, 5, 1), home=home, away=away)
    _register_schedule(session)
    log = _log(session, player=player, game=game, team=home)
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )
    log.points = 99
    session.flush()

    with pytest.raises(StaleReliabilityCohortError, match="observations changed"):
        compute_reliability_scorecards(session, claim=claim)


def test_changed_participation_after_publication_is_rejected(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Changed Participation")
    game = _game(session, number=81, game_date=date(2026, 5, 2), home=home, away=away)
    _register_schedule(session)
    other = _player(session, "Production Anchor")
    _log(session, player=other, game=game, team=away)
    participation = _participation(
        session,
        player=player,
        game=game,
        team=home,
        outcome=ParticipationOutcome.UNKNOWN,
    )
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )
    participation.outcome = ParticipationOutcome.INACTIVE
    session.flush()

    with pytest.raises(StaleReliabilityCohortError, match="observations changed"):
        compute_reliability_scorecards(session, claim=claim)


def test_window_change_has_distinct_source_lineage_and_stales_prior_claim(
    session: Session,
) -> None:
    home, away = _teams(session)
    player = _player(session, "Window Lineage")
    first = _game(session, number=82, game_date=date(2026, 5, 3), home=home, away=away)
    second = _game(session, number=83, game_date=date(2026, 5, 4), home=home, away=away)
    _register_schedule(session)
    _log(session, player=player, game=first, team=home)
    _log(session, player=player, game=second, team=home)
    season_claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=second.game_date,
    )
    window_claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        window_start=second.game_date,
        as_of_date=second.game_date,
    )

    assert season_claim.source_version != window_claim.source_version
    with pytest.raises(StaleReliabilityCohortError, match="stale source"):
        compute_reliability_scorecards(session, claim=season_claim)


def test_stale_schedule_and_config_claims_are_rejected(session: Session) -> None:
    home, away = _teams(session)
    player = _player(session, "Stale")
    game = _game(session, number=90, game_date=date(2026, 5, 10), home=home, away=away)
    _register_schedule(session)
    _log(session, player=player, game=game, team=home)
    claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )
    _register_schedule(session, "schedule-v2")

    with pytest.raises(StaleReliabilityCohortError, match="stale schedule"):
        compute_reliability_scorecards(session, claim=claim)

    # Republish on the current schedule, then supply a differently versioned config.
    current_claim = publish_reliability_cohorts(
        session,
        season=SEASON,
        as_of_date=game.game_date,
    )
    with pytest.raises(StaleReliabilityCohortError, match="config"):
        compute_reliability_scorecards(
            session,
            claim=current_claim,
            config=ReliabilityConfig(lower_percentile=0.10, upper_percentile=0.90),
        )
