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
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, select, true
from sqlalchemy.orm import Session

from hoops_gm.calendar.scoring_periods import require_current_scoring_period_projection
from hoops_gm.db.lineage import PendingScheduleGame
from hoops_gm.db.models.enums import SeasonType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.schedule import TeamScheduleEntry
from hoops_gm.ingest.errors import SourceContractError
from hoops_gm.ingest.nba.models import NbaGameRecord

SOURCE = "nba_stats"
ENDPOINT = "ScheduleLeagueV2"
EASTERN = ZoneInfo("America/New_York")

#: Every field in a ``ScheduleLeagueV2`` team block that names a franchise.
#: Observed on the live 2026-27 payload (2026-08-20): a team block carries
#: ``teamId``, ``teamName``, ``teamCity``, ``teamTricode``, ``teamSlug``,
#: ``wins``, ``losses``, ``score`` and ``seed``. Only the naming fields are
#: listed — ``wins``/``losses``/``score``/``seed`` are zero for *every*
#: not-yet-played game, so requiring them absent would classify the whole
#: future schedule as contradictory.
_TEAM_IDENTITY_FIELDS: tuple[str, ...] = ("teamName", "teamCity", "teamTricode", "teamSlug")


class _TeamState(Enum):
    """How much the source told us about one side of a game."""

    RESOLVED = "resolved"
    #: Identity withheld entirely — id zero and every naming field empty.
    PENDING = "pending"
    #: Id zero but a naming field populated: assigned, and unresolvable.
    CONTRADICTORY = "contradictory"


@dataclass(frozen=True)
class _TeamSide:
    team_id: int
    tricode: str
    state: _TeamState


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
    """Resolved games, source-declared pending games, and resolution failures.

    ``season`` is carried on the result rather than inferred from ``games`` so
    that an empty or wholly unresolved parse is still self-describing: the
    importer has to be able to say *which* season it refused to register a
    refresh for, and a season derived from zero records cannot say that.

    **``pending_games`` and ``unresolved_game_ids`` are different things and
    the difference is the whole of ADR-013.** A pending game is one the source
    published with an explicitly absent identity block; it does not block
    registration. An unresolved game is one the source claims to have assigned
    — it named a team without giving an id — and it still refuses, because
    that is indistinguishable from the parser silently losing a team, which is
    the 1,225-of-1,230 defect the completeness contract was written for.

    Every counted regular-season game lands in exactly one of the three, so
    ``source_game_count == len(games) + len(pending_games) +
    len(unresolved_game_ids)`` holds by construction.
    """

    season: str
    games: tuple[ScheduleGameRecord, ...]
    unresolved_game_ids: tuple[str, ...]
    source_game_count: int
    pending_games: tuple[PendingScheduleGame, ...] = ()

    @property
    def pending_game_ids(self) -> tuple[str, ...]:
        return tuple(game.nba_game_id for game in self.pending_games)


@dataclass(frozen=True)
class ScheduledGameCount:
    """One team's observed game count with exact schedule and period lineage."""

    schedule_refresh_id: int
    schedule_version: str
    schedule_refreshed_at: datetime
    projection_refresh_id: int
    projection_version: str
    projection_refreshed_at: datetime
    deadline_calendar_id: int
    deadline_calendar_version: int
    settings_snapshot_id: int
    settings_snapshot_version: int
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

    **Pending games are reconciled but do not refuse on failure.** The same
    two fields are read, and an unusable result degrades the pending game's
    date to ``None`` with a recorded cause instead of raising — see
    :func:`_pending_game_date` for why the asymmetry is drawn there and not
    somewhere else. Classification therefore happens *before* the strict
    reconciliation below, which is what keeps one bad timestamp on one undrawn
    Cup fixture from costing the other 1,200 games.
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
    pending: list[PendingScheduleGame] = []
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
            if home.state is _TeamState.CONTRADICTORY or away.state is _TeamState.CONTRADICTORY:
                unresolved.append(game_id)
                continue

            if home.state is _TeamState.PENDING or away.state is _TeamState.PENDING:
                game_date_value, absence_reason = _pending_game_date(raw_game, game_id, season)
                pending.append(
                    PendingScheduleGame(
                        nba_game_id=game_id,
                        game_date=game_date_value,
                        game_label=_optional_text(raw_game, "gameLabel"),
                        game_sub_label=_optional_text(raw_game, "gameSubLabel"),
                        game_subtype=_optional_text(raw_game, "gameSubtype"),
                        date_absence_reason=absence_reason,
                    )
                )
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
                        home_team_id=home.team_id,
                        away_team_id=away.team_id,
                        tipoff_utc=utc_tipoff,
                    ),
                    home_nba_team_id=home.team_id,
                    away_nba_team_id=away.team_id,
                    home_tricode=home.tricode,
                    away_tricode=away.tricode,
                )
            )

    seen = [record.game.nba_game_id for record in records]
    seen.extend(game.nba_game_id for game in pending)
    seen.extend(unresolved)
    if len(set(seen)) != len(seen):
        raise _contract("duplicate gameId in schedule")
    return ScheduleParseResult(
        season=season,
        games=tuple(records),
        unresolved_game_ids=tuple(unresolved),
        source_game_count=source_count,
        pending_games=tuple(pending),
    )


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

    league = session.get(League, league_id)
    if league is None:
        raise RuntimeError(f"league {league_id} does not exist")
    if league.season != season:
        raise RuntimeError(f"league {league_id} is for season {league.season!r}, not {season!r}")

    lineage = require_current_scoring_period_projection(session, league)

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
        ScheduledGameCount(
            schedule_refresh_id=lineage.schedule_refresh_id,
            schedule_version=lineage.schedule_version,
            schedule_refreshed_at=lineage.schedule_refreshed_at,
            projection_refresh_id=lineage.projection_refresh_id,
            projection_version=lineage.projection_version,
            projection_refreshed_at=lineage.projection_refreshed_at,
            deadline_calendar_id=lineage.deadline_calendar_id,
            deadline_calendar_version=lineage.deadline_calendar_version,
            settings_snapshot_id=lineage.settings_snapshot_id,
            settings_snapshot_version=lineage.settings_snapshot_version,
            period_number=period_number,
            team_id=team_id,
            games=games,
        )
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


