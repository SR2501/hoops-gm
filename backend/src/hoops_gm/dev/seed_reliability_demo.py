"""Seed a tiny, unmistakably synthetic descriptive reliability cohort.

This module exists only to make the Reliability screen reachable in the unified
portal demo. It does not publish a grade, projected games, recommendation, or
``p(play)``. It gives five players from the synthetic projection cohort two
invented appearances each. Five is deliberate: all remain undrafted in the
composed fixture, so the overlap can supply the largest allowed 3-5 candidate
shortlist without pretending one observed appearance is a durability history.

The player identities are canonical because the projection importer already
resolved them. The observations are not: every synthetic game id and the
schedule refresh source say ``synthetic-reliability-demo``. Evidence rows go
through the production schedule and box-score writers, and the descriptive
claim uses ``publish_reliability_cohorts``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.api.routes.reliability import EVIDENCE_SEASON
from hoops_gm.availability import (
    RELIABILITY_OBSERVATION_SOURCE,
    compute_reliability_scorecards,
    publish_reliability_cohorts,
)
from hoops_gm.db.models.enums import ExternalSource
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.ingest.importers import (
    import_box_scores,
    import_schedule,
)
from hoops_gm.ingest.nba.models import (
    NbaGameRecord,
    PlayerBoxScoreRecord,
)
from hoops_gm.ingest.nba.schedule import ScheduleGameRecord, ScheduleParseResult

DEMO_SCHEDULE_SOURCE = "synthetic-demo:hoops_gm.dev.seed_reliability_demo:schedule"
DEMO_PLAYER_COUNT = 5
DEMO_APPEARANCES_PER_PLAYER = 2
DEMO_GAME_DATES = (
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 1, 9),
    date(2026, 1, 12),
    date(2026, 1, 13),
    date(2026, 1, 14),
    date(2026, 1, 15),
    date(2026, 1, 16),
)
DEMO_GAME_IDS = tuple(
    f"synthetic-reliability-demo-{index}" for index in range(1, len(DEMO_GAME_DATES) + 1)
)
SEEDED_AT = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class ReliabilityDemoSeedResult:
    season: str
    scorecards: int
    final_games: int
    player_game_logs: int
    participation_rows: int
    schedule_source: str
    observation_source: str


@dataclass(frozen=True)
class ReliabilityDemoPlayer:
    player_id: int
    nba_player_id: int
    player_name: str
    team: NbaTeam


def _players(session: Session, player_ids: tuple[int, ...]) -> tuple[ReliabilityDemoPlayer, ...]:
    if len(player_ids) != DEMO_PLAYER_COUNT or len(set(player_ids)) != DEMO_PLAYER_COUNT:
        raise ValueError(
            f"the reliability demo needs {DEMO_PLAYER_COUNT} distinct projected players; "
            f"received {len(set(player_ids))} distinct ids"
        )
    rows = session.execute(
        select(Player, PlayerExternalId, NbaTeam)
        .join(
            PlayerExternalId,
            (PlayerExternalId.player_id == Player.id)
            & (PlayerExternalId.current_for_source == ExternalSource.NBA.value),
        )
        .join(NbaTeam, NbaTeam.id == Player.current_team_id)
        .where(Player.id.in_(player_ids))
    ).all()
    by_id = {
        player.id: ReliabilityDemoPlayer(
            player_id=player.id,
            nba_player_id=int(external.external_id),
            player_name=player.full_name,
            team=team,
        )
        for player, external, team in rows
    }
    missing = [player_id for player_id in player_ids if player_id not in by_id]
    if missing:
        raise ValueError(
            "the reliability demo requires a current NBA identity and team for every "
            f"projected player; missing internal player ids {missing}"
        )
    return tuple(by_id[player_id] for player_id in player_ids)


def _opponents(session: Session, players: tuple[ReliabilityDemoPlayer, ...]) -> tuple[NbaTeam, ...]:
    teams = tuple(session.scalars(select(NbaTeam).order_by(NbaTeam.nba_team_id)))
    if len(teams) < 2:
        raise ValueError(
            "the reliability demo needs at least two teams imported by the schedule seed; "
            f"found {len(teams)}"
        )
    return tuple(
        next(
            team
            for team in (*teams[player_index + 1 :], *teams[: player_index + 1])
            if team.id != player.team.id
        )
        for player_index, player in enumerate(players)
    )


def _schedule(
    players: tuple[ReliabilityDemoPlayer, ...], opponents: tuple[NbaTeam, ...]
) -> ScheduleParseResult:
    records: list[ScheduleGameRecord] = []
    for appearance in range(DEMO_APPEARANCES_PER_PLAYER):
        for player_index, (player, opponent) in enumerate(zip(players, opponents, strict=True)):
            game_index = appearance * DEMO_PLAYER_COUNT + player_index
            game_date = DEMO_GAME_DATES[game_index]
            records.append(
                ScheduleGameRecord(
                    game=NbaGameRecord(
                        nba_game_id=DEMO_GAME_IDS[game_index],
                        season=EVIDENCE_SEASON,
                        season_type="regular",
                        game_date=game_date,
                        home_team_id=player.team.nba_team_id,
                        away_team_id=opponent.nba_team_id,
                        home_score=110 + game_index,
                        away_score=100 + game_index,
                        tipoff_utc=datetime(
                            game_date.year,
                            game_date.month,
                            game_date.day,
                            23,
                            30,
                            tzinfo=UTC,
                        ),
                    ),
                    home_nba_team_id=player.team.nba_team_id,
                    away_nba_team_id=opponent.nba_team_id,
                    home_tricode=player.team.abbreviation,
                    away_tricode=opponent.abbreviation,
                )
            )
    return ScheduleParseResult(
        season=EVIDENCE_SEASON,
        games=tuple(records),
        unresolved_game_ids=(),
        source_game_count=len(records),
        pending_games=(),
    )


def _box_score(
    *,
    player: ReliabilityDemoPlayer,
    game_index: int,
) -> PlayerBoxScoreRecord:
    return PlayerBoxScoreRecord(
        nba_player_id=player.nba_player_id,
        nba_game_id=DEMO_GAME_IDS[game_index],
        nba_team_id=player.team.nba_team_id,
        player_name=player.player_name,
        seconds_played=1_740 + (game_index % DEMO_PLAYER_COUNT) * 60,
        field_goals_made=5 + game_index % 3,
        field_goals_attempted=10 + game_index % 4,
        three_pointers_made=1 + game_index % 2,
        three_pointers_attempted=4 + game_index % 3,
        free_throws_made=3,
        free_throws_attempted=4,
        points=16 + game_index % 5,
        offensive_rebounds=1,
        defensive_rebounds=4 + game_index % 3,
        rebounds=5 + game_index % 3,
        assists=3 + game_index % 4,
        steals=1,
        blocks=game_index % 2,
        turnovers=2,
        personal_fouls=2,
        plus_minus=game_index % 6,
        started=True,
    )


def seed_reliability_demo(
    session: Session, *, player_ids: tuple[int, ...]
) -> ReliabilityDemoSeedResult:
    """Publish five projected players' synthetic descriptive scorecards."""

    players = _players(session, player_ids)
    opponents = _opponents(session, players)
    import_schedule(session, _schedule(players, opponents), source=DEMO_SCHEDULE_SOURCE)

    box_scores = [
        _box_score(player=player, game_index=appearance * DEMO_PLAYER_COUNT + player_index)
        for appearance in range(DEMO_APPEARANCES_PER_PLAYER)
        for player_index, player in enumerate(players)
    ]
    imported_logs = import_box_scores(session, box_scores)

    claim = publish_reliability_cohorts(
        session,
        season=EVIDENCE_SEASON,
        as_of_date=DEMO_GAME_DATES[-1],
        refreshed_at=SEEDED_AT,
    )
    run = compute_reliability_scorecards(session, claim=claim, computed_at=SEEDED_AT)
    expected = (
        DEMO_PLAYER_COUNT,
        len(DEMO_GAME_DATES),
        DEMO_PLAYER_COUNT * DEMO_APPEARANCES_PER_PLAYER,
        0,
    )
    actual = (
        len(run.scorecards),
        run.final_games,
        run.player_game_logs,
        run.participation_rows,
    )
    if actual != expected:
        raise ValueError(
            "the synthetic reliability cohort did not produce its declared shape: "
            f"expected {expected}, got {actual}"
        )
    if imported_logs.created + imported_logs.updated != run.player_game_logs:
        raise ValueError(
            "the box-score writer count does not match the published reliability cohort"
        )
    return ReliabilityDemoSeedResult(
        season=EVIDENCE_SEASON,
        scorecards=len(run.scorecards),
        final_games=run.final_games,
        player_game_logs=run.player_game_logs,
        participation_rows=run.participation_rows,
        schedule_source=DEMO_SCHEDULE_SOURCE,
        observation_source=RELIABILITY_OBSERVATION_SOURCE,
    )
