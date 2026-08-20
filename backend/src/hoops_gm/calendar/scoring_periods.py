"""Materialize the active deadline calendar as current league scoring periods.

``LeagueDeadlineCalendar`` remains the immutable source of truth. The older
``ScoringPeriod`` table is a replaceable projection for date-based schedule and
matchup joins; it is never an ingest target. Because that table has no lineage
columns, this module binds each complete replacement to a keyed ``refresh_runs``
entry whose deterministic version includes the exact calendar, settings, NBA
schedule, and projected period content.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hoops_gm.calendar.deadline_calendar import (
    SCHEMA_VERSION as DEADLINE_CALENDAR_SCHEMA_VERSION,
)
from hoops_gm.calendar.deadline_calendar import (
    DeadlineCalendarStaleActivationError,
    current_deadline_calendar,
    scoring_period_windows,
)
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    content_fingerprint,
    current_refresh,
    lock_league_settings_scope,
    lock_refresh_scope,
    record_refresh,
    verify_refresh,
)
from hoops_gm.db.models.deadline_calendar import LeagueDeadlineCalendar
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.league import League, Matchup, ScoringPeriod
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.ingest.league_settings import LeagueSettingsDocument

EASTERN: Final = ZoneInfo("America/New_York")
PROJECTION_SCHEMA_VERSION: Final = "1"
PROJECTION_SOURCE: Final = "league-deadline-calendar"


class ScoringPeriodProjectionError(RuntimeError):
    """The active calendar cannot support a trustworthy period projection."""


class StaleScoringPeriodProjectionError(ScoringPeriodProjectionError):
    """Stored scoring periods or their registered lineage are no longer current."""


class ScoringPeriodReplacementConflictError(ScoringPeriodProjectionError):
    """A changed projection cannot safely replace periods referenced by matchups."""


@dataclass(frozen=True)
class ProjectedScoringPeriod:
    """One Eastern-calendar-date projection of an authoritative period window."""

    period_number: int
    start_date: date
    end_date: date
    is_playoff: bool


@dataclass(frozen=True)
class ScoringPeriodProjectionLineage:
    """Exact settings, calendar, schedule, and projection cohorts behind a read."""

    projection_refresh_id: int
    projection_version: str
    projection_refreshed_at: datetime
    deadline_calendar_id: int
    deadline_calendar_version: int
    settings_snapshot_id: int
    settings_snapshot_version: int
    schedule_refresh_id: int
    schedule_version: str
    schedule_refreshed_at: datetime


@dataclass(frozen=True)
class ScoringPeriodProjectionResult:
    """What one projection run materialized."""

    lineage: ScoringPeriodProjectionLineage
    created: int
    replaced: int


@dataclass(frozen=True)
class _ProjectionContext:
    calendar: LeagueDeadlineCalendar
    settings_snapshot: LeagueSettingsSnapshot
    schedule_refresh: RefreshRun
    periods: tuple[ProjectedScoringPeriod, ...]
    projection_version: str


def scoring_period_artifact_key(league_id: int) -> str:
    """The refresh-registry stream for one league's period materialization."""

    return f"league-scoring-periods:{league_id}"


def project_scoring_periods(
    session: Session,
    league: League,
    *,
    projected_at: datetime | None = None,
) -> ScoringPeriodProjectionResult:
    """Replace the league's current period materialization from its active calendar.

    Every validation happens before a row is removed. Re-running unchanged
    lineage is a row-level no-op. A changed projection replaces all unreferenced
    rows as one transaction and preserves the prior projection in ``refresh_runs``;
    referenced rows fail closed rather than cascading matchup history away.
    """

    when = projected_at if projected_at is not None else datetime.now(UTC)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("projected_at must be timezone-aware")
    when = when.astimezone(UTC)

    context = _locked_projection_context(session, league)
    existing = tuple(
        session.scalars(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
            # Prevent a concurrent matchup insert from passing the reference
            # check and then being cascade-deleted with the old parent row.
            .with_for_update()
        ).all()
    )
    artifact_key = scoring_period_artifact_key(league.id)
    prior_refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=artifact_key,
        season=league.season,
    )
    if prior_refresh is not None and when < _aware_utc(
        prior_refresh.refreshed_at, path="current projection refresh timestamp"
    ):
        raise ScoringPeriodProjectionError(
            "projected_at precedes the current scoring-period projection refresh"
        )

    unchanged = _rows_match_projection(existing, context.periods)
    replaced = 0
    created = 0

    if not unchanged:
        _reject_referenced_replacement(session, existing)
        replaced = len(existing)
        for row in existing:
            session.delete(row)
        session.flush()

        session.add_all(
            [
                ScoringPeriod(
                    league_id=league.id,
                    period_number=period.period_number,
                    label=None,
                    start_date=period.start_date,
                    end_date=period.end_date,
                    is_playoff=period.is_playoff,
                )
                for period in context.periods
            ]
        )
        session.flush()
        created = len(context.periods)

    refresh = record_refresh(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=artifact_key,
        version=context.projection_version,
        source=PROJECTION_SOURCE,
        season=league.season,
        summary=_projection_summary(league, context),
        refreshed_at=when,
    )
    return ScoringPeriodProjectionResult(
        lineage=_lineage(context, refresh),
        created=created,
        replaced=replaced,
    )


