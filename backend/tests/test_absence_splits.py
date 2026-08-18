"""Descriptive teammate absence evidence and its R35 fail-closed boundary."""

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
from hoops_gm.db.lineage import record_refresh
from hoops_gm.db.models import (
    AbsenceSplit,
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


def _teams(session: Session) -> tuple[NbaTeam, NbaTeam, NbaTeam]:
    teams = (
        NbaTeam(nba_team_id=1, abbreviation="AAA", name="Alpha"),
        NbaTeam(nba_team_id=2, abbreviation="BBB", name="Beta"),
        NbaTeam(nba_team_id=3, abbreviation="OPP", name="Opponent"),
    )
    session.add_all(teams)
    session.flush()
    return teams


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
    session.add(
        TeamScheduleEntry(
            season=SEASON,
            season_type=SeasonType.REGULAR,
            game_id=game.id,
            team_id=team.id,
            opponent_team_id=opponent.id,
            game_date=game_date,
            is_home=True,
        )
    )
    session.flush()
    return game


def _register_schedule(session: Session, version: str = "schedule-test-v1") -> None:
    record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        version=version,
        season=SEASON,
        source="test",
        refreshed_at=datetime(2026, 8, 18, tzinfo=UTC),
    )


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


def test_computes_explicit_and_bounded_inferred_absence_evidence(session: Session) -> None:
    team, _, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Absent teammate")
    start = date(2025, 10, 20)
    games = [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team,
            opponent=opponent,
        )
        for index in range(1, 5)
    ]
    _register_schedule(session)

    _log(session, player=absent, game=games[0], team=team, points=20)
    _participation(
        session,
        player=absent,
        game=games[1],
        team=team,
        outcome=ParticipationOutcome.DID_NOT_PLAY,
    )
    # games[2] has no row for the absent player. It is inferable only because
    # games[0]/games[3] bound a same-team observed membership segment.
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
    row = next(
        split
        for split in result.rows
        if split.beneficiary_player_id == beneficiary.id and split.absent_player_id == absent.id
    )

    assert row.games_with == 2
    assert row.games_without == 2
    assert row.explicit_absence_games == 1
    assert row.inferred_absence_games == 1
    assert row.data_layer == "observations"
    assert row.claim_type == "descriptive"

    with_counting = _dict(_dict(row.production_with)["counting"])
    without_counting = _dict(_dict(row.production_without)["counting"])
    assert _dict(with_counting["points"])["per_game"] == 15.0
    assert _dict(without_counting["points"])["per_game"] == 35.0
    point_delta = _dict(_dict(_dict(row.descriptive_deltas)["counting"])["points"])
    assert point_delta["without_minus_with_per_game"] == 20.0
    assert point_delta["delta_standard_error"] == pytest.approx(50**0.5)

    # 1/1 and 9/10 aggregate to 10/11. Averaging the two game percentages
    # would produce .95 and discard the attempt volume.
    with_shooting = _dict(_dict(row.production_with)["shooting"])
    free_throws = _dict(with_shooting["free_throws"])
    assert free_throws["made"] == 10
    assert free_throws["attempted"] == 11
    assert free_throws["aggregate_rate"] == pytest.approx(10 / 11)

    provenance = _dict(row.provenance)
    without_samples = cast(list[dict[str, object]], provenance["without_samples"])
    assert {sample["condition"] for sample in without_samples} == {
        "without_explicit",
        "without_inferred",
    }
    inferred = next(
        sample for sample in without_samples if sample["condition"] == "without_inferred"
    )
    assert _dict(inferred["target_evidence"])["kind"] == "missing_within_bounded_membership"
    assert row.uncertainty["causal_effect"] is False
    assert row.uncertainty["recommendation"] is False


def test_missing_rows_outside_observed_membership_bounds_are_not_absences(
    session: Session,
) -> None:
    team, _, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Bounded teammate")
    start = date(2025, 11, 1)
    games = [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team,
            opponent=opponent,
        )
        for index in range(1, 7)
    ]
    _register_schedule(session)

    _log(session, player=absent, game=games[1], team=team, points=10)
    _log(session, player=absent, game=games[4], team=team, points=11)
    for index, game in enumerate(games):
        _log(session, player=beneficiary, game=game, team=team, points=20 + index)

    row = next(
        split
        for split in compute_absence_splits(session, season=SEASON).rows
        if split.beneficiary_player_id == beneficiary.id and split.absent_player_id == absent.id
    )

    assert row.games_with == 2
    assert row.games_without == 2
    provenance = _dict(row.provenance)
    all_samples = cast(list[dict[str, object]], provenance["with_samples"]) + cast(
        list[dict[str, object]], provenance["without_samples"]
    )
    sampled_game_ids = {sample["game_id"] for sample in all_samples}
    assert games[0].id not in sampled_game_ids
    assert games[5].id not in sampled_game_ids


