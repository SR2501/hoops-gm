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
    lock_league_settings_scope,
    lock_refresh_scope,
    schedule_completeness,
    verify_refresh,
)
from hoops_gm.db.models.enums import RefreshArtifactType, SeasonType
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

    ``unresolved_game_ids`` is provably always empty on a 200: the canonical
    verifier refuses a completeness block recording any, and this route maps
    that refusal to 409. It is carried anyway so a consumer can read the claim
    it is trusting instead of inferring it from the code — but nothing should be
    built on the assumption that a non-empty list is servable.
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
    """The dense grid plus what a screen needs to label and trust it.

    ``periods`` is snapshot-consistent with ``counts``: ``scoring_periods`` is
    written only by ``project_scoring_periods``, which takes the projection
    scope lock this read already holds.

    ``teams`` is **not**, and the difference is worth naming rather than
    glossing. ``nba_teams`` is written by ``import_teams``, which takes no
    lineage lock, and PostgreSQL's READ COMMITTED gives each statement its own
    snapshot — so a franchise renamed between the counts statement and the team
    statement would be labelled from the newer one. What cannot change is which
    franchise a ``team_id`` denotes: it is a surrogate key with a unique
    ``nba_team_id``, and ``import_teams`` only ever refreshes ``abbreviation``,
    ``name`` and ``city`` on an existing row. So the residual risk is a fresher
    display label on the right team, never a count attributed to the wrong one.
    Closing even that would need a lineage scope for ``nba_teams``, which is
    ``data-engineer``'s to define.
    """

    league_id: int
    season: str
    lineage: ScheduleGridLineage
    teams: list[ScheduleGridTeam]
    periods: list[ScheduleGridPeriod]
    counts: list[ScheduleGridCount]


def _error(status_code: int, code: str, detail: str) -> HTTPException:
    """Raise inside the app's error contract.

    ``X-Bridge-Error`` is **not** a response header. ``app.py``'s handler reads
    it off the exception and returns the code in ``ErrorResponse.error``; the
    only header on the way out is ``X-Request-ID``. The name is a legacy of the
    bridge routes that introduced this transport.
    """

    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={"X-Bridge-Error": code},
    )


def _verified_schedule_evidence(
    session: Session, *, season: str
) -> tuple[RefreshRun, ScheduleCompleteness]:
    """The current schedule refresh and its producer-written completeness block.

    **This runs before ``scheduled_game_counts`` on purpose.**
    ``require_current_scoring_period_projection`` also verifies the schedule,
    but funnels a malformed completeness block, a fingerprint mismatch and
    twenty-odd unrelated configuration faults into one broad
    ``ScoringPeriodProjectionError``. Mapping that to a single code would make
    the two refusals a caller most needs to tell apart indistinguishable.
    Reading the same refresh here first, under the same scope locks and through
    the same canonical functions, keeps them distinct without adding a second
    verifier.

    Two outcomes, because they call for different operator actions: nothing
    registered, or a registration that no longer describes its rows, is
    ``schedule_grid_not_current`` — re-import the schedule. A refresh that
    cannot state what it imported, or states something inconsistent, is
    ``schedule_grid_incomplete_evidence`` — that row can never populate the
    contract, whatever the rows say.
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
    # `verify_refresh` fingerprints the cohort at whatever season type the block
    # names, while `scheduled_game_counts` counts REGULAR unconditionally. Today
    # they agree only because `import_schedule` hard-codes REGULAR. If a playoff
    # cohort were ever registered under this artifact key, the route would
    # verify one cohort and count another, and return 200 with a lineage block
    # that does not describe the numbers beside it — the same failure this
    # module exists to close, arriving through scope instead of a second
    # verifier.
    if completeness.season_type is not SeasonType.REGULAR:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            f"schedule refresh {refresh.id} describes a "
            f"{completeness.season_type.value!r} cohort, but this grid counts regular-season "
            "games only",
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
    """Label exactly the teams the counts already contain, or refuse.

    The team set is taken from ``rows`` rather than by re-applying
    ``scheduled_game_counts``' own active-team filter: repeating that predicate
    here would be a second definition of "which teams are in the grid", free to
    drift from the one that produced the numbers.

    The set equality is then enforced rather than assumed. A short label list
    would render as unlabelled columns — a partially-labelled grid that still
    looks like an answer — which is worse than a refusal.
    """

    team_ids = sorted({row.team_id for row in rows})
    teams = [
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
    if [team.team_id for team in teams] != team_ids:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            "the grid counts teams "
            f"{sorted(set(team_ids) - {team.team_id for team in teams})} that have no team row",
        )
    return teams


def _grid_periods(
    session: Session, *, league_id: int, rows: list[ScheduledGameCount]
) -> list[ScheduleGridPeriod]:
    """Date the periods the counts already contain, or refuse, for the same reason."""

    period_numbers = sorted({row.period_number for row in rows})
    periods = [
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
    if [period.period_number for period in periods] != period_numbers:
        raise _error(
            409,
            "schedule_grid_incomplete_evidence",
            "the grid counts scoring periods "
            f"{sorted(set(period_numbers) - {period.period_number for period in periods})} "
            f"that league {league_id} has no row for",
        )
    return periods


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

    # Take the lineage scopes in the codebase's canonical order —
    # league-settings, then the canonical NBA schedule — before reading any
    # evidence. Order matters, not just coverage: `_locked_projection_context`
    # and `_lock_calendar_inputs` both take them this way round, and on
    # PostgreSQL `acquire_transaction_lock` issues a real `pg_advisory_xact_lock`
    # held to commit, so taking the schedule scope first would let this read and
    # a concurrent calendar derivation or period projection deadlock each other.
    # Re-acquisition inside `scheduled_game_counts` is harmless; advisory locks
    # are counted per session, and SQLite's write reservation is a no-op update.
    lock_league_settings_scope(session, league_id=response_league_id, season=response_season)
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
        # Deliberately one code for a broad class. `ScoringPeriodProjectionError`
        # covers roughly twenty-five causes — no active calendar, no settings
        # snapshot, a calendar bound to another league, a timezone-naive
        # boundary — and only `StaleScoringPeriodProjectionError` means stale.
        # Splitting them would need a sixth error code, and the contract's five
        # are frozen with a frontend already coding against them. The
        # distinction that mattered (completeness and fingerprint evidence) is
        # made above, before this call; the rest is carried in `detail`, which
        # is the underlying message verbatim rather than a re-narration.
        raise _error(409, "schedule_grid_not_current", str(exc)) from exc

    if not rows:
        raise _error(
            409,
            "schedule_grid_incomplete",
            f"current schedule grid for league {response_league_id} has no rows",
        )

    first = rows[0]
    # Unreachable today: ``_verified_schedule_evidence`` and
    # ``_locked_projection_context`` resolve the refresh with the identical
    # ``current_refresh`` call inside one transaction holding that scope lock.
    # Kept because that identity is an invariant of a module this route does not
    # own — if ``scheduled_game_counts`` ever resolves its schedule cohort
    # differently, this fails closed rather than serving two lineages as one.
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