def require_current_scoring_period_projection(
    session: Session,
    league: League,
) -> ScoringPeriodProjectionLineage:
    """Return current projection lineage or reject stale/mismatched materialization."""

    context = _locked_projection_context(session, league)
    rows = tuple(
        session.scalars(
            select(ScoringPeriod)
            .where(ScoringPeriod.league_id == league.id)
            .order_by(ScoringPeriod.period_number)
        ).all()
    )
    if not _rows_match_projection(rows, context.periods):
        raise StaleScoringPeriodProjectionError(
            f"scoring periods for league {league.id} do not match active deadline calendar "
            f"version {context.calendar.version}; run scoring-period projection"
        )

    refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=scoring_period_artifact_key(league.id),
        season=league.season,
    )
    if refresh is None:
        raise StaleScoringPeriodProjectionError(
            f"no scoring-period projection lineage is registered for league {league.id}"
        )
    if refresh.version != context.projection_version:
        raise StaleScoringPeriodProjectionError(
            f"scoring-period projection lineage for league {league.id} is stale: "
            f"registered={refresh.version!r}, expected={context.projection_version!r}"
        )
    return _lineage(context, refresh)


def _locked_projection_context(session: Session, league: League) -> _ProjectionContext:
    lock_league_settings_scope(session, league_id=league.id, season=league.season)
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=league.season,
    )
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=scoring_period_artifact_key(league.id),
        season=league.season,
    )

    try:
        calendar = current_deadline_calendar(session, league)
    except DeadlineCalendarStaleActivationError as exc:
        raise ScoringPeriodProjectionError(f"stale NBA schedule: {exc}") from exc
    if calendar is None:
        raise ScoringPeriodProjectionError(
            f"league {league.id} has no active deadline calendar to project"
        )
    settings_snapshot = session.scalar(
        select(LeagueSettingsSnapshot)
        .where(LeagueSettingsSnapshot.league_id == league.id)
        .order_by(LeagueSettingsSnapshot.version.desc(), LeagueSettingsSnapshot.id.desc())
        .limit(1)
    )
    if settings_snapshot is None:
        raise ScoringPeriodProjectionError(f"league {league.id} has no current settings snapshot")
    schedule_refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=league.season,
    )
    if schedule_refresh is None:
        raise ScoringPeriodProjectionError(
            f"season {league.season!r} has no current NBA schedule refresh"
        )
    try:
        schedule_verification = verify_refresh(session, schedule_refresh)
    except ValueError as exc:
        raise ScoringPeriodProjectionError(
            f"NBA schedule evidence for season {league.season!r} is malformed: {exc}"
        ) from exc
    if not schedule_verification.is_current:
        raise ScoringPeriodProjectionError(
            f"NBA schedule evidence for season {league.season!r} is stale: registered version "
            f"{schedule_refresh.version!r} no longer matches persisted schedule content"
        )

    periods = _validate_and_project(
        league,
        calendar=calendar,
        settings_snapshot=settings_snapshot,
        schedule_refresh=schedule_refresh,
    )
    projection_version = _projection_version(
        league,
        calendar=calendar,
        settings_snapshot=settings_snapshot,
        schedule_refresh=schedule_refresh,
        periods=periods,
    )
    return _ProjectionContext(
        calendar=calendar,
        settings_snapshot=settings_snapshot,
        schedule_refresh=schedule_refresh,
        periods=periods,
        projection_version=projection_version,
    )


