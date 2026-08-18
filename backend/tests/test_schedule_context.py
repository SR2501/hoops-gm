from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from hoops_gm.db.lineage import content_fingerprint, record_refresh
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.schedule_context import OffNightSlate, OpponentContext
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.schedule_context import (
    ContextGame,
    GameResult,
    ScheduleContextConfig,
    StaleContextCohortError,
    TeamGameStats,
    build_off_night_facts,
    build_opponent_profile,
    compute_schedule_context,
    evaluate_blowout_model,
    fit_blowout_model,
    publish_schedule_context_cohorts,
)


def _schedule_entry(identifier: int, game_id: int, game_date: date) -> TeamScheduleEntry:
    return TeamScheduleEntry(
        id=identifier,
        season="2026-27",
        game_id=game_id,
        team_id=1,
        opponent_team_id=2,
        game_date=game_date,
        is_home=True,
    )


def _team_stats(
    *,
    field_goals_made: int = 40,
    field_goals_attempted: int = 85,
    three_pointers_made: int = 12,
    free_throws_made: int = 18,
    free_throws_attempted: int = 22,
    points: int = 110,
    offensive_rebounds: int = 10,
    rebounds: int = 44,
    assists: int = 25,
    steals: int = 7,
    blocks: int = 5,
    turnovers: int = 13,
) -> TeamGameStats:
    return TeamGameStats(
        field_goals_made=field_goals_made,
        field_goals_attempted=field_goals_attempted,
        three_pointers_made=three_pointers_made,
        free_throws_made=free_throws_made,
        free_throws_attempted=free_throws_attempted,
        points=points,
        offensive_rebounds=offensive_rebounds,
        rebounds=rebounds,
        assists=assists,
        steals=steals,
        blocks=blocks,
        turnovers=turnovers,
    )


def _game_results(count: int = 60) -> list[GameResult]:
    start = date(2024, 10, 1)
    games: list[GameResult] = []
    for index in range(count):
        home_team = 1 if index % 2 == 0 else 2
        away_team = 2 if home_team == 1 else 1
        home_score = 100 + (index % 17)
        away_score = 95 + ((index * 5) % 19)
        games.append(
            GameResult(
                game_id=f"G{index:04d}",
                game_date=start + timedelta(days=index),
                home_team_id=home_team,
                away_team_id=away_team,
                home_score=home_score,
                away_score=away_score,
            )
        )
    return games


def test_off_night_facts_count_unique_games_without_scoring_period_assumptions() -> None:
    entries = [
        _schedule_entry(1, 10, date(2026, 10, 20)),
        _schedule_entry(2, 10, date(2026, 10, 20)),
        _schedule_entry(3, 11, date(2026, 10, 21)),
        _schedule_entry(4, 12, date(2026, 10, 21)),
        _schedule_entry(5, 13, date(2026, 10, 21)),
    ]

    facts = build_off_night_facts(
        entries,
        config=ScheduleContextConfig(off_night_percentile=0.5),
    )

    assert [(fact.slate_date, fact.scheduled_game_count) for fact in facts] == [
        (date(2026, 10, 20), 1),
        (date(2026, 10, 21), 3),
    ]
    assert facts[0].is_off_night is True
    assert facts[1].is_off_night is False
    assert facts[0].input_snapshot["game_ids"] == [10]


def test_opponent_profile_keeps_ratio_makes_and_attempts_volume_weighted() -> None:
    games = _game_results(40)
    model = fit_blowout_model(
        games,
        training_cutoff=games[-1].game_date,
        source_version="source",
        window_games=5,
        minimum_history_games=2,
        requested_bins=3,
    )
    context_games: list[ContextGame] = []
    for index, game in enumerate(games):
        home = _team_stats(
            field_goals_made=40,
            field_goals_attempted=100,
        )
        away = _team_stats(
            field_goals_made=1 if index == 39 else 40,
            field_goals_attempted=1 if index == 39 else 100,
        )
        context_games.append(ContextGame(game, home, away))

    profile = build_opponent_profile(
        team_id=1,
        opponent_team_id=2,
        fixture_date=date(2025, 1, 1),
        context_games=context_games,
        score_games=games,
        blowout_model=model,
        config=ScheduleContextConfig(trailing_games=5, minimum_history_games=2),
    )

    ratios = profile.category_defence["ratios"]
    assert isinstance(ratios, dict)
    ratio = ratios["field_goals"]
    assert isinstance(ratio, dict)
    assert ratio["made"] == 161
    assert ratio["attempted"] == 401
    assert ratio["rate"] == pytest.approx(161 / 401)
    assert profile.pace_window_games == 5
    assert 0 <= profile.blowout_probability <= 1


