from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from hoops_gm.db.lineage import record_refresh
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
from hoops_gm.db.models.identity import NbaTeam, Player
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.schedule_context import OffNightSlate, OpponentContext
from hoops_gm.db.models.stats import NbaGame, PlayerGameLog
from hoops_gm.schedule_context import (
    RELEASED_BLOWOUT_MODEL_VERSION,
    ContextGame,
    GameResult,
    IncompleteRecentContextError,
    InsufficientContextCoverageError,
    ScheduleContextConfig,
    StaleContextCohortError,
    TeamGameStats,
    UnreleasedBlowoutModelError,
    build_off_night_facts,
    build_opponent_profile,
    compute_schedule_context,
    context_source_version,
    evaluate_blowout_model,
    fit_blowout_model,
    load_blowout_release,
    publish_schedule_context_cohorts,
)
from hoops_gm.schedule_context.service import _sum_team_logs


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


def test_context_coverage_floor_is_fixed_and_versioned() -> None:
    default = ScheduleContextConfig()
    strict = ScheduleContextConfig(minimum_opponent_coverage=1.0)
    shorter_history = ScheduleContextConfig(trailing_games=14)

    assert default.minimum_opponent_coverage == 0.95
    assert default.opponent_derivation_version != strict.opponent_derivation_version
    assert default.opponent_derivation_version != shorter_history.opponent_derivation_version
    assert default.off_night_model_version != strict.off_night_model_version
    assert default.off_night_model_version != shorter_history.off_night_model_version
    assert default.opponent_derivation_version != default.off_night_model_version
    with pytest.raises(ValueError, match=r"must be in \[0.95, 1\]"):
        ScheduleContextConfig(minimum_opponent_coverage=0.94)


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
            full_name=f"Player {team.id}-{player_index}",
            normalized_name=f"player{team.id}-{player_index}",
            current_team_id=team.id,
        )
        for team in teams
        for player_index in range(5)
    ]
    session.add_all(players)
    session.flush()
    players_by_team = {
        team.id: [player for player in players if player.current_team_id == team.id]
        for team in teams
    }

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
                for player_index, player in enumerate(players_by_team[team.id]):
                    session.add(
                        PlayerGameLog(
                            player_id=player.id,
                            game_id=game.id,
                            team_id=team.id,
                            seconds_played=2_880,
                            field_goals_made=8,
                            field_goals_attempted=17,
                            three_pointers_made=2 + int(player_index < 2),
                            three_pointers_attempted=6,
                            free_throws_made=3 + int(player_index < 3),
                            free_throws_attempted=4 + int(player_index < 2),
                            points=22,
                            offensive_rebounds=2,
                            defensive_rebounds=7,
                            rebounds=9,
                            assists=5,
                            steals=1 + int(player_index < 2),
                            blocks=1,
                            turnovers=2 + int(player_index < 3),
                            personal_fouls=3 + int(player_index < 3),
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
    del games
    model = load_blowout_release().model
    claim = publish_schedule_context_cohorts(
        session,
        season="2026-27",
        config=config,
        refreshed_at=datetime(2026, 8, 18, 12, tzinfo=UTC),
    )
    return model, claim


def test_context_service_persists_explainable_versioned_outputs(session: Any) -> None:
    games, config = _load_context_database(session)
    _model, claim = _publish_test_claim(session, games, config)

    counts = compute_schedule_context(
        session,
        season="2026-27",
        claim=claim,
        config=config,
    )

    assert counts.opponent_created == 4
    assert counts.opponent_eligible == 4
    assert counts.opponent_coverage == 1.0
    assert counts.slate_created == 1
    contexts = session.scalars(select(OpponentContext)).all()
    assert {row.source_version for row in contexts} == {claim.source_version}
    assert {row.opponent_derivation_version for row in contexts} == {
        claim.opponent_derivation_version
    }
    assert {row.blowout_model_version for row in contexts} == {claim.blowout_model_version}
    assert all(row.garbage_time_suppression is None for row in contexts)
    assert all(row.input_snapshot["features_as_of"] == "2026-10-20" for row in contexts)
    assert all(
        row.input_snapshot["opponent_context_coverage"]["coverage_ratio"] == 1.0 for row in contexts
    )
    assert all(
        row.input_snapshot["opponent_context_coverage"]["observation_completeness"]
        == {
            "rule": "last_n_scored_regular_season_team_games_complete_v1",
            "audited_team_fixture_histories": 4,
            "scored_team_game_observations": 40,
            "complete_team_game_observations": 40,
            "incomplete_team_game_observations": 0,
            "maximum_days_since_latest_scored_game": 355,
            "maximum_days_since_latest_complete_game": 355,
        }
        for row in contexts
    )
    assert all(
        row.input_snapshot["observation_completeness"]["team"]["incomplete_game_ids"] == []
        for row in contexts
    )
    [slate] = session.scalars(select(OffNightSlate)).all()
    assert slate.streaming_window_score is None
    assert slate.source_version == claim.source_version
    assert slate.input_snapshot["opponent_context_coverage"]["eligible_fixture_rows"] == 4


def test_context_service_rejects_a_superseded_schedule_cohort(session: Any) -> None:
    games, config = _load_context_database(session)
    _model, claim = _publish_test_claim(session, games, config)
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
            config=config,
        )


def test_context_service_rejects_changed_source_and_retains_old_rows(session: Any) -> None:
    games, config = _load_context_database(session)
    _model, claim = _publish_test_claim(session, games, config)
    compute_schedule_context(
        session,
        season="2026-27",
        claim=claim,
        config=config,
        computed_at=datetime(2026, 8, 18, 13, tzinfo=UTC),
    )
    old_count = session.scalar(select(func.count(OpponentContext.id)))
    [old_slate] = session.scalars(select(OffNightSlate)).all()
    old_slate_id = old_slate.id

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
            config=config,
        )

    assert session.scalar(select(func.count(OpponentContext.id))) == old_count
    assert session.scalar(select(func.count(OffNightSlate.id))) == 1
    new_claim = publish_schedule_context_cohorts(
        session,
        season="2026-27",
        config=config,
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    assert new_claim.source_version != claim.source_version
    counts = compute_schedule_context(
        session,
        season="2026-27",
        claim=new_claim,
        config=config,
        computed_at=datetime(2026, 8, 19, 13, tzinfo=UTC),
    )
    assert session.scalar(select(func.count(OpponentContext.id))) == old_count + 4
    assert counts.slate_created == 1
    slates = session.scalars(select(OffNightSlate).order_by(OffNightSlate.computed_at)).all()
    assert len(slates) == 2
    assert next(slate.id for slate in slates) == old_slate_id
    assert {slate.slate_date for slate in slates} == {date(2026, 10, 20)}
    assert {slate.schedule_version for slate in slates} == {claim.schedule_version}
    assert {slate.model_version for slate in slates} == {claim.off_night_model_version}
    assert {slate.source_version for slate in slates} == {
        claim.source_version,
        new_claim.source_version,
    }
    assert [
        slate.input_snapshot["opponent_context_coverage"]["coverage_ratio"] for slate in slates
    ] == [1.0, 1.0]


def test_context_service_rejects_a_superseded_model_cohort(session: Any) -> None:
    games, config = _load_context_database(session)
    _model, claim = _publish_test_claim(session, games, config)
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
            config=config,
        )