def _validate_and_project(
    league: League,
    *,
    calendar: LeagueDeadlineCalendar,
    settings_snapshot: LeagueSettingsSnapshot,
    schedule_refresh: RefreshRun,
) -> tuple[ProjectedScoringPeriod, ...]:
    if calendar.league_id != league.id or calendar.current_for_league != league.id:
        raise ScoringPeriodProjectionError("active deadline calendar is bound to another league")
    if calendar.season != league.season:
        raise ScoringPeriodProjectionError(
            f"active deadline calendar season {calendar.season!r} "
            f"does not match league season {league.season!r}"
        )
    if calendar.schema_version != DEADLINE_CALENDAR_SCHEMA_VERSION:
        raise ScoringPeriodProjectionError(
            f"unsupported deadline calendar schema version {calendar.schema_version!r}"
        )
    if calendar.settings_snapshot_id != settings_snapshot.id:
        raise ScoringPeriodProjectionError(
            f"active deadline calendar version {calendar.version} cites stale settings snapshot "
            f"{calendar.settings_snapshot_id}; current is {settings_snapshot.id}"
        )
    if calendar.settings_snapshot_version != settings_snapshot.version:
        raise ScoringPeriodProjectionError(
            "deadline calendar settings snapshot version does not match its cited row"
        )
    if calendar.schedule_version != schedule_refresh.version:
        raise ScoringPeriodProjectionError(
            f"active deadline calendar version {calendar.version} cites stale NBA schedule "
            f"{calendar.schedule_version!r}; current is {schedule_refresh.version!r}"
        )
    _aware_utc(schedule_refresh.refreshed_at, path="schedule refresh timestamp")
    _aware_utc(calendar.schedule_refreshed_at, path="deadline calendar schedule timestamp")

    try:
        document = LeagueSettingsDocument.model_validate(settings_snapshot.settings)
    except ValidationError as exc:
        raise ScoringPeriodProjectionError(
            f"settings snapshot {settings_snapshot.id} is not a valid settings document"
        ) from exc
    expected_season = f"{document.source_season_year}-{str(document.source_season_year + 1)[-2:]}"
    if document.source_league_id != league.fantrax_league_id or expected_season != league.season:
        raise ScoringPeriodProjectionError(
            "current settings snapshot identity does not match the target league"
        )

    try:
        season_start = date.fromisoformat(document.source_start_date)
        season_end = date.fromisoformat(document.source_end_date)
        expected_windows = scoring_period_windows(document)
    except ValueError as exc:
        raise ScoringPeriodProjectionError(
            f"settings snapshot {settings_snapshot.id} cannot support period projection: {exc}"
        ) from exc
    if (
        calendar.season_start_date != season_start
        or calendar.season_end_date != season_end
        or calendar.scoring_periods != expected_windows
    ):
        raise ScoringPeriodProjectionError(
            f"active deadline calendar version {calendar.version} does not match its cited "
            "settings snapshot"
        )

    periods: list[ProjectedScoringPeriod] = []
    previous: ProjectedScoringPeriod | None = None
    for window in expected_windows:
        period_number = window.get("period_number")
        start_value = window.get("start_at")
        end_value = window.get("end_at")
        is_playoff = window.get("is_playoff")
        if (
            not isinstance(period_number, int)
            or isinstance(period_number, bool)
            or period_number < 1
        ):
            raise ScoringPeriodProjectionError("deadline calendar has an invalid period number")
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            raise ScoringPeriodProjectionError(
                f"deadline calendar period {period_number} has non-text boundaries"
            )
        if not isinstance(is_playoff, bool):
            raise ScoringPeriodProjectionError(
                f"deadline calendar period {period_number} has no authoritative playoff flag; "
                "refusing to turn unknown into False"
            )

        start_at = _parse_aware(start_value, path=f"period {period_number} start_at")
        end_at = _parse_aware(end_value, path=f"period {period_number} end_at")
        start_date = start_at.astimezone(EASTERN).date()
        end_date = end_at.astimezone(EASTERN).date()
        if end_date < start_date:
            raise ScoringPeriodProjectionError(
                f"period {period_number} ends before it starts after Eastern conversion"
            )
        if start_date < season_start or end_date > season_end:
            raise ScoringPeriodProjectionError(
                f"period {period_number} Eastern dates {start_date}..{end_date} fall outside "
                f"season bounds {season_start}..{season_end}"
            )

        period = ProjectedScoringPeriod(
            period_number=period_number,
            start_date=start_date,
            end_date=end_date,
            is_playoff=is_playoff,
        )
        if previous is not None and period.start_date <= previous.end_date:
            raise ScoringPeriodProjectionError(
                f"period {period.period_number} overlaps period {previous.period_number} "
                "after inclusive Eastern-date projection"
            )
        periods.append(period)
        previous = period
    return tuple(periods)