def _pending_game_date(
    raw_game: Mapping[str, object], game_id: str, season: str
) -> tuple[date | None, str]:
    """The Eastern date of a pending game, and why it is absent when it is.

    **Deliberately lenient where the resolved path is strict.** The rule is
    *strictness proportional to the consequence of being wrong*, and the
    consequence is set by whether the value is persisted and joined. A resolved
    game's date becomes ``team_schedule`` rows, joins ``player_participation``,
    and is the denominator of every expected-games number, so a bad one must
    stop everything. A pending game's date is persisted nowhere: it exists only
    to tell a consumer *which scoring period is provisional*, and a missing one
    costs a screen affordance.

    Applying the strict reconciliation here meant one degenerate timestamp on
    one undrawn Cup fixture returned **no season at all** — not 1,200 games
    with one flagged, not even a ``--dry-run`` view. That is ADR-013's
    explicitly rejected outcome arriving through a different field, and the
    source argues it is reachable: all six pending games carry
    ``seriesText: "Date subject to change"``, and the same objects already use
    a degenerate year-0001 sentinel for ``gameTimeEst`` where a resolved game
    uses 1900.

    **Not** because the two time fields are non-independent. They are — a
    game's ``gameDateTimeUTC`` is an exact offset conversion of its
    ``gameDateTimeEst`` — but that is true of every game in the payload,
    resolved and pending alike, so it cannot ground an asymmetry between them.
    An earlier version of this docstring gave that as the reason; if it held it
    would equally justify deleting the resolved-side check. The resolved check
    stays because it costs nothing and would catch a schema change, which is a
    legitimate reason to keep a guard the current source cannot trip.

    **The reason is returned, not just the absence, because the three causes
    are not the same news and only one of them is "not yet decided".** A bare
    ``None`` conflated *the source declined to give a date* with *we could not
    read the date it gave*, and the conflation ran in the comforting
    direction: told the source has not decided, an operator waits; told the
    date could not be read, an operator investigates. Reporting the cause is
    cheaper and more honest than either conflating them or moving the refusal
    boundary back onto a field nothing persists:

    ``""``
        A date was published, reconciled, and falls inside the season.
    ``not_offered``
        **Both** time fields are absent or empty. This is the only cause that
        means "the source has not committed to a date." It requires both,
        because a payload giving the date in one field and not the other is
        the source *having* committed — a reviewer caught an earlier version
        reporting exactly that as ``not_offered``, which is the same
        wait-versus-investigate conflation this function exists to remove,
        reproduced one level down.
    ``unreadable``
        A value was published and we could not parse it, or it carried a
        timezone where an Eastern wall clock is expected, or one field was
        given and its sibling withheld. **This is our failure or a schema
        change, not an undecided bracket**, and the live smoke asserts it
        never occurs.
    ``irreconcilable``
        Both fields parsed and disagree — the source contradicting itself.
    ``implausible``
        Both fields parsed and agree, and the date is nowhere near the season
        it claims to belong to. This exists because **agreement is not
        validity**: the NBA uses a ``1900-01-01`` epoch as a live placeholder
        for a time-only field on every resolved game in the payload, and a
        placeholder pair in the *date* fields would reconcile perfectly —
        1900's Eastern offset really is -05:00 — and be recorded as a decided
        date in 1900. That is strictly worse than ``None``, which at least
        says we do not know. The year-0001 sentinel only fails reconciliation
        by accident, because ``America/New_York`` was on a -04:56 local mean
        time before 1883; one year over, the same trick reconciles.
    """

    values: list[str] = []
    for key in ("gameDateTimeUTC", "gameDateTimeEst"):
        value = raw_game.get(key)
        if value is not None and value != "":
            values.append(key)
    if not values:
        return None, "not_offered"
    if len(values) == 1:
        # One field given, its sibling withheld. The source *has* committed to
        # a date; we cannot read it in the shape this parser requires, which
        # is a schema change on our read path rather than an undecided
        # bracket.
        return None, "unreadable"
    try:
        utc_tipoff = _parse_utc(raw_game, "gameDateTimeUTC", game_id)
        eastern_tipoff = _parse_eastern_wall_clock(raw_game, "gameDateTimeEst", game_id)
    except (SourceContractError, OverflowError):
        # OverflowError, not just the contract error: `astimezone` raises it
        # for a datetime whose conversion falls outside `datetime.min`/`max`,
        # and this function's whole purpose is that no pending-game timestamp
        # can cost the season. A year-0001 value one non-UTC offset from the
        # boundary does exactly that, and year-0001 is the sentinel this
        # source is already observed to emit for undecided times.
        return None, "unreadable"
    try:
        reconciles = eastern_tipoff.astimezone(UTC) == utc_tipoff
    except OverflowError:
        return None, "unreadable"
    if not reconciles:
        return None, "irreconcilable"
    game_day = eastern_tipoff.date()
    if not _plausible_season_date(game_day, season):
        return None, "implausible"
    return game_day, ""


