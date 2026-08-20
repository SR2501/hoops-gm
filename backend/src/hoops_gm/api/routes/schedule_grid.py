"""Current raw team-by-scoring-period schedule counts for one league."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.security import require_loopback_host
from hoops_gm.calendar.scoring_periods import ScoringPeriodProjectionError
from hoops_gm.db.models.league import League
from hoops_gm.ingest.nba.schedule import scheduled_game_counts

router = APIRouter(prefix="/leagues/{league_id}/schedule-grid", tags=["schedule-grid"])


class ScheduleRefreshLineage(BaseModel):
    refresh_id: int
    version: str
    refreshed_at: datetime


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


class ScheduleGridCount(BaseModel):
    period_number: int
    team_id: int
    games: int


class ScheduleGridResponse(BaseModel):
    league_id: int
    season: str
    lineage: ScheduleGridLineage
    counts: list[ScheduleGridCount]


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


@router.get(
    "/current",
    response_model=ScheduleGridResponse,
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

    try:
        rows = scheduled_game_counts(
            session,
            league_id=league.id,
            season=league.season,
        )
    except ScoringPeriodProjectionError as exc:
        raise _error(409, "schedule_grid_not_current", str(exc)) from exc

    if not rows:
        raise _error(
            409,
            "schedule_grid_incomplete",
            f"current schedule grid for league {league.id} has no rows",
        )

    first = rows[0]
    return ScheduleGridResponse(
        league_id=league.id,
        season=league.season,
        lineage=ScheduleGridLineage(
            schedule=ScheduleRefreshLineage(
                refresh_id=first.schedule_refresh_id,
                version=first.schedule_version,
                refreshed_at=first.schedule_refreshed_at,
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
        counts=[
            ScheduleGridCount(
                period_number=row.period_number,
                team_id=row.team_id,
                games=row.games,
            )
            for row in rows
        ],
    )
