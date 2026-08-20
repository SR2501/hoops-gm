"""Direct-evidence teammate splits and their fail-closed R35 boundary."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.availability import (
    AbsenceSplitInputError,
    compute_absence_splits,
    latest_absence_splits,
)
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    record_refresh,
    schedule_content_version,
)
from hoops_gm.db.models import (
    AbsenceSplit,
    AbsenceSplitComputationRun,
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
    team = NbaTeam(nba_team_id=1, abbreviation="AAA", name="Alpha")
    opponent = NbaTeam(nba_team_id=2, abbreviation="OPP", name="Opponent")
    session.add_all([team, opponent])
    session.flush()
    return team, opponent


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
    team: NbaTeam,
    opponent: NbaTeam,
) -> NbaGame:
    game = NbaGame(
        season=SEASON,
        season_type=SeasonType.REGULAR,
        nba_game_id=f"00225{number:05d}",
        game_date=game_date,
        status=GameStatus.FINAL,
        home_team_id=team.id,
        away_team_id=opponent.id,
    )
    session.add(game)
    session.flush()
    session.add_all(
        [
            TeamScheduleEntry(
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=team.id,
                opponent_team_id=opponent.id,
                game_date=game_date,
                is_home=True,
            ),
            TeamScheduleEntry(
                season=SEASON,
                season_type=SeasonType.REGULAR,
                game_id=game.id,
                team_id=opponent.id,
                opponent_team_id=team.id,
                game_date=game_date,
                is_home=False,
            ),
        ]
    )
    session.flush()
    return game


def _games(
    session: Session,
    team: NbaTeam,
    opponent: NbaTeam,
    count: int,
    *,
    start: date = date(2025, 10, 20),
) -> list[NbaGame]:
    return [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team,
            opponent=opponent,
        )
        for index in range(1, count + 1)
    ]


def _register_schedule(session: Session, version: str = "schedule-test-v1") -> None:
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=version,
        season=SEASON,
        source="test",
        refreshed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )


def _register_verified_schedule(session: Session) -> None:
    game_count = len(
        session.scalars(
            select(NbaGame).where(
                NbaGame.season == SEASON,
                NbaGame.season_type == SeasonType.REGULAR,
            )
        ).all()
    )
    team_row_count = len(
        session.scalars(
            select(TeamScheduleEntry).where(
                TeamScheduleEntry.season == SEASON,
                TeamScheduleEntry.season_type == SeasonType.REGULAR,
            )
        ).all()
    )
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=schedule_content_version(session, season=SEASON),
        season=SEASON,
        source="test",
        summary={
            SCHEDULE_COMPLETENESS_SUMMARY_KEY: {
                "season": SEASON,
                "season_type": SeasonType.REGULAR.value,
                "source_game_count": game_count,
                "resolved_game_count": game_count,
                "unresolved_game_ids": [],
                "persisted_team_row_count": team_row_count,
            }
        },
        refreshed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )


def _mutate_schedule_date_without_changing_row_count(
    session: Session,
    game: NbaGame,
) -> None:
    game.game_date += timedelta(days=1)
    for entry in session.scalars(
        select(TeamScheduleEntry).where(TeamScheduleEntry.game_id == game.id)
    ):
        entry.game_date = game.game_date
    session.flush()


def _log(
    session: Session,
    *,
    player: Player,
    game: NbaGame,
    team: NbaTeam,
    points: int,
    free_throws_made: int = 0,
    free_throws_attempted: int = 0,
) -> PlayerGameLog:
    row = PlayerGameLog(
        player_id=player.id,
        game_id=game.id,
        team_id=team.id,
        seconds_played=1800,
        points=points,
        rebounds=5,
        assists=4,
        steals=1,
        blocks=0,
        turnovers=2,
        three_pointers_made=2,
        field_goals_made=5,
        field_goals_attempted=10,
        free_throws_made=free_throws_made,
        free_throws_attempted=free_throws_attempted,
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


def _dict(value: object) -> dict[str, object]:
    return cast(dict[str, object], value)


def _pair(
    result_rows: tuple[AbsenceSplit, ...], beneficiary: Player, absent: Player
) -> AbsenceSplit:
    return next(
        split
        for split in result_rows
        if split.beneficiary_player_id == beneficiary.id and split.absent_player_id == absent.id
    )


def test_computes_only_directly_observed_non_play_evidence(session: Session) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Absent teammate")
    games = _games(session, team, opponent, 4)
    _register_schedule(session)

    _log(session, player=absent, game=games[0], team=team, points=20)
    _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
    )
    _participation(
        session,
        player=absent,
        game=games[2],
        team=team,
        outcome=ParticipationOutcome.INACTIVE,
    )
    _log(session, player=absent, game=games[3], team=team, points=22)
    for game, points, made, attempted in zip(
        games,
        (10, 30, 40, 20),
        (1, 1, 0, 9),
        (1, 10, 0, 10),
        strict=True,
    ):
        _log(
            session,
            player=beneficiary,
            game=game,
            team=team,
            points=points,
            free_throws_made=made,
            free_throws_attempted=attempted,
        )

    result = compute_absence_splits(session, season=SEASON)
    row = _pair(result.rows, beneficiary, absent)

    assert result.computation_run.result_count == 1
    assert row.games_with == 2
    assert row.games_without == 2
    assert row.observed_absence_games == 2
    assert row.data_layer == "observations"
    assert row.claim_type == "descriptive"
    assert row.provenance["missing_rows_classified"] == 0

    with_counting = _dict(_dict(row.production_with)["counting"])
    without_counting = _dict(_dict(row.production_without)["counting"])
    assert _dict(with_counting["points"])["per_game"] == 15.0
    assert _dict(without_counting["points"])["per_game"] == 35.0
    point_delta = _dict(_dict(_dict(row.descriptive_deltas)["counting"])["points"])
    assert point_delta["without_minus_with_per_game"] == 20.0
    assert point_delta["delta_standard_error"] == pytest.approx(50**0.5)

    with_shooting = _dict(_dict(row.production_with)["shooting"])
    free_throws = _dict(with_shooting["free_throws"])
    assert free_throws["made"] == 10
    assert free_throws["attempted"] == 11
    assert free_throws["aggregate_rate"] == pytest.approx(10 / 11)

    without_samples = cast(list[dict[str, object]], row.provenance["without_samples"])
    assert {sample["condition"] for sample in without_samples} == {"without_observed"}
    assert {_dict(sample["target_evidence"])["kind"] for sample in without_samples} == {
        "participation"
    }


def test_long_missing_window_between_same_team_observations_is_never_absence(
    session: Session,
) -> None:
    """Bracketing Team A rows do not prove continuous roster membership or feed completeness."""

    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    teammate = _player(session, "Left and later returned")
    games = _games(session, team, opponent, 10)
    _register_schedule(session)

    _log(session, player=teammate, game=games[0], team=team, points=10)
    _log(session, player=teammate, game=games[-1], team=team, points=10)
    for game in games:
        _log(session, player=beneficiary, game=game, team=team, points=20)

    result = compute_absence_splits(session, season=SEASON)

    assert not any(
        row.beneficiary_player_id == beneficiary.id and row.absent_player_id == teammate.id
        for row in result.rows
    )
    assert result.computation_run.result_count == 0
    assert latest_absence_splits(session, season=SEASON) == ()


def test_explicit_unknown_is_provenance_not_a_schedule_coverage_claim(session: Session) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Unknown teammate")
    games = _games(session, team, opponent, 4, start=date(2026, 1, 1))
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.UNKNOWN,
    )
    _participation(
        session,
        player=absent,
        game=games[2],
        team=team,
        outcome=ParticipationOutcome.INACTIVE,
    )
    _log(session, player=absent, game=games[3], team=team, points=10)
    for game in games:
        _log(session, player=beneficiary, game=game, team=team, points=20)

    row = _pair(
        compute_absence_splits(session, season=SEASON).rows,
        beneficiary,
        absent,
    )

    assert row.games_without == 1
    assert row.observed_absence_games == 1
    assert row.provenance["explicit_unknown_game_ids"] == [games[1].id]
    assert not hasattr(row, "excluded_unknown_games")
    assert row.uncertainty["sample_sizes"] == {"with": 2, "without": 1}
    assert row.uncertainty["variance_estimable"] == {"with": True, "without": False}


def test_unknown_participation_does_not_override_a_game_log_that_proves_play(
    session: Session,
) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    teammate = _player(session, "Observed teammate")
    games = _games(session, team, opponent, 3, start=date(2026, 1, 10))
    _register_schedule(session)
    _log(session, player=teammate, game=games[0], team=team, points=10)
    _participation(
        session,
        player=teammate,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.INACTIVE,
    )
    _log(session, player=teammate, game=games[2], team=team, points=10)
    _participation(
        session,
        player=teammate,
        game=games[2],
        team=team,
        outcome=ParticipationOutcome.UNKNOWN,
    )
    for game in games:
        _log(session, player=beneficiary, game=game, team=team, points=20)

    row = _pair(
        compute_absence_splits(session, season=SEASON).rows,
        beneficiary,
        teammate,
    )

    with_samples = cast(list[dict[str, object]], row.provenance["with_samples"])
    last_target = _dict(with_samples[-1]["target_evidence"])
    assert last_target["kind"] == "player_game_log"
    assert last_target["participation_outcome"] == ParticipationOutcome.UNKNOWN.value


def test_shooting_uncertainty_does_not_treat_clustered_attempts_as_independent(
    session: Session,
) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Clustered shooter")
    absent = _player(session, "Absent teammate")
    games = _games(session, team, opponent, 4, start=date(2026, 2, 1))
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    _log(session, player=absent, game=games[1], team=team, points=10)
    for game in games[2:]:
        _participation(
            session,
            player=absent,
            game=game,
            team=team,
            outcome=ParticipationOutcome.INACTIVE,
        )
    for game, made in zip(games, (10, 0, 5, 5), strict=True):
        _log(
            session,
            player=beneficiary,
            game=game,
            team=team,
            points=20,
            free_throws_made=made,
            free_throws_attempted=10,
        )

    row = _pair(
        compute_absence_splits(session, season=SEASON).rows,
        beneficiary,
        absent,
    )
    with_ft = _dict(_dict(_dict(row.production_with)["shooting"])["free_throws"])

    assert with_ft["aggregate_rate"] == 0.5
    assert with_ft["observed_games"] == 2
    assert with_ft["interval"] is None
    assert "wilson_95_interval" not in with_ft
    assert "shot_level_standard_error" not in with_ft
    assert "cluster within games" in cast(str, with_ft["interval_reason"])


def test_conflicting_play_and_non_play_evidence_fails_loudly(session: Session) -> None:
    team, opponent = _teams(session)
    player = _player(session, "Contradiction")
    game = _games(session, team, opponent, 1, start=date(2026, 3, 1))[0]
    _register_schedule(session)
    _log(session, player=player, game=game, team=team, points=10)
    _participation(
        session,
        player=player,
        game=game,
        team=team,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
    )

    with pytest.raises(AbsenceSplitInputError, match="game log"):
        compute_absence_splits(session, season=SEASON)


def test_schedule_lineage_is_required_before_computation(session: Session) -> None:
    team, opponent = _teams(session)
    _games(session, team, opponent, 1, start=date(2026, 3, 10))

    with pytest.raises(AbsenceSplitInputError, match="schedule refresh"):
        compute_absence_splits(session, season=SEASON)


def test_same_row_count_schedule_mutation_blocks_computation_publication(
    session: Session,
) -> None:
    team, opponent = _teams(session)
    games = _games(session, team, opponent, 3, start=date(2026, 3, 20))
    _register_verified_schedule(session)
    original_row_count = len(session.scalars(select(TeamScheduleEntry)).all())

    _mutate_schedule_date_without_changing_row_count(session, games[0])

    assert len(session.scalars(select(TeamScheduleEntry)).all()) == original_row_count
    with pytest.raises(AbsenceSplitInputError, match=r"schedule evidence.*stale"):
        compute_absence_splits(session, season=SEASON)
    assert session.scalars(select(AbsenceSplitComputationRun)).all() == []


def test_same_row_count_schedule_mutation_blocks_current_retrieval(session: Session) -> None:
    team, opponent = _teams(session)
    games = _games(session, team, opponent, 1, start=date(2026, 3, 25))
    _register_verified_schedule(session)
    published = compute_absence_splits(session, season=SEASON)
    original_row_count = len(session.scalars(select(TeamScheduleEntry)).all())

    _mutate_schedule_date_without_changing_row_count(session, games[0])

    assert len(session.scalars(select(TeamScheduleEntry)).all()) == original_row_count
    with pytest.raises(AbsenceSplitInputError, match=r"schedule evidence.*stale"):
        latest_absence_splits(session, season=SEASON)
    assert session.get(AbsenceSplitComputationRun, published.computation_run.id) is not None


def test_malformed_schedule_verification_uses_absence_split_domain_error(
    session: Session,
) -> None:
    team, opponent = _teams(session)
    _games(session, team, opponent, 1, start=date(2026, 3, 30))
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        version=schedule_content_version(session, season=SEASON),
        season=SEASON,
        source="test",
        summary={SCHEDULE_COMPLETENESS_SUMMARY_KEY: {"season": SEASON}},
    )

    for operation in (
        lambda: compute_absence_splits(session, season=SEASON),
        lambda: latest_absence_splits(session, season=SEASON),
    ):
        with pytest.raises(
            AbsenceSplitInputError, match=r"schedule evidence.*malformed"
        ) as exc_info:
            operation()
        assert isinstance(exc_info.value.__cause__, ValueError)


def test_a_b_a_recomputation_reactivates_the_final_a_cohort(session: Session) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Absent teammate")
    games = _games(session, team, opponent, 3, start=date(2026, 4, 1))
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.INACTIVE,
    )
    _log(session, player=absent, game=games[2], team=team, points=10)
    beneficiary_logs = [
        _log(session, player=beneficiary, game=game, team=team, points=points)
        for game, points in zip(games, (10, 20, 30), strict=True)
    ]

    first_a = compute_absence_splits(session, season=SEASON)
    beneficiary_logs[1].points = 25
    session.flush()
    middle_b = compute_absence_splits(session, season=SEASON)
    beneficiary_logs[1].points = 20
    session.flush()
    final_a = compute_absence_splits(session, season=SEASON)

    assert first_a.computation_run.input_fingerprint == final_a.computation_run.input_fingerprint
    assert first_a.computation_run.id < middle_b.computation_run.id < final_a.computation_run.id
    assert len(session.scalars(select(AbsenceSplitComputationRun)).all()) == 3
    pair_rows = session.scalars(
        select(AbsenceSplit).where(
            AbsenceSplit.beneficiary_player_id == beneficiary.id,
            AbsenceSplit.absent_player_id == absent.id,
        )
    ).all()
    assert len(pair_rows) == 3
    latest = _pair(latest_absence_splits(session, season=SEASON), beneficiary, absent)
    latest_without = _dict(_dict(latest.production_without)["counting"])
    assert _dict(latest_without["points"])["per_game"] == 20.0


def test_empty_recomputation_supersedes_obsolete_pair_rows(session: Session) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Corrected teammate")
    games = _games(session, team, opponent, 3, start=date(2026, 5, 1))
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    corrected = _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.INACTIVE,
    )
    _log(session, player=absent, game=games[2], team=team, points=10)
    for game in games:
        _log(session, player=beneficiary, game=game, team=team, points=20)

    first = compute_absence_splits(session, season=SEASON)
    assert _pair(first.rows, beneficiary, absent).games_without == 1

    corrected.outcome = ParticipationOutcome.PLAYED
    _log(session, player=absent, game=games[1], team=team, points=10)
    session.flush()
    second = compute_absence_splits(session, season=SEASON)

    assert second.computation_run.id != first.computation_run.id
    assert second.computation_run.result_count == 0
    assert second.rows == ()
    assert latest_absence_splits(session, season=SEASON) == ()
    assert (
        session.scalar(select(AbsenceSplit).where(AbsenceSplit.run_id == first.computation_run.id))
        is not None
    )


def test_empty_nonempty_empty_reactivates_the_final_empty_cohort(session: Session) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Cohort teammate")
    games = _games(session, team, opponent, 3, start=date(2026, 6, 1))
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    middle = _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.UNKNOWN,
    )
    _log(session, player=absent, game=games[2], team=team, points=10)
    for game in games:
        _log(session, player=beneficiary, game=game, team=team, points=20)

    first_empty = compute_absence_splits(session, season=SEASON)
    assert first_empty.rows == ()

    middle.outcome = ParticipationOutcome.INACTIVE
    session.flush()
    nonempty = compute_absence_splits(session, season=SEASON)
    assert _pair(nonempty.rows, beneficiary, absent).games_without == 1

    middle.outcome = ParticipationOutcome.UNKNOWN
    session.flush()
    final_empty = compute_absence_splits(session, season=SEASON)

    assert (
        first_empty.computation_run.input_fingerprint
        == final_empty.computation_run.input_fingerprint
    )
    assert (
        first_empty.computation_run.id
        < nonempty.computation_run.id
        < final_empty.computation_run.id
    )
    assert final_empty.rows == ()
    assert latest_absence_splits(session, season=SEASON) == ()


def test_caught_invalid_computation_does_not_persist_an_activation(session: Session) -> None:
    team, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Invalid-input teammate")
    games = _games(session, team, opponent, 3, start=date(2026, 7, 1))
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.INACTIVE,
    )
    _log(session, player=absent, game=games[2], team=team, points=10)
    beneficiary_logs = [
        _log(
            session,
            player=beneficiary,
            game=game,
            team=team,
            points=20,
            free_throws_made=1,
            free_throws_attempted=2,
        )
        for game in games
    ]

    valid = compute_absence_splits(session, season=SEASON)
    beneficiary_logs[1].free_throws_made = 3
    beneficiary_logs[1].free_throws_attempted = 2
    session.flush()

    with pytest.raises(AbsenceSplitInputError, match="invalid shooting components"):
        compute_absence_splits(session, season=SEASON)
    session.commit()

    runs = session.scalars(select(AbsenceSplitComputationRun)).all()
    assert [run.id for run in runs] == [valid.computation_run.id]
    latest = _pair(latest_absence_splits(session, season=SEASON), beneficiary, absent)
    latest_without = _dict(_dict(latest.production_without)["shooting"])
    assert _dict(latest_without["free_throws"])["made"] == 1