def test_context_service_rejects_a_superseded_opponent_derivation_cohort(session: Any) -> None:
    games, config = _load_context_database(session)
    _model, claim = _publish_test_claim(session, games, config)
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.MODEL,
        artifact_key="schedule-context-opponent-derivation",
        version="replacement-derivation",
        source="test",
        season="2026-27",
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )

    with pytest.raises(
        StaleContextCohortError,
        match="stale model:schedule-context-opponent-derivation",
    ):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            config=config,
        )


def test_opponent_derivation_config_versions_retain_both_context_cohorts(session: Any) -> None:
    games, config_10 = _load_context_database(session)
    history = session.execute(
        select(PlayerGameLog, NbaGame)
        .join(NbaGame, NbaGame.id == PlayerGameLog.game_id)
        .where(NbaGame.nba_game_id.like("H%"))
    ).all()
    for log, game in history:
        if int(game.nba_game_id[1:3]) >= 25:
            log.field_goals_attempted += 10
    session.flush()

    _model, claim_10 = _publish_test_claim(session, games, config_10)
    first = compute_schedule_context(
        session,
        season="2026-27",
        claim=claim_10,
        config=config_10,
        computed_at=datetime(2026, 8, 18, 13, tzinfo=UTC),
    )

    config_5 = ScheduleContextConfig(trailing_games=5, minimum_history_games=3)
    claim_5 = publish_schedule_context_cohorts(
        session,
        season="2026-27",
        config=config_5,
        refreshed_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    second = compute_schedule_context(
        session,
        season="2026-27",
        claim=claim_5,
        config=config_5,
        computed_at=datetime(2026, 8, 19, 13, tzinfo=UTC),
    )
    with pytest.raises(
        StaleContextCohortError,
        match="stale model:schedule-context-opponent-derivation cohort",
    ):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim_10,
            config=config_10,
        )
    with pytest.raises(StaleContextCohortError, match="opponent derivation does not match"):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim_5,
            config=config_10,
        )

    assert first.opponent_created == second.opponent_created == 4
    assert claim_10.opponent_derivation_version == config_10.opponent_derivation_version
    assert claim_5.opponent_derivation_version == config_5.opponent_derivation_version
    assert claim_10.opponent_derivation_version != claim_5.opponent_derivation_version
    assert claim_10.blowout_model_version == claim_5.blowout_model_version

    contexts = session.scalars(
        select(OpponentContext).order_by(
            OpponentContext.opponent_derivation_version,
            OpponentContext.team_schedule_id,
        )
    ).all()
    assert len(contexts) == 8
    by_derivation = {
        version: [row for row in contexts if row.opponent_derivation_version == version]
        for version in {
            claim_10.opponent_derivation_version,
            claim_5.opponent_derivation_version,
        }
    }
    rows_10 = by_derivation[claim_10.opponent_derivation_version]
    rows_5 = by_derivation[claim_5.opponent_derivation_version]
    assert len(rows_10) == len(rows_5) == 4
    assert {row.pace_window_games for row in rows_10} == {10}
    assert {row.defence_window_games for row in rows_10} == {10}
    assert {row.pace_window_games for row in rows_5} == {5}
    assert {row.defence_window_games for row in rows_5} == {5}
    assert {row.pace_possessions for row in rows_10} != {row.pace_possessions for row in rows_5}
    assert {row.category_defence["normalization_possessions"] for row in rows_10} != {
        row.category_defence["normalization_possessions"] for row in rows_5
    }
    assert {row.blowout_model_version for row in contexts} == {RELEASED_BLOWOUT_MODEL_VERSION}

    slates = session.scalars(select(OffNightSlate)).all()
    assert len(slates) == 2
    assert {slate.model_version for slate in slates} == {
        claim_10.off_night_model_version,
        claim_5.off_night_model_version,
    }


