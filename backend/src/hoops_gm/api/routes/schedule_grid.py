"""Current raw team-by-scoring-period schedule counts for one league."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.schemas import ErrorResponse
from hoops_gm.api.security import require_loopback_host
from hoops_gm.calendar.scoring_periods import ScoringPeriodProjectionError
from hoops_gm.db.models.league import League
from hoops_gm.db.models.lineage import RefreshRun
from hoops_gm.ingest.nba.schedule import scheduled_game_counts

router = APIRouter(prefix="/leagues/{league_id}/schedule-grid", tags=["schedule-grid"])


class ScheduleRefreshLineage(BaseModel):
    refresh_id: int
    version: str
    refreshed_at: datetime
    source_game_count: int
    resolved_game_count: int
    team_schedule_rows: int
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


def _schedule_completeness(
    session: Session,
    *,
    refresh_id: int,
    counted_team_games: int,
) -> tuple[int, int, int, list[str]]:
    refresh = session.get(RefreshRun, refresh_id)
    if refresh is None:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} is unavailable",
        )

    summary = refresh.summary
    if not isinstance(summary, dict):
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} has malformed source-completeness evidence",
        )

    required = {
        "source_game_count",
        "resolved_game_count",
        "team_schedule_rows",
        "unresolved_game_ids",
    }
    missing = sorted(required - summary.keys())
    if missing:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} cannot prove source completeness; "
            f"missing summary evidence: {', '.join(missing)}",
        )

    source_game_count = summary["source_game_count"]
    resolved_game_count = summary["resolved_game_count"]
    team_schedule_rows = summary["team_schedule_rows"]
    unresolved_game_ids = summary["unresolved_game_ids"]
    if (
        not isinstance(source_game_count, int)
        or isinstance(source_game_count, bool)
        or source_game_count < 0
        or not isinstance(resolved_game_count, int)
        or isinstance(resolved_game_count, bool)
        or resolved_game_count < 0
        or not isinstance(team_schedule_rows, int)
        or isinstance(team_schedule_rows, bool)
        or team_schedule_rows < 0
        or not isinstance(unresolved_game_ids, list)
        or any(not isinstance(game_id, str) or not game_id for game_id in unresolved_game_ids)
    ):
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} has malformed source-completeness evidence",
        )
    if unresolved_game_ids:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} has unresolved game assignments: "
            f"{', '.join(unresolved_game_ids)}",
        )
    if source_game_count != resolved_game_count or team_schedule_rows != resolved_game_count * 2:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} does not describe one resolved two-team row pair "
            "for every source game",
        )
    if source_game_count == 0 or counted_team_games == 0:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} cannot prove a non-empty game-count grid",
        )
    if counted_team_games > team_schedule_rows:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh_id} has fewer persisted team rows than the grid counts",
        )
    return (
        source_game_count,
        resolved_game_count,
        team_schedule_rows,
        unresolved_game_ids,
    )


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
    counted_team_games = sum(row.games for row in rows)
    (
        source_game_count,
        resolved_game_count,
        team_schedule_rows,
        unresolved_game_ids,
    ) = _schedule_completeness(
        session,
        refresh_id=first.schedule_refresh_id,
        counted_team_games=counted_team_games,
    )

    # The strict query reserves lineage scopes with transaction locks. This API
    # only returns copied dataclass values, so release those locks without
    # committing SQLite's no-op write reservations.
    session.rollback()

    return ScheduleGridResponse(
        league_id=response_league_id,
        season=response_season,
        lineage=ScheduleGridLineage(
            schedule=ScheduleRefreshLineage(
                refresh_id=first.schedule_refresh_id,
                version=first.schedule_version,
                refreshed_at=first.schedule_refreshed_at,
                source_game_count=source_game_count,
                resolved_game_count=resolved_game_count,
                team_schedule_rows=team_schedule_rows,
                unresolved_game_ids=unresolved_game_ids,
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
