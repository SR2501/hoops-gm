"""Parser and calendar queries for the NBA schedule feed.

The schedule endpoint is a fact source.  This module does not decide whether a
slate is light or whether a rest pattern is risky; it only preserves games and
counts them inside the league's existing scoring periods.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from hoops_gm.db.models.league import ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.db.models.stats import NbaGame
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.nba.models import NbaGameRecord

SOURCE = "nba_stats"
ENDPOINT = "ScheduleLeagueV2"
EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ScheduleGameRecord:
    """A resolved regular-season game from ``ScheduleLeagueV2``."""

    game: NbaGameRecord
    home_nba_team_id: int
    away_nba_team_id: int
    home_tricode: str
    away_tricode: str


@dataclass(frozen=True)
class ScheduleParseResult:
    """Resolved games plus explicitly reported games whose teams are TBD."""

    games: tuple[ScheduleGameRecord, ...]
    unresolved_game_ids: tuple[str, ...]
    source_game_count: int


@dataclass(frozen=True)
class ScheduledGameCount:
    """One team's observed game count inside one scoring period."""

    period_number: int
    team_id: int
    games: int


def parse_schedule(payload: Mapping[str, object], *, season: str) -> ScheduleParseResult:
    """Parse the nested ``leagueSchedule`` response and validate its time claims.

    ``gameDateTimeUTC`` is the instant.  ``gameDateTimeEst`` carries a ``Z``
    suffix but is an Eastern wall-clock value, so it is parsed as a wall clock
    and independently reconciled to the UTC sibling.  This prevents the
    schedule adapter from repeating the project's prior mislabeled-time bug.
    """

    league_schedule = payload.get("leagueSchedule")
    if not isinstance(league_schedule, Mapping):
        raise _contract("missing leagueSchedule object")
    if league_schedule.get("seasonYear") != season:
        raise _contract(f"expected season {season!r}, got {league_schedule.get('seasonYear')!r}")
    game_dates = league_schedule.get("gameDates")
    if not isinstance(game_dates, list):
        raise _contract("leagueSchedule.gameDates is not a list")

    records: list[ScheduleGameRecord] = []
    unresolved: list[str] = []
    source_count = 0
    for game_date in game_dates:
        if not isinstance(game_date, Mapping):
            raise _contract("gameDates contains a non-object")
        games = game_date.get("games")
        if not isinstance(games, list):
            raise _contract("gameDates entry has no games list")
        for raw_game in games:
            if not isinstance(raw_game, Mapping):
                raise _contract("games contains a non-object")
            game_id = _required_text(raw_game, "gameId")
            if not game_id.startswith("002"):
                continue
            source_count += 1
            home = _team(raw_game, "homeTeam", game_id)
            away = _team(raw_game, "awayTeam", game_id)
            if home[0] == 0 or away[0] == 0:
                unresolved.append(game_id)
                continue
            utc_tipoff = _parse_utc(raw_game, "gameDateTimeUTC", game_id)
            eastern_tipoff = _parse_eastern_wall_clock(raw_game, "gameDateTimeEst", game_id)
            if eastern_tipoff.astimezone(UTC) != utc_tipoff:
                raise _contract(
                    f"{game_id} has inconsistent EST/UTC tipoff fields: "
                    f"{eastern_tipoff.isoformat()} != {utc_tipoff.isoformat()}"
                )
            game_day = eastern_tipoff.date()
            records.append(
                ScheduleGameRecord(
                    game=NbaGameRecord(
                        nba_game_id=game_id,
                        season=season,
                        season_type="regular",
                        game_date=game_day,
                        home_team_id=home[0],
                        away_team_id=away[0],
                        tipoff_utc=utc_tipoff,
                    ),
                    home_nba_team_id=home[0],
                    away_nba_team_id=away[0],
                    home_tricode=home[1],
                    away_tricode=away[1],
                )
            )

    if len({record.game.nba_game_id for record in records}) != len(records):
        raise _contract("duplicate gameId in schedule")
    return ScheduleParseResult(tuple(records), tuple(unresolved), source_count)


def scheduled_game_counts(
    session: Session, *, league_id: int, season: str
) -> list[ScheduledGameCount]:
    """Count schedule rows against ``scoring_periods``; no week table is created."""

    statement: Select[tuple[int, int, int]] = (
        select(
            ScoringPeriod.period_number,
            TeamScheduleEntry.team_id,
            func.count(TeamScheduleEntry.id),
        )
        .join(
            TeamScheduleEntry,
            TeamScheduleEntry.game_date.between(ScoringPeriod.start_date, ScoringPeriod.end_date),
        )
        .join(NbaGame, NbaGame.id == TeamScheduleEntry.game_id)
        .where(ScoringPeriod.league_id == league_id, NbaGame.season == season)
        .group_by(ScoringPeriod.period_number, TeamScheduleEntry.team_id)
        .order_by(ScoringPeriod.period_number, TeamScheduleEntry.team_id)
    )
    return [
        ScheduledGameCount(period_number, team_id, games)
        for period_number, team_id, games in session.execute(statement)
    ]


def _team(raw_game: Mapping[str, object], key: str, game_id: str) -> tuple[int, str]:
    value = raw_game.get(key)
    if not isinstance(value, Mapping):
        raise _contract(f"{game_id} missing {key} object")
    team_id = value.get("teamId")
    tricode = value.get("teamTricode")
    if not isinstance(team_id, int) or isinstance(team_id, bool) or team_id < 0:
        raise _contract(f"{game_id} has invalid {key}.teamId")
    if team_id == 0:
        return 0, ""
    if not isinstance(tricode, str) or len(tricode) != 3 or not tricode.isupper():
        raise _contract(f"{game_id} has invalid {key}.teamTricode")
    return team_id, tricode


def _parse_utc(raw_game: Mapping[str, object], key: str, game_id: str) -> datetime:
    value = _required_text(raw_game, key)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _contract(f"{game_id} has invalid {key}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _contract(f"{game_id} {key} is not timezone-aware")
    return parsed.astimezone(UTC)


def _parse_eastern_wall_clock(raw_game: Mapping[str, object], key: str, game_id: str) -> datetime:
    value = _required_text(raw_game, key)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", ""))
    except ValueError as exc:
        raise _contract(f"{game_id} has invalid {key}: {value!r}") from exc
    if parsed.tzinfo is not None:
        raise _contract(f"{game_id} {key} must be treated as an Eastern wall clock")
    return parsed.replace(tzinfo=EASTERN)


def _required_text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise _contract(f"missing or invalid {key}")
    return value


def _contract(message: str) -> SourceContractError:
    return SourceContractError(message, source=SOURCE, endpoint=ENDPOINT)