def test_blowout_fit_is_time_ordered_and_reports_held_out_calibration() -> None:
    games = _game_results(100)
    cutoff = games[69].game_date
    model = fit_blowout_model(
        games,
        training_cutoff=cutoff,
        source_version="source-v1",
        window_games=10,
        minimum_history_games=3,
        requested_bins=4,
    )

    backtest = evaluate_blowout_model(
        model,
        games,
        held_out_start=games[70].game_date,
        held_out_end=games[-1].game_date,
    )

    assert backtest.training_cutoff < backtest.held_out_start
    assert backtest.held_out_examples == 30
    assert sum(row.count for row in backtest.calibration_bins) == 30
    assert 0 <= backtest.brier_score <= 1
    assert 0 <= backtest.expected_calibration_error <= 1


def test_future_result_cannot_change_an_earlier_blowout_model() -> None:
    games = _game_results(80)
    cutoff = games[59].game_date
    first = fit_blowout_model(
        games,
        training_cutoff=cutoff,
        source_version="same-source",
        window_games=10,
        minimum_history_games=3,
        requested_bins=4,
    )
    changed = [
        (
            GameResult(
                row.game_id,
                row.game_date,
                row.home_team_id,
                row.away_team_id,
                200,
                50,
            )
            if row.game_date > cutoff
            else row
        )
        for row in games
    ]
    second = fit_blowout_model(
        changed,
        training_cutoff=cutoff,
        source_version="same-source",
        window_games=10,
        minimum_history_games=3,
        requested_bins=4,
    )

    assert first == second


def test_future_trained_model_cannot_score_a_historical_fixture() -> None:
    games = _game_results(40)
    model = fit_blowout_model(
        games,
        training_cutoff=games[-1].game_date,
        source_version="source",
        window_games=5,
        minimum_history_games=2,
        requested_bins=3,
    )
    context_games = [ContextGame(game, _team_stats(), _team_stats()) for game in games]

    with pytest.raises(ValueError, match="training cutoff must precede"):
        build_opponent_profile(
            team_id=1,
            opponent_team_id=2,
            fixture_date=games[-2].game_date,
            context_games=context_games,
            score_games=games,
            blowout_model=model,
            config=ScheduleContextConfig(trailing_games=5, minimum_history_games=2),
        )


def _load_context_database(session: Any) -> tuple[list[GameResult], ScheduleContextConfig]:
    teams = [
        NbaTeam(nba_team_id=100 + index, abbreviation=f"T{index}", name=f"Team {index}")
        for index in range(1, 5)
    ]
    session.add_all(teams)
    session.flush()
    players = [
        Player(
            full_name=f"Player {team.id}",
            normalized_name=f"player{team.id}",
            current_team_id=team.id,
        )
        for team in teams
    ]
    session.add_all(players)
    session.flush()
    player_by_team = {player.current_team_id: player for player in players}

    results: list[GameResult] = []
    start = date(2025, 10, 1)
    pairings = ((teams[0], teams[1]), (teams[2], teams[3]))
    for day in range(30):
        for pair_index, (first, second) in enumerate(pairings):
            home, away = (first, second) if day % 2 == 0 else (second, first)
            game = NbaGame(
                season="2025-26",
                nba_game_id=f"H{day:02d}{pair_index}",
                game_date=start + timedelta(days=day),
                home_team_id=home.id,
                away_team_id=away.id,
                home_score=105 + (day % 13),
                away_score=94 + ((day * 3 + pair_index) % 17),
            )
            session.add(game)
            session.flush()
            for team in (home, away):
                session.add(
                    PlayerGameLog(
                        player_id=player_by_team[team.id].id,
                        game_id=game.id,
                        team_id=team.id,
                        field_goals_made=40,
                        field_goals_attempted=85,
                        three_pointers_made=12,
                        three_pointers_attempted=32,
                        free_throws_made=18,
                        free_throws_attempted=22,
                        points=110,
                        offensive_rebounds=10,
                        defensive_rebounds=34,
                        rebounds=44,
                        assists=25,
                        steals=7,
                        blocks=5,
                        turnovers=13,
                        personal_fouls=18,
                        plus_minus=0,
                    )
                )
            assert game.home_score is not None
            assert game.away_score is not None
            results.append(
                GameResult(
                    game_id=game.nba_game_id,
                    game_date=game.game_date,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    home_score=game.home_score,
                    away_score=game.away_score,
                )
            )

    fixture_date = date(2026, 10, 20)
    for pair_index, (home, away) in enumerate(pairings):
        game = NbaGame(
            season="2026-27",
            nba_game_id=f"F{pair_index}",
            game_date=fixture_date,
            home_team_id=home.id,
            away_team_id=away.id,
        )
        session.add(game)
        session.flush()
        session.add_all(
            [
                TeamScheduleEntry(
                    season="2026-27",
                    game_id=game.id,
                    team_id=home.id,
                    opponent_team_id=away.id,
                    game_date=fixture_date,
                    is_home=True,
                ),
                TeamScheduleEntry(
                    season="2026-27",
                    game_id=game.id,
                    team_id=away.id,
                    opponent_team_id=home.id,
                    game_date=fixture_date,
                    is_home=False,
                ),
            ]
        )
    session.flush()
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        version="schedule-v1",
        source="test",
        season="2026-27",
        refreshed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    return results, ScheduleContextConfig(trailing_games=10, minimum_history_games=3)


