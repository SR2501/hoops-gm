"""Current raw team-by-scoring-period schedule counts for one league.

Descriptive only. This route reports how many games each NBA team is
scheduled to play inside each of the league's scoring periods, and the exact
lineage that produced those counts. It does not decide whether a week is
light, does not rank, and does not value — those are ``quant``'s under ADR-009
and are deliberately absent here.

**Where the evidence comes from.** Completeness is *not* recomputed locally.
``hoops_gm.db.lineage`` owns the single definition of "does this registered
schedule refresh still describe the rows it claims to describe"
(:func:`verify_refresh`) and the single reader of the producer's completeness
block (:func:`schedule_completeness`). An earlier version of this route
hand-rolled its own reader against flat summary keys the producer never wrote,
which made the endpoint permanently unavailable while looking rigorous. A
second verifier can only ever drift from the producer, so there is exactly
one, and this route consumes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.calendar.scoring_periods import ScoringPeriodProjectionError
from hoops_gm.db.lineage import (
    NBA_SCHEDULE_ARTIFACT_KEY,
    SCHEDULE_COMPLETENESS_SUMMARY_KEY,
    ScheduleCompleteness,
    current_refresh,
    lock_refresh_scope,
    schedule_completeness,
    verify_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType
from hoops_gm.db.models.identity import NbaTeam
from hoops_gm.db.models.league import League, ScoringPeriod
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.ingest.nba.schedule import ScheduledGameCount, scheduled_game_counts

router = APIRouter(prefix="/leagues/{league_id}/schedule-grid", tags=["schedule-grid"])


class ScheduleRefreshLineage(BaseModel):
    """The canonical NBA schedule cohort the counts were read from.

    ``persisted_team_row_count`` counts ``team_schedule`` *rows*, two per game.
    The name is the producer's (``ScheduleCompleteness``) rather than a
    friendlier one, because a consumer comparing 1,230 against 2,460 needs to
    know which of the two it is holding.
    """

    refresh_id: int
    version: str
    refreshed_at: datetime
    source_game_count: int
    resolved_game_count: int
    persisted_team_row_count: int
    unresolved_game_ids: list[str]


class ScoringPeriodProjectionLineage(BaseModel):
    refresh_id: int
    version: str
    refreshed_at: datetime


class VersionedRowLineage(BaseModel):
    id: int
    version: int


class ScheduleGridLineage(BaseModel):
    schedule: ScheduleRefreshLineage
    scoring_period_projection: ScoringPeriodProjectionLineage
    deadline_calendar: VersionedRowLineage
    settings_snapshot: VersionedRowLineage


class ScheduleGridTeam(BaseModel):
    """One NBA team appearing in ``counts``, with the labels a screen needs."""

    team_id: int
    nba_team_id: int
    abbreviation: str
    name: str


class ScheduleGridPeriod(BaseModel):
    """One scoring period appearing in ``counts``, with its Eastern dates."""

    period_number: int
    start_date: date
    end_date: date
    is_playoff: bool


class ScheduleGridCount(BaseModel):
    period_number: int
    team_id: int
    games: int


class ScheduleGridResponse(BaseModel):
    """The dense grid plus everything needed to label and trust it.

    ``teams`` and ``periods`` are read inside the same transaction and lock
    scope as ``counts``, so a caller can never render one lineage's counts
    against another lineage's row and column headers.
    """

    league_id: int
    season: str
    lineage: ScheduleGridLineage
    teams: list[ScheduleGridTeam]
    periods: list[ScheduleGridPeriod]
    counts: list[ScheduleGridCount]


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


def _verified_schedule_evidence(
    session: Session, *, season: str
) -> tuple[RefreshRun, ScheduleCompleteness]:
    """The current schedule refresh and its producer-written completeness block.

    Fails closed in three distinguishable ways, because they call for different
    operator actions: nothing registered or no longer describing its rows is
    ``schedule_grid_not_current`` (re-import the schedule), while a refresh
    that cannot state what it imported is ``schedule_grid_incomplete_evidence``
    (this row can never populate the contract, whatever the rows say).
    """

    refresh = current_refresh(
        session,
        RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=season,
    )
    if refresh is None:
        raise _error(
            409,
            "schedule_grid_not_current",
            f"season {season!r} has no current NBA schedule refresh",
        )

    summary = refresh.summary
    if not isinstance(summary, Mapping):
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh.id} has malformed source-completeness evidence: "
            "summary is not an object",
        )
    try:
        completeness = schedule_completeness(summary)
    except ValueError as exc:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh.id} has malformed source-completeness evidence: {exc}",
        ) from exc
    if completeness is None:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh.id} carries no {SCHEDULE_COMPLETENESS_SUMMARY_KEY} "
            "block and so cannot prove source completeness; re-import the schedule through "
            "the NBA schedule adapter",
        )

    try:
        verification = verify_refresh(session, refresh)
    except ValueError as exc:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh.id} has inconsistent source-completeness evidence: {exc}",
        ) from exc
    if not verification.is_current:
        raise _error(
            409,
            "schedule_grid_not_current",
            f"schedule refresh {refresh.id} registered version "
            f"{verification.registered_version!r} no longer matches the persisted schedule "
            "content for season "
            f"{season!r}",
        )
    return refresh, completeness


def _grid_teams(session: Session, rows: list[ScheduledGameCount]) -> list[ScheduleGridTeam]:
    """Label exactly the teams the counts already contain.

    The team set is taken from ``rows`` rather than by re-applying
    ``scheduled_game_counts``' own active-team filter: repeating that predicate
    here would be a second definition of "which teams are in the grid", free to
    drift from the one that produced the numbers.
    """

    team_ids = sorted({row.team_id for row in rows})
    return [
        ScheduleGridTeam(
            team_id=team_id,
            nba_team_id=nba_team_id,
            abbreviation=abbreviation,
            name=name,
        )
        for team_id, nba_team_id, abbreviation, name in session.execute(
            select(NbaTeam.id, NbaTeam.nba_team_id, NbaTeam.abbreviation, NbaTeam.name)
            .where(NbaTeam.id.in_(team_ids))
            .order_by(NbaTeam.id)
        )
    ]


def _grid_periods(
    session: Session, *, league_id: int, rows: list[ScheduledGameCount]
) -> list[ScheduleGridPeriod]:
    """Date the periods the counts already contain, for the same reason."""

    period_numbers = sorted({row.period_number for row in rows})
    return [
        ScheduleGridPeriod(
            period_number=period_number,
            start_date=start_date,
            end_date=end_date,
            is_playoff=is_playoff,
        )
        for period_number, start_date, end_date, is_playoff in session.execute(
            select(
                ScoringPeriod.period_number,
                ScoringPeriod.start_date,
                ScoringPeriod.end_date,
                ScoringPeriod.is_playoff,
            )
            .where(
                ScoringPeriod.league_id == league_id,
                ScoringPeriod.period_number.in_(period_numbers),
            )
            .order_by(ScoringPeriod.period_number)
        )
    ]


@router.get(
    "/current",
    response_model=ScheduleGridResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
    summary="The league's current raw team-by-scoring-period game-count grid",
)
def get_current_schedule_grid(
    league_id: int,
    session: SessionDep,
    request: Request,
) -> ScheduleGridResponse:
    require_loopback_host(
        request,
        error_code="schedule_grid_local_only",
        detail="The schedule grid is only served to the local machine.",
    )
    league = session.get(League, league_id)
    if league is None:
        raise _error(404, "schedule_grid_league_not_found", f"no league {league_id}")
    response_league_id = league.id
    response_season = league.season

    # Take the canonical schedule scope before reading any evidence, so the
    # refresh row checked here is the same one ``scheduled_game_counts`` reads
    # under the same lock a moment later.
    lock_refresh_scope(
        session,
        artifact_type=RefreshArtifactType.SCHEDULE,
        artifact_key=NBA_SCHEDULE_ARTIFACT_KEY,
        season=response_season,
    )
    refresh, completeness = _verified_schedule_evidence(session, season=response_season)
    schedule_refresh_id = refresh.id
    schedule_version = refresh.version
    schedule_refreshed_at = refresh.refreshed_at

    try:
        rows = scheduled_game_counts(
            session,
            league_id=response_league_id,
            season=response_season,
        )
    except ScoringPeriodProjectionError as exc:
        raise _error(409, "schedule_grid_not_current", str(exc)) from exc

    if not rows:
        raise _error(
            409,
            "schedule_grid_incomplete",
            f"current schedule grid for league {response_league_id} has no rows",
        )

    first = rows[0]
    if first.schedule_refresh_id != schedule_refresh_id:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"the grid was counted against schedule refresh {first.schedule_refresh_id} but "
            f"{schedule_refresh_id} is the verified current one",
        )
    if sum(row.games for row in rows) == 0:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {schedule_refresh_id} records "
            f"{completeness.resolved_game_count} resolved game(s) for season "
            f"{response_season!r}, but none of them fall inside a scoring period of league "
            f"{response_league_id}",
        )

    teams = _grid_teams(session, rows)
    periods = _grid_periods(session, league_id=response_league_id, rows=rows)

    # The strict query reserves lineage scopes with transaction locks. This API
    # only returns copied dataclass values, so release those locks without
    # committing SQLite's no-op write reservations.
    session.rollback()

    return ScheduleGridResponse(
        league_id=response_league_id,
        season=response_season,
        lineage=ScheduleGridLineage(
            schedule=ScheduleRefreshLineage(
                refresh_id=schedule_refresh_id,
                version=schedule_version,
                refreshed_at=schedule_refreshed_at,
                source_game_count=completeness.source_game_count,
                resolved_game_count=completeness.resolved_game_count,
                persisted_team_row_count=completeness.persisted_team_row_count,
                unresolved_game_ids=list(completeness.unresolved_game_ids),
            ),
            scoring_period_projection=ScoringPeriodProjectionLineage(
                refresh_id=first.projection_refresh_id,
                version=first.projection_version,
                refreshed_at=first.projection_refreshed_at,
            ),
            deadline_calendar=VersionedRowLineage(
                id=first.deadline_calendar_id,
                version=first.deadline_calendar_version,
            ),
            settings_snapshot=VersionedRowLineage(
                id=first.settings_snapshot_id,
                version=first.settings_snapshot_version,
            ),
        ),
        teams=teams,
        periods=periods,
        counts=[
            ScheduleGridCount(
                period_number=row.period_number,
                team_id=row.team_id,
                games=row.games,
            )
            for row in rows
        ],
    )