def test_only_the_gate_passed_blowout_release_can_be_published(session: Any) -> None:
    _games, config = _load_context_database(session)

    with pytest.raises(UnreleasedBlowoutModelError, match="not in the production release registry"):
        publish_schedule_context_cohorts(
            session,
            season="2026-27",
            config=config,
            blowout_model_version="locally-fitted-variant",
        )

    release = load_blowout_release(RELEASED_BLOWOUT_MODEL_VERSION)
    assert release.model.version == RELEASED_BLOWOUT_MODEL_VERSION
    assert release.model.source_version == release.training_source_fingerprint
    assert release.holdout_source_fingerprint == "e992a314295c442a"


def test_three_player_subset_is_not_a_complete_team_box_score() -> None:
    logs = [
        PlayerGameLog(
            player_id=index,
            game_id=1,
            team_id=1,
            seconds_played=4_800,
            field_goals_made=8,
            field_goals_attempted=17,
            three_pointers_made=2,
            free_throws_made=3,
            free_throws_attempted=4,
            points=22,
            offensive_rebounds=2,
            rebounds=9,
            assists=5,
            steals=1,
            blocks=1,
            turnovers=2,
        )
        for index in range(1, 4)
    ]

    with pytest.raises(ValueError, match="at least five plausible player-minute rows"):
        _sum_team_logs(logs)


