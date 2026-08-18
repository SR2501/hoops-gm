"""League deadline calendar: the read-only HTTP surface over a league's current calendar.

Read-only from the API's perspective, mirroring ``lineage.py``: nothing here
derives or activates a calendar. Those are internal operations performed by
``hoops_gm.calendar.deadline_calendar`` inside a producer's own transaction
(the settings/schedule ingestion pipelines), not through this router. What
the API exposes is the one question a downstream consumer (the notification
engine, the dashboard) actually has: what is the league's current calendar.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from hoops_gm.api.deps import SessionDep
from hoops_gm.api.security import require_loopback_host
from hoops_gm.calendar.deadline_calendar import current_deadline_calendar
from hoops_gm.db.models.league import League

router = APIRouter(prefix="/leagues/{league_id}/deadline-calendar", tags=["deadline-calendar"])


class ScoringPeriodWindow(BaseModel):
    """One scoring-period boundary, exactly as the settings snapshot supplied it."""

    period_number: int
    start_at: str
    end_at: str
    #: ``None`` when the source never supplied a playoff marker for this
    #: period -- never defaulted to ``False``.
    is_playoff: bool | None


class DeadlineCalendarResponse(BaseModel):
    """A league's derived calendar.

    Known dates, plus every unsupported rule as an explicit unknown.
    """

    league_id: int
    version: int
    season: str
    settings_snapshot_version: int
    schedule_version: str
    season_start_date: date
    season_end_date: date
    scoring_periods: list[ScoringPeriodWindow]
    #: ``lineup_lock``, ``waivers``, ``trade_deadline``, ``keepers``,
    #: ``playoffs`` -- each the settings snapshot's raw ``{value, evidence}``
    #: pair. See ``hoops_gm.db.models.deadline_calendar`` for why "unsupported"
    #: does not mean "necessarily unknown".
    unsupported_rules: dict[str, object]
    derived_at: datetime


@router.get(
    "/current",
    response_model=DeadlineCalendarResponse,
    summary="The league's current activated deadline calendar",
)
def get_current_deadline_calendar(
    league_id: int, session: SessionDep, request: Request
) -> DeadlineCalendarResponse:
    # This response carries bridge-derived rule values verbatim, including
    # ``source_path``/``capture_ref`` provenance (see ``unsupported_rules``
    # below) -- unlike ``lineage.py``'s summary-only reads, that is not safe
    # to hand to an arbitrary caller. No bridge secret is required: this is
    # an ordinary dashboard read, not a bridge write.
    require_loopback_host(
        request,
        error_code="deadline_calendar_local_only",
        detail="The deadline calendar is only served to the local machine.",
    )
    league = session.get(League, league_id)
    if league is None:
        raise HTTPException(status_code=404, detail=f"no league {league_id}")

    calendar = current_deadline_calendar(session, league)
    if calendar is None:
        raise HTTPException(
            status_code=404, detail=f"no active deadline calendar for league {league_id}"
        )

    return DeadlineCalendarResponse(
        league_id=calendar.league_id,
        version=calendar.version,
        season=calendar.season,
        settings_snapshot_version=calendar.settings_snapshot_version,
        schedule_version=calendar.schedule_version,
        season_start_date=calendar.season_start_date,
        season_end_date=calendar.season_end_date,
        scoring_periods=[
            ScoringPeriodWindow.model_validate(period) for period in calendar.scoring_periods
        ],
        unsupported_rules=calendar.unsupported_rules,
        derived_at=calendar.derived_at,
    )
