"""Deriving and activating a league's deadline calendar.

See ``hoops_gm.db.models.deadline_calendar`` for the full rationale of what
this joins and why. In short: this module never invents a value. It joins the
league's most recent :class:`~hoops_gm.db.models.league_settings.LeagueSettingsSnapshot`
with the season's most recent schedule refresh cohort
(``hoops_gm.db.lineage``'s ``RefreshRun`` with ``artifact_type=SCHEDULE``),
and fails closed — never falls back to a plausible default, never reads
``docs/league/2025-26-rules-baseline.md`` — whenever either lineage is
missing or the settings snapshot's own identity does not match the league.

**Two different kinds of "stale".** Deriving fails closed when lineage is
simply absent. Activating a *previously derived* calendar version fails
closed on a different question: whether the lineage it was built from is
still each source's current state. A season's schedule can be re-ingested
after a calendar was derived from it, and a settings snapshot can gain a new
version the same way; reactivating a calendar version whose lineage has since
been superseded would silently reinstate stale rules under the "current"
label. Genuine A -> B -> A cycling is still fully supported — it just goes
through :func:`derive_deadline_calendar` again (which returns the existing
row when the lineage is unchanged, or opens a fresh version when it points at
lineage that has since been re-derived back to equivalent content) rather
than reactivating a version whose own recorded lineage has moved on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.db.models.deadline_calendar import LeagueDeadlineCalendar
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.league import League
from hoops_gm.db.models.league_settings import LeagueSettingsSnapshot
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.ingest.league_settings import LeagueSettingsDocument

#: Names the shape of ``scoring_periods``/``unsupported_rules`` this module
#: writes, independent of the settings document's own ``schema_version``.
SCHEMA_VERSION: Final = "1"

#: The timing rules the backlog names explicitly and that Fantrax's official
#: source has never been observed to supply directly. Kept separate from
#: ``roster_limits``/``games_caps``, which are roster-construction rules, not
#: deadline/timing facts, and out of this calendar's scope.
_TIMING_FIELDS: Final[tuple[str, ...]] = (
    "lineup_lock",
    "waivers",
    "trade_deadline",
    "keepers",
    "playoffs",
)


class DeadlineCalendarLineageError(ValueError):
    """The settings or schedule lineage cannot support deriving a calendar."""


class DeadlineCalendarStaleActivationError(ValueError):
    """The requested calendar version's recorded lineage is no longer current."""


@dataclass(frozen=True)
class DeadlineCalendarDerivation:
    """Result of one call to :func:`derive_deadline_calendar`."""

    calendar: LeagueDeadlineCalendar
    #: ``False`` when an existing row for this exact lineage was returned
    #: instead of inserting a duplicate.
    created: bool


def derive_deadline_calendar(
    session: Session,
    league: League,
    *,
    derived_at: datetime | None = None,
) -> DeadlineCalendarDerivation:
    """Join the league's current settings snapshot with its current schedule refresh.

    Fails closed with :class:`DeadlineCalendarLineageError` when either
    lineage is missing, or when the settings snapshot's own league/season
    identity does not match ``league``. Idempotent by exact lineage: calling
    this again while both the settings snapshot and the schedule refresh are
    unchanged returns the existing row rather than creating a duplicate.
    """
    when = derived_at if derived_at is not None else datetime.now(UTC)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("derived_at must be timezone-aware")

    settings_snapshot = _current_settings_snapshot(session, league.id)
    if settings_snapshot is None:
        raise DeadlineCalendarLineageError(
            f"no league-settings snapshot registered for league {league.id}; "
            "season bounds and scoring periods are unknowable"
        )

    document = LeagueSettingsDocument.model_validate(settings_snapshot.settings)
    expected_season = _season_label(document.source_season_year)
    if document.source_league_id != league.fantrax_league_id or expected_season != league.season:
        raise DeadlineCalendarLineageError(
            "league-settings snapshot identity mismatch: "
            f"snapshot league/season={document.source_league_id!r}/{expected_season!r}, "
            f"target league/season={league.fantrax_league_id!r}/{league.season!r}"
        )

    schedule_refresh = _current_schedule_refresh(session, league.season)
    if schedule_refresh is None:
        raise DeadlineCalendarLineageError(
            f"no registered schedule refresh for season {league.season}; "
            "schedule lineage is unknowable"
        )

    existing = session.scalar(
        select(LeagueDeadlineCalendar).where(
            LeagueDeadlineCalendar.league_id == league.id,
            LeagueDeadlineCalendar.settings_snapshot_id == settings_snapshot.id,
            LeagueDeadlineCalendar.schedule_version == schedule_refresh.version,
        )
    )
    if existing is not None:
        return DeadlineCalendarDerivation(calendar=existing, created=False)

    season_start_date = _require_plain_date(document.source_start_date, path="source_start_date")
    season_end_date = _require_plain_date(document.source_end_date, path="source_end_date")
    scoring_periods = _scoring_periods(document)
    unsupported_rules = _unsupported_rules(document)

    latest_version = session.scalar(
        select(LeagueDeadlineCalendar.version)
        .where(LeagueDeadlineCalendar.league_id == league.id)
        .order_by(LeagueDeadlineCalendar.version.desc())
        .limit(1)
    )
    next_version = (latest_version or 0) + 1

    calendar = LeagueDeadlineCalendar(
        league_id=league.id,
        version=next_version,
        schema_version=SCHEMA_VERSION,
        season=league.season,
        settings_snapshot_id=settings_snapshot.id,
        settings_snapshot_version=settings_snapshot.version,
        schedule_version=schedule_refresh.version,
        schedule_refreshed_at=schedule_refresh.refreshed_at,
        season_start_date=season_start_date,
        season_end_date=season_end_date,
        scoring_periods=scoring_periods,
        unsupported_rules=unsupported_rules,
        derived_at=when,
    )
    session.add(calendar)
    session.flush()
    return DeadlineCalendarDerivation(calendar=calendar, created=True)


