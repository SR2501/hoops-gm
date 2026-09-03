"""Seed a tiny, unmistakably synthetic descriptive reliability cohort.

This module exists only to make the Reliability screen reachable in the unified
portal demo. It does not publish a grade, projected games, recommendation, or
``p(play)``. The two player names, schedule source, and observation source all
carry ``synthetic demo`` provenance so a rendered row cannot be mistaken for
historical NBA evidence.

The synthetic identity anchors are inserted locally with zero confidence and an
explicit ``synthetic-demo`` source detail because routing them through
``import_nba_players`` would falsely claim NBA.com supplied them. Every evidence
row then goes through the same production schedule and box-score writers as an
ingest, and the descriptive claim uses ``publish_reliability_cohorts``.
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
from hoops_gm.db.models.enums import ExternalSource, FieldEvidence, MatchMethod
from hoops_gm.db.models.identity import NbaTeam, Player, PlayerExternalId
from hoops_gm.identity.names import normalize_name
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
DEMO_PLAYER_IDS = (990_000_001, 990_000_002)
DEMO_PLAYER_NAMES = (
    "[synthetic demo] steady observation example",
    "[synthetic demo] interrupted observation example",
)
DEMO_GAME_DATES = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 8))
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


def _teams(session: Session) -> tuple[NbaTeam, NbaTeam]:
    teams = tuple(session.scalars(select(NbaTeam).order_by(NbaTeam.nba_team_id).limit(2)))
    if len(teams) != 2:
        raise ValueError(
            "the reliability demo needs two teams imported by the schedule seed; "
            f"found {len(teams)}"
        )
    return teams


def _schedule(home: NbaTeam, away: NbaTeam) -> ScheduleParseResult:
    records = tuple(
        ScheduleGameRecord(
            game=NbaGameRecord(
                nba_game_id=DEMO_GAME_IDS[index - 1],
                season=EVIDENCE_SEASON,
                season_type="regular",
                game_date=game_date,
                home_team_id=home.nba_team_id,
                away_team_id=away.nba_team_id,
                home_score=110 + index,
                away_score=100 + index,
                tipoff_utc=datetime(
                    game_date.year,
                    game_date.month,
                    game_date.day,
                    23,
                    30,
                    tzinfo=UTC,
                ),
            ),
            home_nba_team_id=home.nba_team_id,
            away_nba_team_id=away.nba_team_id,
            home_tricode=home.abbreviation,
            away_tricode=away.abbreviation,
        )
        for index, game_date in enumerate(DEMO_GAME_DATES, start=1)
    )
    return ScheduleParseResult(
        season=EVIDENCE_SEASON,
        games=records,
        unresolved_game_ids=(),
        source_game_count=len(records),
        pending_games=(),
    )


def _players(session: Session, home: NbaTeam, away: NbaTeam) -> None:
    for player_id, name, team in zip(
        DEMO_PLAYER_IDS,
        DEMO_PLAYER_NAMES,
        (home, away),
        strict=True,
    ):
        normalized = normalize_name(name)
        player = Player(
            full_name=name,
            normalized_name=normalized.key,
            first_name=normalized.first or None,
            last_name=normalized.last or None,
            current_team_id=team.id,
        )
        session.add(player)
        session.flush()
        session.add(
            PlayerExternalId(
                player_id=player.id,
                source=ExternalSource.NBA,
                current_for_source=ExternalSource.NBA.value,
                source_detail="synthetic-demo",
                external_id=str(player_id),
                external_name=name,
                normalized_name=normalized.key,
                external_team=team.abbreviation,
                confidence=0.0,
                match_method=MatchMethod.ANCHOR_ID,
                name_evidence=FieldEvidence.UNKNOWN,
            )
        )
    session.flush()


def _box_score(
    *,
    player_id: int,
    player_name: str,
    game_index: int,
    team: NbaTeam,
) -> PlayerBoxScoreRecord:
    return PlayerBoxScoreRecord(
        nba_player_id=player_id,
        nba_game_id=DEMO_GAME_IDS[game_index - 1],
        nba_team_id=team.nba_team_id,
        player_name=player_name,
        seconds_played=1_740 + game_index * 120,
        field_goals_made=5 + game_index,
        field_goals_attempted=10 + game_index,
        three_pointers_made=1 + game_index,
        three_pointers_attempted=4 + game_index,
        free_throws_made=3,
        free_throws_attempted=4,
        points=16 + game_index * 2,
        offensive_rebounds=1,
        defensive_rebounds=4 + game_index,
        rebounds=5 + game_index,
        assists=3 + game_index,
        steals=1,
        blocks=game_index % 2,
        turnovers=2,
        personal_fouls=2,
        plus_minus=game_index,
        started=True,
    )


def seed_reliability_demo(session: Session) -> ReliabilityDemoSeedResult:
    """Publish two synthetic descriptive scorecards through production writers."""

    home, away = _teams(session)
    _players(session, home, away)
    import_schedule(session, _schedule(home, away), source=DEMO_SCHEDULE_SOURCE)

    box_scores = [
        _box_score(
            player_id=DEMO_PLAYER_IDS[0],
            player_name=DEMO_PLAYER_NAMES[0],
            game_index=index,
            team=home,
        )
        for index in range(1, len(DEMO_GAME_DATES) + 1)
    ]
    box_scores.append(
        _box_score(
            player_id=DEMO_PLAYER_IDS[1],
            player_name=DEMO_PLAYER_NAMES[1],
            game_index=1,
            team=away,
        )
    )
    imported_logs = import_box_scores(session, box_scores)

    claim = publish_reliability_cohorts(
        session,
        season=EVIDENCE_SEASON,
        as_of_date=DEMO_GAME_DATES[-1],
        refreshed_at=SEEDED_AT,
    )
    run = compute_reliability_scorecards(session, claim=claim, computed_at=SEEDED_AT)
    expected = (2, 3, 4, 0)
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