def _plausible_season_date(game_day: date, season: str) -> bool:
    """Is this date anywhere near the season it claims to belong to?

    A deliberately loose bound — July to July around a season that runs
    October to June — because its job is to catch an epoch placeholder, not to
    police the calendar. The NBA's own schedule shifts by weeks; a sentinel
    misses by a century.

    ``season`` is ``NNNN-NN``, already validated against the payload's
    ``seasonYear`` before any game is read, so the leading year is trustworthy
    here.
    """

    try:
        start_year = int(season.split("-", 1)[0])
    except ValueError:  # pragma: no cover - season shape is validated upstream
        return True
    return date(start_year, 7, 1) <= game_day < date(start_year + 2, 7, 1)


def _team(raw_game: Mapping[str, object], key: str, game_id: str) -> _TeamSide:
    """Classify one side of a game as resolved, source-declared pending, or contradictory.

    The three-way split is ADR-013's, and the middle branch is deliberately
    narrow. **Pending requires the source to have withheld the identity
    entirely**: ``teamId`` zero *and* every one of ``teamName``, ``teamCity``,
    ``teamTricode`` and ``teamSlug`` absent, null or empty. That is exactly
    what the live 2026-27 payload publishes for the six Emirates NBA Cup
    knockout fixtures, verified 2026-08-20.

    A zero ``teamId`` beside *any* populated identity field is
    ``CONTRADICTORY``: the source has named a team it gave no id for, which is
    "claims to have assigned but we cannot resolve" and must still refuse. It
    is also the branch that keeps the refusal reachable — without it the
    parser could only resolve, zero out, or raise, and
    ``unresolved_game_ids`` would be a guard that reads correctly and can
    never fire.
    """

    value = raw_game.get(key)
    if not isinstance(value, Mapping):
        raise _contract(f"{game_id} missing {key} object")
    team_id = value.get("teamId")
    tricode = value.get("teamTricode")
    if not isinstance(team_id, int) or isinstance(team_id, bool) or team_id < 0:
        raise _contract(f"{game_id} has invalid {key}.teamId")
    if team_id == 0:
        named = sorted(field for field in _TEAM_IDENTITY_FIELDS if not _is_absent(value.get(field)))
        if named:
            return _TeamSide(0, "", _TeamState.CONTRADICTORY)
        return _TeamSide(0, "", _TeamState.PENDING)
    if not isinstance(tricode, str) or len(tricode) != 3 or not tricode.isupper():
        raise _contract(f"{game_id} has invalid {key}.teamTricode")
    return _TeamSide(team_id, tricode, _TeamState.RESOLVED)


def _is_absent(value: object) -> bool:
    """True when the source withheld a field rather than populating it."""

    return value is None or value == ""


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


def _optional_text(raw: Mapping[str, object], key: str) -> str:
    """A label the source may legitimately leave blank, normalised to ``""``.

    Deliberately lenient where :func:`_required_text` is strict: these are
    descriptive labels, not identifiers, and refusing a whole season's import
    because the NBA left ``gameSubLabel`` off one Cup fixture would be the
    wrong trade. The live smoke, not the parser, is what asserts the labels
    still explain the pending set.
    """

    value = raw.get(key)
    return value if isinstance(value, str) else ""


def _contract(message: str) -> SourceContractError:
    return SourceContractError(message, source=SOURCE, endpoint=ENDPOINT)