def _publish_test_claim(
    session: Any,
    games: list[GameResult],
    config: ScheduleContextConfig,
) -> tuple[Any, Any]:
    training_source_version = content_fingerprint(
        f"{game.game_id}:{game.game_date.isoformat()}:{game.home_team_id}:"
        f"{game.away_team_id}:{game.home_score}:{game.away_score}"
        for game in games
    )
    model = fit_blowout_model(
        games,
        training_cutoff=max(game.game_date for game in games),
        source_version=training_source_version,
        window_games=10,
        minimum_history_games=3,
        requested_bins=4,
    )
    claim = publish_schedule_context_cohorts(
        session,
        season="2026-27",
        blowout_model=model,
        config=config,
        refreshed_at=datetime(2026, 8, 18, 12, tzinfo=UTC),
    )
    return model, claim


def test_context_service_persists_explainable_versioned_outputs(session: Any) -> None:
    games, config = _load_context_database(session)
    model, claim = _publish_test_claim(session, games, config)

    counts = compute_schedule_context(
        session,
        season="2026-27",
        claim=claim,
        blowout_model=model,
        config=config,
    )

    assert counts.opponent_created == 4
    assert counts.slate_created == 1
    contexts = session.scalars(select(OpponentContext)).all()
    assert {row.source_version for row in contexts} == {claim.source_version}
    assert all(row.garbage_time_suppression is None for row in contexts)
    assert all(row.input_snapshot["features_as_of"] == "2026-10-20" for row in contexts)
    [slate] = session.scalars(select(OffNightSlate)).all()
    assert slate.streaming_window_score is None
    assert slate.source_version == claim.schedule_version


def test_context_service_rejects_a_superseded_schedule_cohort(session: Any) -> None:
    games, config = _load_context_database(session)
    model, claim = _publish_test_claim(session, games, config)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key="nba-schedule",
        version="schedule-v2",
        source="test",
        season="2026-27",
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    with pytest.raises(StaleContextCohortError, match="stale schedule"):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            blowout_model=model,
            config=config,
        )


def test_context_service_rejects_changed_source_and_retains_old_rows(session: Any) -> None:
    games, config = _load_context_database(session)
    model, claim = _publish_test_claim(session, games, config)
    compute_schedule_context(
        session,
        season="2026-27",
        claim=claim,
        blowout_model=model,
        config=config,
    )
    old_count = session.scalar(select(func.count(OpponentContext.id)))

    game = session.scalar(select(NbaGame).where(NbaGame.nba_game_id == "H000"))
    assert game is not None
    log = session.scalar(select(PlayerGameLog).where(PlayerGameLog.game_id == game.id))
    assert log is not None
    log.points = 111
    session.flush()

    with pytest.raises(StaleContextCohortError, match="observations changed"):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            blowout_model=model,
            config=config,
        )

    assert session.scalar(select(func.count(OpponentContext.id))) == old_count
    new_claim = publish_schedule_context_cohorts(
        session,
        season="2026-27",
        blowout_model=model,
        config=config,
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    assert new_claim.source_version != claim.source_version
    compute_schedule_context(
        session,
        season="2026-27",
        claim=new_claim,
        blowout_model=model,
        config=config,
    )
    assert session.scalar(select(func.count(OpponentContext.id))) == old_count + 4


def test_context_service_rejects_a_superseded_model_cohort(session: Any) -> None:
    games, config = _load_context_database(session)
    model, claim = _publish_test_claim(session, games, config)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key="schedule-context-blowout",
        version="replacement-model",
        source="test",
        season="2026-27",
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    with pytest.raises(StaleContextCohortError, match="stale model"):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            blowout_model=model,
            config=config,
        )
