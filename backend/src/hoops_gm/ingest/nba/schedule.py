"""Parser and calendar queries for the NBA schedule feed.

The schedule endpoint is a fact source.  This module does not decide whether a
slate is light or whether a rest pattern is risky; it only preserves games and
counts them inside the league's existing scoring periods.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, select, true
from sqlalchemy.orm import Session

from hoops_gm.db.models.enums import SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
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


@dataclass(frozen=True)
class ScheduleDensityRecord:
    """Pure calendar facts for one team game from ``team_schedule``."""

    schedule_version: str
    schedule_refreshed_at: datetime
    season: str
    season_type: SeasonType
    team_id: int
    game_id: int
    game_date: date
    is_back_to_back: bool
    rest_days: int | None
    rest_days_differential: int | None
    games_in_4_days: int
    is_3_in_4: bool
    games_in_5_days: int
    is_4_in_5: bool
    games_in_6_days: int
    is_4_in_6: bool
    road_trip_length: int
    road_trip_structure: tuple[int, ...]


def build_schedule_density(
    entries: Sequence[TeamScheduleEntry],
    *,
    schedule_version: str,
    schedule_refreshed_at: datetime,
) -> list[ScheduleDensityRecord]:
    """Compute the calendar facts that pure schedule-density is allowed to know.

    The function is intentionally derived only from ``team_schedule`` rows:
    dates, opponents, home/away flags, and game order. The caller must carry the
    schedule refresh cohort into the result so downstream context cannot mix
    density facts from one refresh with schedule rows from another.
    """

    if not schedule_version:
        raise ValueError("schedule_version must not be empty")
    if schedule_refreshed_at.tzinfo is None or schedule_refreshed_at.utcoffset() is None:
        raise ValueError("schedule_refreshed_at must be timezone-aware")
    cohorts = {(entry.season, entry.season_type) for entry in entries}
    if len(cohorts) > 1:
        raise ValueError("schedule density entries must belong to one season and season type")

    per_team: dict[int, list[TeamScheduleEntry]] = defaultdict(list)
    for entry in entries:
        per_team[entry.team_id].append(entry)

    ordered_by_team = {
        team_id: sorted(
            team_entries,
            key=lambda entry: (entry.game_date, entry.game_id or 0),
        )
        for team_id, team_entries in per_team.items()
    }
    rest_by_team_game = _rest_days_by_team_game(ordered_by_team)
    refreshed_at_utc = schedule_refreshed_at.astimezone(UTC)

    density_rows: list[ScheduleDensityRecord] = []
    for team_id in sorted(ordered_by_team):
        ordered = ordered_by_team[team_id]
        current_trip: list[TeamScheduleEntry] = []
        previous: TeamScheduleEntry | None = None

        for entry in ordered:
            rest_days = rest_by_team_game[(team_id, entry.game_id)]
            opponent_rest_days = rest_by_team_game.get((entry.opponent_team_id, entry.game_id))
            rest_days_differential = (
                None
                if rest_days is None or opponent_rest_days is None
                else rest_days - opponent_rest_days
            )

            games_in_4_days = _games_in_window(ordered, entry.game_date, 4)
            games_in_5_days = _games_in_window(ordered, entry.game_date, 5)
            games_in_6_days = _games_in_window(ordered, entry.game_date, 6)

            if entry.is_home:
                road_trip_length = 0
                road_trip_structure: tuple[int, ...] = ()
                current_trip = []
            else:
                if previous is None or previous.is_home:
                    current_trip = [entry]
                else:
                    current_trip.append(entry)
                road_trip_length = len(current_trip)
                road_trip_structure = tuple(
                    trip_entry.opponent_team_id for trip_entry in current_trip
                )

            density_rows.append(
                ScheduleDensityRecord(
                    schedule_version=schedule_version,
                    schedule_refreshed_at=refreshed_at_utc,
                    season=entry.season,
                    season_type=entry.season_type,
                    team_id=team_id,
                    game_id=entry.game_id,
                    game_date=entry.game_date,
                    is_back_to_back=rest_days == 0,
                    rest_days=rest_days,
                    rest_days_differential=rest_days_differential,
                    games_in_4_days=games_in_4_days,
                    is_3_in_4=games_in_4_days >= 3,
                    games_in_5_days=games_in_5_days,
                    is_4_in_5=games_in_5_days >= 4,
                    games_in_6_days=games_in_6_days,
                    is_4_in_6=games_in_6_days >= 4,
                    road_trip_length=road_trip_length,
                    road_trip_structure=road_trip_structure,
                )
            )
            previous = entry

    return density_rows


def team_schedule_density(
    entries: Sequence[TeamScheduleEntry],
    *,
    schedule_version: str,
    schedule_refreshed_at: datetime,
) -> list[ScheduleDensityRecord]:
    return build_schedule_density(
        entries,
        schedule_version=schedule_version,
        schedule_refreshed_at=schedule_refreshed_at,
    )


def schedule_density(
    entries: Sequence[TeamScheduleEntry],
    *,
    schedule_version: str,
    schedule_refreshed_at: datetime,
) -> list[ScheduleDensityRecord]:
    return build_schedule_density(
        entries,
        schedule_version=schedule_version,
        schedule_refreshed_at=schedule_refreshed_at,
    )


def compute_schedule_density(
    entries: Sequence[TeamScheduleEntry],
    *,
    schedule_version: str,
    schedule_refreshed_at: datetime,
) -> list[ScheduleDensityRecord]:
    return build_schedule_density(
        entries,
        schedule_version=schedule_version,
        schedule_refreshed_at=schedule_refreshed_at,
    )


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
    session: Session,
    *,
    league_id: int,
    season: str,
    playoff_only: bool = False,
) -> list[ScheduledGameCount]:
    """Return the complete active-team grid for the league's scoring periods.

    Zero-game teams and periods are explicit rows rather than missing data. The
    scoring-period calendar remains league-owned; no duplicate week table is
    created.
    """

    statement: Select[tuple[int, int, int]] = (
        select(
            ScoringPeriod.period_number,
            NbaTeam.id,
            func.count(TeamScheduleEntry.id),
        )
        .select_from(ScoringPeriod)
        .join(NbaTeam, true())
        .outerjoin(
            TeamScheduleEntry,
            and_(
                TeamScheduleEntry.team_id == NbaTeam.id,
                TeamScheduleEntry.season == season,
                TeamScheduleEntry.season_type == SeasonType.REGULAR,
                TeamScheduleEntry.game_date.between(
                    ScoringPeriod.start_date, ScoringPeriod.end_date
                ),
            ),
        )
        .where(
            ScoringPeriod.league_id == league_id,
            NbaTeam.is_active.is_(True),
        )
        .group_by(ScoringPeriod.period_number, NbaTeam.id)
        .order_by(ScoringPeriod.period_number, NbaTeam.id)
    )
    if playoff_only:
        statement = statement.where(ScoringPeriod.is_playoff.is_(True))

    return [
        ScheduledGameCount(period_number, team_id, games)
        for period_number, team_id, games in session.execute(statement)
    ]


def playoff_scheduled_game_counts(
    session: Session, *, league_id: int, season: str
) -> list[ScheduledGameCount]:
    """Return raw game counts only for this league's flagged playoff periods."""

    return scheduled_game_counts(
        session,
        league_id=league_id,
        season=season,
        playoff_only=True,
    )


def _games_in_window(ordered: Sequence[TeamScheduleEntry], current_date: date, days: int) -> int:
    start = current_date - timedelta(days=days - 1)
    return sum(1 for entry in ordered if start <= entry.game_date <= current_date)


def _rest_days_by_team_game(
    ordered_by_team: Mapping[int, Sequence[TeamScheduleEntry]],
) -> dict[tuple[int, int], int | None]:
    rest_by_team_game: dict[tuple[int, int], int | None] = {}
    for team_id, ordered in ordered_by_team.items():
        previous: TeamScheduleEntry | None = None
        for entry in ordered:
            rest_by_team_game[(team_id, entry.game_id)] = (
                None if previous is None else (entry.game_date - previous.game_date).days - 1
            )
            previous = entry
    return rest_by_team_game


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