def activate_deadline_calendar(
    session: Session,
    league: League,
    version: int,
) -> LeagueDeadlineCalendar:
    """Make ``version`` the league's current calendar.

    Re-validates lineage currency before mutating anything: fails closed with
    :class:`DeadlineCalendarStaleActivationError` when a newer settings
    snapshot or schedule refresh has since been registered, so the league can
    never be pinned to lineage that is no longer authoritative. If the target
    is already the league's current calendar, this is a no-op that still
    performs the currency check.
    """
    target = session.scalar(
        select(LeagueDeadlineCalendar).where(
            LeagueDeadlineCalendar.league_id == league.id,
            LeagueDeadlineCalendar.version == version,
        )
    )
    if target is None:
        raise DeadlineCalendarLineageError(
            f"no deadline calendar version {version} for league {league.id}"
        )

    current_settings = _current_settings_snapshot(session, league.id)
    if current_settings is None or current_settings.id != target.settings_snapshot_id:
        raise DeadlineCalendarStaleActivationError(
            f"league {league.id} settings lineage has moved past calendar version {version}"
        )

    current_schedule = _current_schedule_refresh(session, target.season)
    if current_schedule is None or current_schedule.version != target.schedule_version:
        raise DeadlineCalendarStaleActivationError(
            f"schedule lineage for {target.season} has moved past calendar version {version}"
        )

    previously_active = session.scalar(
        select(LeagueDeadlineCalendar).where(
            LeagueDeadlineCalendar.current_for_league == league.id,
        )
    )
    if previously_active is not None and previously_active.id != target.id:
        # Cleared and flushed on its own: the unique constraint on
        # ``current_for_league`` is checked per-statement, and clearing the
        # old row and setting the new one in the same flush can be batched by
        # SQLAlchemy into one executemany ordered by primary key rather than
        # by the order these assignments happened in Python -- when the new
        # row's id sorts before the old row's, that ordering would transiently
        # give two rows the same marker and trip the constraint even though
        # the end state is valid.
        previously_active.current_for_league = None
        session.flush()
    target.current_for_league = league.id
    session.flush()
    return target


def current_deadline_calendar(session: Session, league: League) -> LeagueDeadlineCalendar | None:
    """The league's currently active calendar, or ``None`` if none has been activated."""
    return session.scalar(
        select(LeagueDeadlineCalendar).where(LeagueDeadlineCalendar.current_for_league == league.id)
    )


def _season_label(season_year: int) -> str:
    return f"{season_year}-{str(season_year + 1)[-2:]}"


def _current_settings_snapshot(session: Session, league_id: int) -> LeagueSettingsSnapshot | None:
    return session.scalar(
        select(LeagueSettingsSnapshot)
        .where(LeagueSettingsSnapshot.league_id == league_id)
        .order_by(LeagueSettingsSnapshot.version.desc())
        .limit(1)
    )


def _current_schedule_refresh(session: Session, season: str) -> RefreshRun | None:
    """The season-scoped current schedule refresh.

    ``hoops_gm.db.lineage.current_refresh`` is global per ``artifact_type`` and
    is not season-aware, so it would return the wrong season's schedule if
    multiple seasons were ever refreshed out of order. This mirrors the same,
    already-established workaround as
    ``hoops_gm.availability.absence_splits._schedule_refresh``.
    """
    return session.scalar(
        select(RefreshRun)
        .where(
            RefreshRun.artifact_type == RefreshArtifactType.SCHEDULE,
            RefreshRun.season == season,
        )
        .order_by(RefreshRun.refreshed_at.desc(), RefreshRun.id.desc())
        .limit(1)
    )


def _require_plain_date(value: str, *, path: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DeadlineCalendarLineageError(
            f"{path} is not a valid ISO 8601 date: {value!r}"
        ) from exc


def _require_aware(value: str, *, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise DeadlineCalendarLineageError(
            f"{path} is not a valid ISO 8601 timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeadlineCalendarLineageError(
            f"{path} is a naive timestamp ({value!r}); refusing to guess its timezone"
        )
    return parsed


def _scoring_periods(document: LeagueSettingsDocument) -> list[dict[str, object]]:
    if not document.scoring_periods.is_known:
        return []
    rules = document.scoring_periods.value
    assert rules is not None  # is_known guarantees this

    playoff_numbers: set[int] | None = None
    if document.playoffs.is_known and document.playoffs.value is not None:
        playoff_numbers = set(document.playoffs.value.period_numbers)

    periods: list[dict[str, object]] = []
    for boundary in sorted(rules.periods, key=lambda p: p.period_number):
        start_at = _require_aware(
            boundary.start_at, path=f"scoring_periods[{boundary.period_number}].start_at"
        )
        end_at = _require_aware(
            boundary.end_at, path=f"scoring_periods[{boundary.period_number}].end_at"
        )
        is_playoff = (
            boundary.period_number in playoff_numbers if playoff_numbers is not None else None
        )
        periods.append(
            {
                "period_number": boundary.period_number,
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "is_playoff": is_playoff,
            }
        )
    return periods


def _unsupported_rules(document: LeagueSettingsDocument) -> dict[str, object]:
    serialized = document.model_dump(mode="json")
    return {field: serialized[field] for field in _TIMING_FIELDS}