def test_team_changes_break_membership_segments_instead_of_inventing_absences(
    session: Session,
) -> None:
    team_a, team_b, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    traded = _player(session, "Traded teammate")
    start = date(2025, 12, 1)
    games_a = [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team_a,
            opponent=opponent,
        )
        for index in (1, 2, 4, 5)
    ]
    game_b = _game(
        session,
        number=3,
        game_date=start + timedelta(days=3),
        team=team_b,
        opponent=opponent,
    )
    _register_schedule(session)

    _log(session, player=traded, game=games_a[0], team=team_a, points=10)
    _log(session, player=traded, game=game_b, team=team_b, points=10)
    _log(session, player=traded, game=games_a[-1], team=team_a, points=10)
    for game in games_a:
        _log(session, player=beneficiary, game=game, team=team_a, points=20)

    result = compute_absence_splits(session, season=SEASON)

    assert not any(
        row.beneficiary_player_id == beneficiary.id and row.absent_player_id == traded.id
        for row in result.rows
    )


def test_unknown_participation_is_excluded_not_coerced_to_absence(session: Session) -> None:
    team, _, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Unknown teammate")
    start = date(2026, 1, 1)
    games = [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team,
            opponent=opponent,
        )
        for index in range(1, 5)
    ]
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

    row = next(
        split
        for split in compute_absence_splits(session, season=SEASON).rows
        if split.beneficiary_player_id == beneficiary.id and split.absent_player_id == absent.id
    )

    assert row.games_without == 1
    assert row.explicit_absence_games == 1
    assert row.inferred_absence_games == 0
    assert row.excluded_unknown_games == 1
    assert row.uncertainty["sample_sizes"] == {"with": 2, "without": 1}
    assert row.uncertainty["variance_estimable"] == {"with": True, "without": False}


def test_unknown_participation_does_not_override_a_game_log_that_proves_play(
    session: Session,
) -> None:
    team, _, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    teammate = _player(session, "Observed teammate")
    start = date(2026, 1, 10)
    games = [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team,
            opponent=opponent,
        )
        for index in range(1, 4)
    ]
    _register_schedule(session)
    _log(session, player=teammate, game=games[0], team=team, points=10)
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

    row = next(
        split
        for split in compute_absence_splits(session, season=SEASON).rows
        if split.beneficiary_player_id == beneficiary.id and split.absent_player_id == teammate.id
    )

    assert row.games_with == 2
    with_samples = cast(list[dict[str, object]], row.provenance["with_samples"])
    last_target = _dict(with_samples[-1]["target_evidence"])
    assert last_target["kind"] == "player_game_log"
    assert last_target["participation_outcome"] == ParticipationOutcome.UNKNOWN.value


def test_conflicting_play_and_non_play_evidence_fails_loudly(session: Session) -> None:
    team, _, opponent = _teams(session)
    player = _player(session, "Contradiction")
    game = _game(
        session,
        number=1,
        game_date=date(2026, 2, 1),
        team=team,
        opponent=opponent,
    )
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


def test_schedule_lineage_is_required_before_missing_rows_are_examined(session: Session) -> None:
    team, _, opponent = _teams(session)
    _game(
        session,
        number=1,
        game_date=date(2026, 3, 1),
        team=team,
        opponent=opponent,
    )

    with pytest.raises(AbsenceSplitInputError, match="schedule refresh"):
        compute_absence_splits(session, season=SEASON)


def test_same_inputs_reuse_the_persisted_evidence_and_changed_inputs_version_it(
    session: Session,
) -> None:
    team, _, opponent = _teams(session)
    beneficiary = _player(session, "Beneficiary")
    absent = _player(session, "Absent teammate")
    start = date(2026, 4, 1)
    games = [
        _game(
            session,
            number=index,
            game_date=start + timedelta(days=index),
            team=team,
            opponent=opponent,
        )
        for index in range(1, 4)
    ]
    _register_schedule(session)
    _log(session, player=absent, game=games[0], team=team, points=10)
    _log(session, player=absent, game=games[2], team=team, points=10)
    beneficiary_logs = [
        _log(session, player=beneficiary, game=game, team=team, points=points)
        for game, points in zip(games, (10, 20, 30), strict=True)
    ]

    first = compute_absence_splits(session, season=SEASON)
    second = compute_absence_splits(session, season=SEASON)
    assert first.created >= 1
    assert second.created == 0
    assert second.reused == first.created

    beneficiary_logs[1].points = 25
    session.flush()
    third = compute_absence_splits(session, season=SEASON)

    assert third.created >= 1
    pair_rows = session.scalars(
        select(AbsenceSplit).where(
            AbsenceSplit.beneficiary_player_id == beneficiary.id,
            AbsenceSplit.absent_player_id == absent.id,
        )
    ).all()
    assert len(pair_rows) == 2
    assert len({row.input_fingerprint for row in pair_rows}) == 2
    [latest] = [
        row
        for row in latest_absence_splits(session, season=SEASON)
        if row.beneficiary_player_id == beneficiary.id and row.absent_player_id == absent.id
    ]
    latest_without = _dict(_dict(latest.production_without)["counting"])
    assert _dict(latest_without["points"])["per_game"] == 25.0