def _projection_version(
    league: League,
    *,
    calendar: LeagueDeadlineCalendar,
    settings_snapshot: LeagueSettingsSnapshot,
    schedule_refresh: RefreshRun,
    periods: tuple[ProjectedScoringPeriod, ...],
) -> str:
    parts = [
        f"schema:{PROJECTION_SCHEMA_VERSION}",
        f"league:{league.id}:{league.season}",
        f"calendar:{calendar.id}:{calendar.version}",
        f"settings:{settings_snapshot.id}:{settings_snapshot.version}",
        f"schedule:{schedule_refresh.id}:{schedule_refresh.version}",
    ]
    parts.extend(
        f"period:{period.period_number}:{period.start_date.isoformat()}:"
        f"{period.end_date.isoformat()}:{period.is_playoff}"
        for period in periods
    )
    return content_fingerprint(parts)


def _projection_summary(league: League, context: _ProjectionContext) -> dict[str, object]:
    return {
        "league_id": league.id,
        "deadline_calendar_id": context.calendar.id,
        "deadline_calendar_version": context.calendar.version,
        "settings_snapshot_id": context.settings_snapshot.id,
        "settings_snapshot_version": context.settings_snapshot.version,
        "nba_schedule_refresh_id": context.schedule_refresh.id,
        "nba_schedule_version": context.schedule_refresh.version,
        "periods": [
            {
                "period_number": period.period_number,
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
                "is_playoff": period.is_playoff,
            }
            for period in context.periods
        ],
    }


def _rows_match_projection(
    rows: tuple[ScoringPeriod, ...],
    periods: tuple[ProjectedScoringPeriod, ...],
) -> bool:
    if len(rows) != len(periods):
        return False
    return all(
        row.period_number == period.period_number
        and row.label is None
        and row.start_date == period.start_date
        and row.end_date == period.end_date
        and row.is_playoff is period.is_playoff
        for row, period in zip(rows, periods, strict=True)
    )


def _reject_referenced_replacement(
    session: Session,
    rows: tuple[ScoringPeriod, ...],
) -> None:
    row_ids = [row.id for row in rows]
    if not row_ids:
        return
    referenced = session.scalar(
        select(func.count()).select_from(Matchup).where(Matchup.scoring_period_id.in_(row_ids))
    )
    if referenced:
        raise ScoringPeriodReplacementConflictError(
            f"cannot replace {len(rows)} scoring periods while {referenced} matchups reference "
            "them; preserving matchup history requires a versioned schema"
        )


def _lineage(
    context: _ProjectionContext,
    refresh: RefreshRun,
) -> ScoringPeriodProjectionLineage:
    return ScoringPeriodProjectionLineage(
        projection_refresh_id=refresh.id,
        projection_version=refresh.version,
        projection_refreshed_at=_aware_utc(
            refresh.refreshed_at, path="projection refresh timestamp"
        ),
        deadline_calendar_id=context.calendar.id,
        deadline_calendar_version=context.calendar.version,
        settings_snapshot_id=context.settings_snapshot.id,
        settings_snapshot_version=context.settings_snapshot.version,
        schedule_refresh_id=context.schedule_refresh.id,
        schedule_version=context.schedule_refresh.version,
        schedule_refreshed_at=_aware_utc(
            context.schedule_refresh.refreshed_at, path="schedule refresh timestamp"
        ),
    )


def _parse_aware(value: str, *, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScoringPeriodProjectionError(
            f"{path} is not a valid ISO 8601 timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScoringPeriodProjectionError(
            f"{path} is timezone-naive; refusing to guess its timezone"
        )
    return parsed


def _aware_utc(value: datetime, *, path: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScoringPeriodProjectionError(f"{path} is timezone-naive")
    return value.astimezone(UTC)