def test_regular_season_source_fingerprint_excludes_playoff_rows(session: Any) -> None:
    _games, _config = _load_context_database(session)
    regular_version = context_source_version(session)
    teams = session.scalars(select(NbaTeam).order_by(NbaTeam.id)).all()
    session.add(
        NbaGame(
            season="2025-26",
            season_type=SeasonType.PLAYOFFS,
            nba_game_id="PLAYOFF-1",
            game_date=date(2026, 4, 20),
            home_team_id=teams[0].id,
            away_team_id=teams[1].id,
            home_score=120,
            away_score=110,
        )
    )
    session.flush()

    assert context_source_version(session) == regular_version


def test_context_run_fails_before_writes_when_recent_half_of_box_scores_is_incomplete(
    session: Any,
) -> None:
    games, _config = _load_context_database(session)
    config = ScheduleContextConfig(trailing_games=15, minimum_history_games=3)
    history_start = date(2026, 9, 19)
    scored_games = session.scalars(select(NbaGame).where(NbaGame.home_score.is_not(None))).all()
    for game in scored_games:
        day = int(game.nba_game_id[1:3])
        game.game_date = history_start + timedelta(days=day)
        game.season = "2026-27"
    session.flush()
    recent_half_start = date(2026, 10, 4)
    latest_complete_date = recent_half_start - timedelta(days=1)
    assert (date(2026, 10, 20) - latest_complete_date).days == 17
    recent_game_ids = session.scalars(
        select(NbaGame.id).where(
            NbaGame.game_date >= recent_half_start,
            NbaGame.home_score.is_not(None),
        )
    ).all()
    assert len(recent_game_ids) == 30
    recent_logs = session.scalars(
        select(PlayerGameLog).where(PlayerGameLog.game_id.in_(recent_game_ids))
    ).all()
    assert len(recent_logs) == 300
    for log in recent_logs:
        log.seconds_played = 1
    session.flush()
    model, claim = _publish_test_claim(session, games, config)

    with pytest.raises(
        IncompleteRecentContextError,
        match=r"15/15 incomplete box scores in its last 15 scored games",
    ):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            config=config,
        )

    assert model.version == RELEASED_BLOWOUT_MODEL_VERSION
    assert session.scalar(select(func.count(OpponentContext.id))) == 0
    assert session.scalar(select(func.count(OffNightSlate.id))) == 0


def test_context_run_fails_before_writes_when_fixture_coverage_is_below_floor(
    session: Any,
) -> None:
    games, config = _load_context_database(session)
    new_team = NbaTeam(nba_team_id=999, abbreviation="NEW", name="New Team")
    session.add(new_team)
    session.flush()
    first_entry = session.scalar(select(TeamScheduleEntry).order_by(TeamScheduleEntry.id))
    assert first_entry is not None
    first_entry.team_id = new_team.id
    session.flush()
    _model, claim = _publish_test_claim(session, games, config)

    with pytest.raises(InsufficientContextCoverageError, match="3/4"):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            config=config,
        )

    assert session.scalar(select(func.count(OpponentContext.id))) == 0
    assert session.scalar(select(func.count(OffNightSlate.id))) == 0


def test_context_service_rejects_naive_computed_at(session: Any) -> None:
    games, config = _load_context_database(session)
    _model, claim = _publish_test_claim(session, games, config)

    with pytest.raises(ValueError, match="computed_at must be timezone-aware"):
        compute_schedule_context(
            session,
            season="2026-27",
            claim=claim,
            config=config,
            computed_at=datetime(2026, 8, 18, 12),
        )
